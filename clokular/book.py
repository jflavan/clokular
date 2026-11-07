"""Load a document's text, cached on disk.

EPUB layout needs Qt, so it runs in a child process on the offscreen platform
(``python -m clokular index FILE OUT``). That keeps page layout independent of
the screen, and keeps a broken EPUB from taking the answer window down.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from . import config
from .locate import BookText

CACHE_VERSION = 1


def cache_dir() -> Path:
    d = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "clokular" / "books"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _key(path: str, cfg: dict) -> str:
    st = os.stat(path)
    ident = json.dumps([CACHE_VERSION, os.path.realpath(path), st.st_size, st.st_mtime_ns, cfg["epub_font"], cfg["epub_font_size"]])
    return hashlib.sha256(ident.encode()).hexdigest()[:24]


def kind(path: str) -> str | None:
    p = path.lower()
    if p.endswith(".epub"):
        return "epub"
    if p.endswith(".pdf"):
        return "pdf"
    return None


def to_json(book: BookText) -> dict:
    return {
        "text": book.text,
        "page_starts": book.page_starts,
        "exact_pages": book.exact_pages,
        "title": book.title,
        "author": book.author,
    }


def from_json(d: dict) -> BookText:
    return BookText(d["text"], d["page_starts"], d["exact_pages"], d.get("title", ""), d.get("author", ""))


def index_to_file(path: str, out: str) -> None:
    """Run inside the child process."""
    cfg = config.load()
    k = kind(path)
    if k == "pdf":
        from . import pdf

        book = pdf.extract(path)
    elif k == "epub":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtGui import QFont, QGuiApplication

        _app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
        from . import epub

        font = QFont(cfg["epub_font"])
        font.setPointSize(int(cfg["epub_font_size"]))
        book = epub.extract(path, font)
    else:
        raise ValueError(f"unsupported file type: {path}")
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(to_json(book), f)
    os.replace(tmp, out)


def load(path: str) -> BookText:
    """Load from cache, or index in a child process (a few seconds the first time)."""
    if kind(path) is None:
        raise ValueError(f"clokular only understands EPUB and PDF files, not {Path(path).name}")
    cfg = config.load()
    cached = cache_dir() / f"{_key(path, cfg)}.json"
    if not cached.exists():
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        r = subprocess.run(
            [sys.executable, "-m", "clokular", "index", path, str(cached)],
            capture_output=True, text=True, env=env, timeout=600,
        )
        if r.returncode != 0 or not cached.exists():
            tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
            raise RuntimeError("Couldn't read the book's text: " + " | ".join(tail))
    with open(cached, encoding="utf-8") as f:
        return from_json(json.load(f))
