"""Find the reader's place in a book and decide what counts as "read so far".

Everything here is pure (no Qt, no I/O) so the spoiler boundary can be tested.

A ``BookText`` is the book's plain text plus ``page_starts``: the character
offset where each page begins, in reading order. For PDFs those pages are
Okular's real pages. For EPUBs they come from a replica of Okular's layout and
may not number exactly like Okular, so Okular's page number is scaled onto them.
"""

from __future__ import annotations

import bisect
import unicodedata
from dataclasses import dataclass, field

# Characters folded together so that Okular's selected text matches our
# extracted text even when typography differs (curly vs straight quotes, etc.).
_FOLD = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
        "―": "-", "−": "-",
        " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    }
)
_DROP = {"­", "￼", "​", "‌", "‍", "﻿"}

# How much text after the selection may be included: never past the end of the
# page the selection is on, and never more than this many characters.
MAX_AFTER_SELECTION = 2500
# How much text before the selection is quoted directly to Claude.
CONTEXT_BEFORE = 9000


@dataclass
class BookText:
    text: str
    page_starts: list[int]
    exact_pages: bool = False  # True when page_starts are Okular's real pages (PDF)
    title: str = ""
    author: str = ""

    @property
    def page_count(self) -> int:
        return len(self.page_starts)

    def page_of(self, offset: int) -> int:
        """0-based page index containing ``offset``."""
        return max(0, bisect.bisect_right(self.page_starts, offset) - 1)

    def page_end(self, page: int) -> int:
        return self.page_starts[page + 1] if page + 1 < len(self.page_starts) else len(self.text)


@dataclass
class Location:
    start: int  # offset of the selection in BookText.text
    end: int
    cutoff: int  # everything before this offset counts as read
    page: int  # 0-based page in BookText's own numbering
    method: str  # "near-page", "nearby", "before-page", "first-occurrence"
    occurrences: int = 1
    notes: list[str] = field(default_factory=list)


def normalize(text: str) -> tuple[str, list[int]]:
    """Fold typography and whitespace; return (normalized, index map to original)."""
    out: list[str] = []
    idx: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        if ch in _DROP:
            continue
        ch = ch.translate(_FOLD)
        if not ch.isascii():
            ch = unicodedata.normalize("NFKC", ch)
        for c in ch:
            if c.isspace():
                if prev_space:
                    continue
                prev_space = True
                out.append(" ")
                idx.append(i)
                continue
            prev_space = False
            for f in c.casefold():
                out.append(f)
                idx.append(i)
    if out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def _find_all(hay: str, needle: str) -> list[int]:
    hits, i = [], hay.find(needle)
    while i != -1:
        hits.append(i)
        i = hay.find(needle, i + 1)
    return hits


def _occurrences(book: BookText, needle: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """(start, end) offsets in book.text of ``needle`` within text[lo:hi]."""
    lo = max(0, lo)
    hi = min(len(book.text), hi)
    if lo >= hi:
        return []
    norm, idx = normalize(book.text[lo:hi])
    res = []
    for h in _find_all(norm, needle):
        start = lo + idx[h]
        end = lo + idx[h + len(needle) - 1] + 1
        res.append((start, end))
    return res


def okular_to_book_page(book: BookText, okular_page: int, okular_pages: int) -> int:
    """Map Okular's 1-based page number onto BookText's 0-based page index."""
    if book.page_count == 0:
        return 0
    if okular_pages <= 0 or okular_page <= 0:
        return 0
    if book.exact_pages or okular_pages == book.page_count:
        return min(okular_page - 1, book.page_count - 1)
    scaled = round((okular_page - 0.5) * book.page_count / okular_pages - 0.5)
    return min(max(scaled, 0), book.page_count - 1)


def _needles(selection: str) -> list[str]:
    """The full selection first, then shorter pieces in case it spans junk
    (page headers, footnote markers) that our text doesn't have."""
    full, _ = normalize(selection)
    if not full:
        return []
    needles = [full]
    words = full.split(" ")
    if len(words) > 12:
        needles.append(" ".join(words[:8]))
        needles.append(" ".join(words[-8:]))
    return needles


def locate(book: BookText, selection: str, okular_page: int, okular_pages: int) -> Location | None:
    """Find the selection near the reader's page. Returns None if not found."""
    if not book.text or not book.page_starts:
        return None
    p = okular_to_book_page(book, okular_page, okular_pages)
    exact = book.exact_pages or okular_pages == book.page_count
    # The current page and its neighbours are on screen at once in continuous
    # mode, so anything on them has been seen.
    near = (1, 2) if exact else (2, 3)
    wide = 3 if exact else max(6, book.page_count // 40)

    def bounds(a: int, b: int) -> tuple[int, int]:
        a = max(0, a)
        b = min(book.page_count - 1, b)
        return book.page_starts[a], book.page_end(b)

    def distance(hit: tuple[int, int]) -> int:
        # Pages ahead of the reader count double: guessing too early only loses
        # context, guessing too late can spoil.
        d = book.page_of(hit[0]) - p
        return -d if d <= 0 else 2 * d

    for needle in _needles(selection):
        # 1. On (or right next to) the page Okular says is current.
        lo, hi = bounds(p - near[0], p + near[1] - 1)
        hits = _occurrences(book, needle, lo, hi)
        method = "near-page"
        if not hits:
            # 2. A few pages either side, for when our page estimate drifts.
            lo, hi = bounds(p - wide, p + wide)
            hits = _occurrences(book, needle, lo, hi)
            method = "nearby"
        if not hits:
            # 3. Anywhere before the reader's position: the latest such place.
            lo, hi = bounds(0, p + near[1] - 1)
            hits = _occurrences(book, needle, lo, hi)
            if hits:
                hits = [hits[-1]]
            method = "before-page"
        if not hits:
            # 4. Okular's page doesn't fit (stale D-Bus answer, wrong tab...).
            #    Use the earliest place in the book: may lose context, never spoils.
            hits = _occurrences(book, needle, 0, len(book.text))[:1]
            method = "first-occurrence"
        if not hits:
            continue
        # Nearest to the reader's page; on a tie, the earlier one (spoiler-safe).
        start, end = min(hits, key=lambda h: (distance(h), h[0]))
        if needle != _needles(selection)[0]:
            # Matched only part of the selection: extend to cover the rest.
            full_len = len(_needles(selection)[0])
            if needle == _needles(selection)[1]:
                end = min(len(book.text), start + int(full_len * 1.2))
            else:
                start = max(0, end - int(full_len * 1.2))
        page = book.page_of(end - 1)
        cutoff = min(book.page_end(page), end + MAX_AFTER_SELECTION)
        cutoff = max(cutoff, end)
        loc = Location(start, end, cutoff, page, method, occurrences=len(hits))
        if needle != _needles(selection)[0]:
            loc.notes.append("matched part of the selection")
        return loc
    return None


def read_so_far(book: BookText, loc: Location) -> str:
    return book.text[: loc.cutoff]


def context_before(book: BookText, loc: Location, chars: int = CONTEXT_BEFORE) -> str:
    start = max(0, loc.start - chars)
    # Start on a paragraph boundary so the excerpt doesn't open mid-sentence.
    nl = book.text.find("\n", start, loc.start)
    if 0 <= nl < loc.start and start > 0:
        start = nl + 1
    return book.text[start : loc.cutoff]
