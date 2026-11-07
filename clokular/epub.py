"""EPUB text extraction that follows Okular's own page layout.

Okular's EPUB backend (generators/epub/converter.cpp) pours every spine item
into one QTextDocument with 600x800 pages, padding each item with newlines so
the next one starts on a fresh page. We repeat those steps with PySide6 so
that page numbers line up closely with what Okular shows.

Needs a QGuiApplication; run it through ``python -m clokular index`` (which
uses the offscreen platform) so layout doesn't depend on the screen.
"""

from __future__ import annotations

import posixpath
import re
import zipfile

from PySide6.QtCore import QSizeF, QUrl
from PySide6.QtGui import QFont, QImage, QTextBlockFormat, QTextCursor, QTextDocument
from PySide6.QtXml import QDomDocument

from .locate import BookText

PAGE_W, PAGE_H, PADDING = 600, 800, 20


def _opf(z: zipfile.ZipFile) -> tuple[str, str]:
    container = z.read("META-INF/container.xml").decode("utf-8", "replace")
    path = re.search(r'full-path="([^"]+)"', container).group(1)
    return path, z.read(path).decode("utf-8", "replace")


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', tag) or re.search(rf"\b{name}\s*=\s*'([^']*)'", tag)
    return m.group(1) if m else None


def spine_and_meta(z: zipfile.ZipFile) -> tuple[str, list[str], str, str]:
    opf_path, opf = _opf(z)
    base = posixpath.dirname(opf_path)
    manifest = {}
    for m in re.finditer(r"<(?:\w+:)?item\b[^>]*>", opf):
        i, h = _attr(m.group(0), "id"), _attr(m.group(0), "href")
        if i and h:
            manifest[i] = h
    spine = []
    for m in re.finditer(r"<(?:\w+:)?itemref\b[^>]*>", opf):
        ref = _attr(m.group(0), "idref")
        if ref in manifest:
            spine.append(manifest[ref])

    def meta(tag: str) -> str:
        mm = re.search(rf"<dc:{tag}\b[^>]*>(.*?)</dc:{tag}>", opf, re.S)
        return re.sub(r"\s+", " ", mm.group(1)).strip() if mm else ""

    return base, spine, _unescape(meta("title")), _unescape(meta("creator"))


def _unescape(s: str) -> str:
    import html

    return html.unescape(s)


class _EpubDocument(QTextDocument):
    def __init__(self, z: zipfile.ZipFile, base: str, font: QFont):
        super().__init__()
        self._z, self._base, self._font = z, base, font
        self._sub = QUrl()
        self.setPageSize(QSizeF(PAGE_W, PAGE_H))
        self.setDefaultStyleSheet("a { color: #0000ff }")

    def set_current_subdocument(self, link: str) -> None:
        i = link.find("/")
        self._sub = QUrl.fromLocalFile(link[: i + 1]) if i > 0 else QUrl()

    def read(self, path: str) -> bytes | None:
        p = posixpath.normpath(posixpath.join(self._base, QUrl.fromPercentEncoding(path.lstrip("/").encode())))
        try:
            return self._z.read(p)
        except KeyError:
            return None

    def _check_css(self, css: str) -> str:
        css = re.sub(r"line-height\s*:\s*[\w\.]*;", "", css)
        out = []
        for item in re.split(r"\s+", css):
            m = re.match(r"(([0-9]+)(\.[0-9]+)?)r?em(.*)", item)
            out.append(f"{float(m.group(1)) * self._font.pointSize():g}px{m.group(4)}" if m else item)
        return " ".join(out)

    def loadResource(self, typ, name):  # noqa: N802 (Qt override)
        data = self.read(self._sub.resolved(name).path())
        if not data:
            return None
        t = int(typ.value) if hasattr(typ, "value") else int(typ)
        if t == QTextDocument.ResourceType.ImageResource.value:
            img = QImage.fromData(data)
            if img.height() > PAGE_H - 2 * PADDING:
                img = img.scaledToHeight(PAGE_H - 2 * PADDING)
            if img.width() > PAGE_W - 2 * PADDING:
                img = img.scaledToWidth(PAGE_W - 2 * PADDING)
            return img
        if t == QTextDocument.ResourceType.StyleSheetResource.value:
            return self._check_css(data.decode("utf-8", "replace"))
        return None


def _page_starts(doc: QTextDocument) -> list[int]:
    """Character offset of the first line on each page."""
    pages = doc.pageCount()
    starts = [-1] * pages
    layout = doc.documentLayout()
    block = doc.begin()
    while block.isValid():
        top = layout.blockBoundingRect(block).top()
        bl = block.layout()
        for i in range(bl.lineCount()):
            line = bl.lineAt(i)
            pg = int((top + line.y()) // PAGE_H)
            if 0 <= pg < pages and starts[pg] == -1:
                starts[pg] = block.position() + line.textStart()
        block = block.next()
    # Pages with no line of their own (an image-only page) start where the next one does.
    nxt = doc.characterCount() - 1
    for i in range(pages - 1, -1, -1):
        if starts[i] == -1:
            starts[i] = nxt
        nxt = starts[i]
    starts[0] = 0
    for i in range(1, pages):  # keep monotonic
        starts[i] = max(starts[i], starts[i - 1])
    return starts


def extract(path: str, font: QFont) -> BookText:
    z = zipfile.ZipFile(path)
    base, spine, title, author = spine_and_meta(z)
    doc = _EpubDocument(z, base, font)
    cursor = QTextCursor(doc)
    first = True
    for link in spine:
        raw = doc.read(link)
        if raw is None:
            continue
        doc.set_current_subdocument(link)
        html = raw.decode("utf-8", "replace")
        html = re.sub(r"< *section", "<p", html)
        html = re.sub(r"< */ *section", "</p", html)
        dom = QDomDocument()
        if dom.setContent(html):
            html = dom.toString()
        if first:
            doc.setHtml(html)
            first = False
        else:
            cursor.insertHtml(html)
        page = doc.pageCount()
        cursor.insertBlock(QTextBlockFormat())
        while doc.pageCount() == page:
            cursor.insertText("\n")
    doc.setDefaultFont(font)
    text = doc.toPlainText()
    return BookText(text=text, page_starts=_page_starts(doc), exact_pages=False, title=title, author=author)
