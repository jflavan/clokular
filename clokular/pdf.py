"""PDF text extraction with exact page boundaries, via poppler's pdftotext."""

from __future__ import annotations

import subprocess

from .locate import BookText


def split_pages(raw: str) -> tuple[str, list[int]]:
    """pdftotext separates pages with form feeds; turn that into page_starts."""
    pages = raw.split("\f")
    if pages and pages[-1].strip() == "":
        pages.pop()  # pdftotext ends with a trailing form feed
    starts, parts, pos = [], [], 0
    for page in pages:
        starts.append(pos)
        chunk = page if page.endswith("\n") else page + "\n"
        parts.append(chunk)
        pos += len(chunk)
    return "".join(parts), starts or [0]


def _info(path: str) -> dict[str, str]:
    try:
        out = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    info = {}
    for line in out.splitlines():
        k, _, v = line.partition(":")
        info[k.strip()] = v.strip()
    return info


def extract(path: str) -> BookText:
    raw = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", path, "-"], capture_output=True, text=True, check=True, timeout=300
    ).stdout
    text, starts = split_pages(raw)
    info = _info(path)
    return BookText(text=text, page_starts=starts, exact_pages=True, title=info.get("Title", ""), author=info.get("Author", ""))
