"""The clokular: link that Okular's "Search for ... with > Claude" menu opens."""

from __future__ import annotations

from urllib.parse import unquote

SCHEME = "clokular"


def selection_from_url(url: str) -> str:
    """'clokular:It%20is%20possible' -> 'It is possible'."""
    if not url.lower().startswith(SCHEME + ":"):
        raise ValueError(f"not a {SCHEME}: link: {url[:40]!r}")
    rest = url[len(SCHEME) + 1 :]
    # Tolerate clokular://... or clokular:///... from other launchers.
    rest = rest.lstrip("/") if rest.startswith("//") else rest
    return unquote(rest).strip()
