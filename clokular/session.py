"""Turn a highlighted passage into a prepared Claude request: find the book,
find the reader's place, and write out exactly what they've read."""

from __future__ import annotations

import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import book as booklib
from . import okular
from .locate import BookText, context_before, locate, okular_to_book_page, read_so_far
from .prompt import READ_FILE, first_message

_RANK = {"near-page": 0, "nearby": 1, "before-page": 2, "first-occurrence": 3}
KEEP_SESSIONS_DAYS = 14


@dataclass
class Prepared:
    selection: str
    workdir: str
    prompt: str
    title: str = ""
    page: int | None = None
    pages: int | None = None
    located: bool = False
    warnings: list[str] = field(default_factory=list)


def sessions_dir() -> Path:
    d = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "clokular" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cleanup_old() -> None:
    cutoff = time.time() - KEEP_SESSIONS_DAYS * 86400
    for d in sessions_dir().iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _tidy(text: str) -> str:
    # Okular's layout pads chapters with blank lines and leaves U+FFFC where
    # images were; squeeze both out for Claude.
    text = text.replace("￼", "")
    return re.sub(r"\n[ \t]*(\n[ \t]*){2,}", "\n\n", text)


def choose(selection: str, docs: list[okular.OpenDocument], loader=booklib.load):
    """Pick the open document (and place in it) that best matches the selection."""
    best = None
    errors = []
    for doc in docs:
        if booklib.kind(doc.path) is None:
            continue
        try:
            text = loader(doc.path)
        except Exception as e:  # noqa: BLE001 - surface any reader failure as a warning
            errors.append(f"{Path(doc.path).name}: {e}")
            continue
        loc = locate(text, selection, doc.page, doc.pages)
        rank = _RANK[loc.method] if loc else 9
        if best is None or rank < best[0]:
            best = (rank, doc, text, loc)
        if rank == 0:
            break
    return best, errors


def prepare(selection: str, docs: list[okular.OpenDocument] | None = None, loader=booklib.load) -> Prepared:
    _cleanup_old()
    workdir = sessions_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    workdir.mkdir()
    if docs is None:
        docs = okular.open_documents()
    best, errors = choose(selection, docs, loader)
    warnings = list(errors)
    title = author = ""
    page = pages = None
    located = False
    context = ""
    so_far = ""
    note = ""
    if best is None:
        if not docs:
            warnings.append("Couldn't reach Okular to see which book is open, so Claude only sees the passage.")
        elif not errors:
            warnings.append("The open document isn't an EPUB or PDF, so Claude only sees the passage.")
    else:
        _, doc, text, loc = best
        title = text.title or Path(doc.path).stem
        author = text.author
        page, pages = doc.page, doc.pages
        if loc is not None:
            located = True
            so_far = read_so_far(text, loc)
            context = context_before(text, loc)
            if loc.method == "first-occurrence":
                warnings.append("Couldn't pin down this passage near your page, so Claude is using the first "
                                "place it appears. It may know less than you do, but it won't know more.")
            elif loc.notes:
                note = "Note: only part of the highlight matched the book's text exactly."
        else:
            so_far, context = _before_page(text, doc)
            warnings.append("Couldn't find the highlighted text in the book, so Claude sees the pages "
                            "before this one plus the passage itself.")
            located = bool(so_far)
            note = "The highlight itself wasn't found in the text; the excerpt ends just before the reader's page."
    (workdir / READ_FILE).write_text(_tidy(so_far), encoding="utf-8")
    prompt = first_message(selection=selection, context=_tidy(context), title=title, author=author,
                           page=page, pages=pages, located=located, note=note)
    return Prepared(selection, str(workdir), prompt, title, page, pages, located, warnings)


def _before_page(text: BookText, doc: okular.OpenDocument) -> tuple[str, str]:
    p = okular_to_book_page(text, doc.page, doc.pages)
    safe = max(0, p - (0 if text.exact_pages else 2))
    end = text.page_starts[safe] if safe < text.page_count else 0
    so_far = text.text[:end]
    return so_far, so_far[-9000:]


def follow_up_message(question: str) -> str:
    return question.strip()
