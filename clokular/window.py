"""The answer window that opens next to Okular."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from . import claude, log, session


class _Bridge(QObject):
    """Carries events from worker threads to the GUI thread."""
    prepared = Signal(object)
    event = Signal(object)
    failed = Signal(str)


class AnswerWindow(QWidget):
    def __init__(self, selection: str):
        super().__init__()
        self.selection = selection
        self.prep: session.Prepared | None = None
        self.session_id: str | None = None
        self.history_md = ""  # earlier Q&A, shown above the current answer
        self.procs: list = []
        self.busy = False
        self.bridge = _Bridge()
        self.bridge.prepared.connect(self._on_prepared)
        self.bridge.event.connect(self._on_event)
        self.bridge.failed.connect(self._on_failed)

        self.setWindowTitle("Claude")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        quote = QLabel(self._elide(selection, 320))
        quote.setWordWrap(True)
        quote.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        qf = quote.font()
        qf.setItalic(True)
        quote.setFont(qf)
        quote.setStyleSheet("QLabel { border-left: 3px solid palette(highlight); padding: 2px 0 2px 10px;"
                            " color: palette(placeholder-text); }")
        lay.addWidget(quote)

        self.status = QLabel("Finding your place in the book…")
        sf = self.status.font()
        sf.setPointSizeF(sf.pointSizeF() * 0.92)
        self.status.setFont(sf)
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self.status)

        self.answer = QTextBrowser()
        self.answer.setOpenExternalLinks(True)
        self.answer.setFrameShape(QTextBrowser.Shape.NoFrame)
        self.answer.setStyleSheet("QTextBrowser { background: transparent; }")
        af = self.answer.font()
        af.setPointSizeF(af.pointSizeF() * 1.05)
        self.answer.setFont(af)
        lay.addWidget(self.answer, 1)

        row = QHBoxLayout()
        self.ask = QLineEdit()
        self.ask.setPlaceholderText("Ask a follow-up…")
        self.ask.setClearButtonEnabled(True)
        self.ask.returnPressed.connect(self._ask)
        self.send = QPushButton("Ask")
        self.send.clicked.connect(self._ask)
        row.addWidget(self.ask, 1)
        row.addWidget(self.send)
        lay.addLayout(row)

        self.footer = QLabel("")
        ff = self.footer.font()
        ff.setPointSizeF(ff.pointSizeF() * 0.85)
        self.footer.setFont(ff)
        self.footer.setStyleSheet("color: palette(placeholder-text);")
        self.footer.setWordWrap(True)
        lay.addWidget(self.footer)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.close)
        self._set_busy(True)
        settings = QSettings("clokular", "clokular")
        self.resize(settings.value("size", self.sizeHint().expandedTo(self.minimumSizeHint())))
        if self.width() < 300:
            self.resize(540, 620)
        threading.Thread(target=self._prepare, daemon=True).start()

    # ---- helpers -------------------------------------------------------
    @staticmethod
    def _elide(text: str, n: int) -> str:
        text = " ".join(text.split())
        return text if len(text) <= n else text[: n - 1].rstrip() + "…"

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.ask.setEnabled(not busy)
        self.send.setEnabled(not busy)
        if not busy:
            self.ask.setFocus()

    def _show(self, current_md: str) -> None:
        bar = self.answer.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        self.answer.setMarkdown(self.history_md + current_md)
        if at_bottom or not self.history_md:
            bar.setValue(bar.maximum() if self.history_md else 0)

    # ---- preparing -----------------------------------------------------
    def _prepare(self) -> None:
        try:
            self.bridge.prepared.emit(session.prepare(self.selection))
        except Exception as e:  # noqa: BLE001
            self.bridge.failed.emit(f"Something went wrong preparing the request: {e}")

    def _on_prepared(self, prep: session.Prepared) -> None:
        self.prep = prep
        log.write(f"prepared: title={prep.title!r} page={prep.page}/{prep.pages} located={prep.located} "
                  f"workdir={prep.workdir} warnings={prep.warnings}")
        if prep.title:
            self.setWindowTitle(f"Claude · {prep.title}")
        if prep.page and prep.pages and prep.located:
            self.footer.setText(f"Claude only knows what you've read: through page {prep.page} of {prep.pages}.")
        elif not prep.located:
            self.footer.setText("Claude sees only the highlighted passage.")
        if prep.warnings:
            self.footer.setText((self.footer.text() + "\n" if self.footer.text() else "") + " ".join(prep.warnings))
        self.status.setText("Thinking…")
        self._start(prep.prompt, resume=None)

    # ---- running claude -----------------------------------------------
    def _start(self, prompt: str, resume: str | None) -> None:
        self._set_busy(True)
        workdir = self.prep.workdir

        def work():
            try:
                claude.run(prompt, workdir, self.bridge.event.emit, resume=resume, proc_holder=self.procs)
            except Exception as e:  # noqa: BLE001
                self.bridge.event.emit(claude.Event("error", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_event(self, ev: claude.Event) -> None:
        if ev.session_id:
            self.session_id = ev.session_id
        if ev.kind == "tool":
            self.status.setText("Looking back through what you've read…")
        elif ev.kind == "text":
            self.status.setText("Writing…")
            self._show(ev.text)
        elif ev.kind == "done":
            log.write(f"answer ({len(ev.text)} chars, session {ev.session_id}): {ev.text[:300]!r}")
            self._show(ev.text)
            self.history_md += ev.text + "\n\n"
            self.status.setText("")
            self.status.hide()
            self._set_busy(False)
            snap = os.environ.get("CLOKULAR_SNAPSHOT")
            if snap:  # for testing: save a picture of this window
                QTimer.singleShot(300, lambda: self.grab().save(snap))
        elif ev.kind == "error":
            self._on_failed(ev.text)

    def _on_failed(self, msg: str) -> None:
        log.write(f"error: {msg}")
        self.status.show()
        self.status.setText("⚠ " + msg)
        self.status.setStyleSheet("color: palette(link-visited);")
        self._set_busy(False)
        if self.prep is None:
            self.ask.setEnabled(False)
            self.send.setEnabled(False)

    def _ask(self) -> None:
        q = self.ask.text().strip()
        if not q or self.busy or not self.prep:
            return
        self.ask.clear()
        self.history_md += f"---\n\n**You:** {q}\n\n"
        self._show("")
        self.status.show()
        self.status.setStyleSheet("color: palette(placeholder-text);")
        self.status.setText("Thinking…")
        self._start(session.follow_up_message(q), resume=self.session_id)

    def closeEvent(self, e):  # noqa: N802
        QSettings("clokular", "clokular").setValue("size", self.size())
        for p in self.procs:
            if p.poll() is None:
                p.kill()
        super().closeEvent(e)


def show(selection: str) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("clokular")
    app.setDesktopFileName("clokular")
    app.setApplicationDisplayName("Claude")
    icon_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons", "clokular-claude.svg")
    app.setWindowIcon(QIcon.fromTheme("clokular-claude", QIcon(icon_file)))
    w = AnswerWindow(selection)
    w.show()
    w.raise_()
    w.activateWindow()
    QTimer.singleShot(1500, lambda: log.write(
        f"window: exposed={w.windowHandle().isExposed() if w.windowHandle() else None} "
        f"active={w.isActiveWindow()} token={'yes' if os.environ.get('XDG_ACTIVATION_TOKEN') else 'no'} "
        f"platform={app.platformName()}"))
    return app.exec()


def show_error(message: str) -> int:
    app = QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.warning(None, "Claude", message)
    return 1
