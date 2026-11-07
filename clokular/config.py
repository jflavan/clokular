"""User settings in ~/.config/clokular/config.json (all optional)."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    # Model alias passed to `claude --model`.
    "model": "sonnet",
    # Path to the claude CLI; empty means look it up on PATH.
    "claude_path": "",
    # Okular's EPUB backend lays text out in its default font. Inside the
    # Flathub sandbox that is a 9pt sans; these settings reproduce its pages.
    "epub_font": "Sans Serif",
    "epub_font_size": 9,
}


def path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "clokular" / "config.json"


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(path(), encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            cfg.update({k: v for k, v in user.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return cfg
