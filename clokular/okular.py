"""Ask running Okular windows which document and page they're showing.

Okular exports org.kde.okular on the session bus: each window registers
``org.kde.okular.Instance_<uuid>`` (or ``org.kde.okular`` with --unique), and
each open tab is an object at /okular, /okular2, ... The Flathub sandbox lets
these through because they sit under the app's own ID.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

_SERVICE = re.compile(r"^org\.kde\.okular(\.Instance_[0-9a-fA-F]+|-\d+)?$")
_PART = re.compile(r"^/okular\d*$")


@dataclass(frozen=True)
class OpenDocument:
    service: str
    object_path: str
    path: str
    page: int  # 1-based, as Okular counts
    pages: int


def _busctl(*args: str, timeout: float = 3) -> str:
    r = subprocess.run(["busctl", "--user", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout


def _call(service: str, obj: str, method: str):
    out = json.loads(_busctl("--json=short", "call", service, obj, "org.kde.okular", method))
    return out["data"][0]


def open_documents() -> list[OpenDocument]:
    try:
        names = json.loads(_busctl("--json=short", "list"))
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
        return []
    seen_connections = set()
    docs: list[OpenDocument] = []
    for entry in names:
        name = entry.get("name", "")
        if not _SERVICE.match(name):
            continue
        conn = entry.get("connection") or name
        if conn in seen_connections:
            continue  # one window can own two names
        seen_connections.add(conn)
        try:
            paths = [p for p in _busctl("tree", "--list", name).split() if _PART.match(p)]
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            continue
        for obj in paths:
            try:
                path = _call(name, obj, "currentDocument")
                if not path:
                    continue
                docs.append(OpenDocument(name, obj, path, int(_call(name, obj, "currentPage")), int(_call(name, obj, "pages"))))
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired):
                continue
    return docs
