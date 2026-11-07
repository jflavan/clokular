"""Append-only log at ~/.cache/clokular/clokular.log (for troubleshooting)."""

from __future__ import annotations

import os
import time
from pathlib import Path

MAX_BYTES = 512 * 1024


def path() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "clokular" / "clokular.log"


def write(msg: str) -> None:
    p = path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > MAX_BYTES:
            p.replace(p.with_suffix(".log.old"))
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{os.getpid()}] {msg}\n")
    except OSError:
        pass
