"""Hook clokular into Okular's right-click menu, and undo it.

Okular's text-selection menu has "Search for '...' with" listing the user's
*preferred* web shortcuts (KIO's kuriikwsfilter). We add a shortcut named
"Claude" whose URL is clokular:<text>, and register this program as the
handler for clokular: links. In the Flathub build, Okular reads its KIO config
from ~/.var/app/org.kde.okular/{config,data}, and opening the link goes
through the desktop portal to the handler on the host.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .urls import SCHEME

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "bin" / "clokular"
HOME = Path.home()
DATA = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local" / "share"))
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
DESKTOP_FILE = DATA / "applications" / "clokular.desktop"
STATE_FILE = DATA / "clokular" / "install.json"
PROVIDER_NAME = "claude"  # desktop-entry name of the web shortcut
ICON_NAME = "clokular-claude"
ICON_SRC = REPO / "icons" / f"{ICON_NAME}.svg"


def icon_path(data_dir: Path) -> Path:
    """Where an icon theme lookup will find our icon (hicolor is every theme's fallback)."""
    return data_dir / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON_NAME}.svg"
# KIO's built-in preferred list, used when the user has never changed it.
KIO_DEFAULT_PREFERRED = ["google", "youtube", "yahoo", "wikipedia", "wikit"]

PROVIDER = f"""[Desktop Entry]
Charset=
Hidden=false
Icon={ICON_NAME}
Keys=claude
Name=Claude
Query={SCHEME}:\\\\{{@}}
Type=Service
"""

def exec_arg(arg: str) -> str:
    """Quote one argument for a .desktop Exec= line (Desktop Entry spec):
    inside double quotes escape " ` $ \\ with a backslash, double % for
    field codes, then apply the string-value rule that doubles backslashes."""
    quoted = "".join("\\" + c if c in '"`$\\' else c for c in arg).replace("%", "%%")
    return '"' + quoted.replace("\\", "\\\\") + '"'


def handler_entry(python: str) -> str:
    """The .desktop file that handles clokular: links. It names the Python
    interpreter explicitly, so a different python3 earlier on PATH (Homebrew,
    pyenv...) without PySide6 can't break it."""
    return f"""[Desktop Entry]
Type=Application
Name=Claude for Okular
Comment=Explain highlighted text without spoilers
Exec={exec_arg(python)} {exec_arg(str(LAUNCHER))} %u
Icon={ICON_NAME}
Terminal=false
NoDisplay=true
MimeType=x-scheme-handler/{SCHEME};
"""


def okular_targets() -> list[tuple[str, Path, Path]]:
    """(label, config dir, data dir) for each Okular install found."""
    targets = []
    fp = HOME / ".var" / "app" / "org.kde.okular"
    has_flatpak = fp.exists()
    if not has_flatpak and shutil.which("flatpak"):
        has_flatpak = subprocess.run(["flatpak", "info", "org.kde.okular"], capture_output=True).returncode == 0
    if has_flatpak:
        targets.append(("Okular (Flatpak)", fp / "config", fp / "data"))
    if shutil.which("okular"):
        targets.append(("Okular (system)", CONFIG, DATA))
    return targets


# ---- tiny KConfig (INI) editing -------------------------------------------

def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _get(lines: list[str], group: str, key: str) -> str | None:
    cur = None
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
        elif cur == group and "=" in s and s.split("=", 1)[0].strip() == key:
            return s.split("=", 1)[1]
    return None


def _set(lines: list[str], group: str, key: str, value: str | None) -> list[str]:
    """Set (or with value=None, remove) key in [group]."""
    out, cur, done, group_seen = [], None, False, False
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if cur == group and not done and value is not None:
                out.append(f"{key}={value}")
                done = True
            cur = s[1:-1]
            group_seen = group_seen or cur == group
        elif cur == group and "=" in s and s.split("=", 1)[0].strip() == key:
            if value is not None and not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(line)
    if value is not None and not done:
        if cur == group:
            out.append(f"{key}={value}")
        else:
            if out and out[-1].strip():
                out.append("")
            out += [f"[{group}]", f"{key}={value}"]
    return out


def _split_list(v: str) -> list[str]:
    return [x for x in (p.strip() for p in v.split(",")) if x]


# ---- install / uninstall ----------------------------------------------------

def _state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def _install_icon(data_dir: Path) -> None:
    dest = icon_path(data_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ICON_SRC, dest)
    # Bump the theme dir's mtime so icon caches notice the new file.
    os.utime(data_dir / "icons" / "hicolor", None)


def _update_desktop_database() -> None:
    # Optional (desktop-file-utils): refreshes the MIME cache for our handler.
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(DESKTOP_FILE.parent)], capture_output=True)


def install() -> int:
    import sys

    # Always check first: the handler will run this exact interpreter, so it
    # must have PySide6, and Claude Code must be usable.
    if check() != 0:
        return 1
    print()
    if not LAUNCHER.exists():
        print(f"missing launcher: {LAUNCHER}")
        return 1
    LAUNCHER.chmod(0o755)
    targets = okular_targets()
    _install_icon(DATA)
    DESKTOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_FILE.write_text(handler_entry(sys.executable), encoding="utf-8")
    _update_desktop_database()
    # xdg-mime prints a harmless "qtpaths: command not found" on some KDE setups.
    subprocess.run(["xdg-mime", "default", DESKTOP_FILE.name, f"x-scheme-handler/{SCHEME}"], capture_output=True)
    registered = subprocess.run(["xdg-mime", "query", "default", f"x-scheme-handler/{SCHEME}"],
                                capture_output=True, text=True).stdout.strip()
    handler_ok = registered == DESKTOP_FILE.name
    if handler_ok:
        print(f"registered {SCHEME}: links -> {LAUNCHER} (using {sys.executable})")
    else:
        print(f"ERROR: couldn't make {DESKTOP_FILE.name} the handler for {SCHEME}: links "
              f"(xdg-mime reports {registered or 'nothing'!r}). Clicking Claude in Okular won't do anything.\n"
              f"  try: xdg-mime default {DESKTOP_FILE.name} x-scheme-handler/{SCHEME}")
    state = _state()
    for label, cfg_dir, data_dir in targets:
        prov = data_dir / "kf6" / "searchproviders" / f"{PROVIDER_NAME}.desktop"
        prov.parent.mkdir(parents=True, exist_ok=True)
        prov.write_text(PROVIDER, encoding="utf-8")
        _install_icon(data_dir)
        rc = cfg_dir / "kuriikwsfilterrc"
        lines = _read_lines(rc)
        current = _get(lines, "General", "PreferredWebShortcuts")
        key = str(rc)
        if key not in state:
            state[key] = {"had_key": current is not None}
        prefs = _split_list(current) if current is not None else list(KIO_DEFAULT_PREFERRED)
        if PROVIDER_NAME not in prefs:
            prefs.insert(0, PROVIDER_NAME)
        lines = _set(lines, "General", "PreferredWebShortcuts", ",".join(prefs))
        if _get(lines, "General", "EnableWebShortcuts") == "false":
            lines = _set(lines, "General", "EnableWebShortcuts", "true")
        rc.parent.mkdir(parents=True, exist_ok=True)
        rc.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{label}: added 'Claude' to the right-click search menu")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    if not handler_ok:
        return 1
    print("Restart Okular to pick up the new menu entry.")
    return 0


def uninstall() -> int:
    state = _state()
    for label, cfg_dir, data_dir in okular_targets():
        prov = data_dir / "kf6" / "searchproviders" / f"{PROVIDER_NAME}.desktop"
        prov.unlink(missing_ok=True)
        icon_path(data_dir).unlink(missing_ok=True)
        rc = cfg_dir / "kuriikwsfilterrc"
        lines = _read_lines(rc)
        current = _get(lines, "General", "PreferredWebShortcuts")
        if current is not None:
            prefs = [p for p in _split_list(current) if p != PROVIDER_NAME]
            had_key = state.get(str(rc), {}).get("had_key", True)
            if not had_key and prefs == KIO_DEFAULT_PREFERRED:
                lines = _set(lines, "General", "PreferredWebShortcuts", None)
            else:
                lines = _set(lines, "General", "PreferredWebShortcuts", ",".join(prefs))
            body = [l for l in lines if l.strip()]
            if body == ["[General]"]:
                rc.unlink(missing_ok=True)
            else:
                rc.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{label}: removed 'Claude' from the menu")
    DESKTOP_FILE.unlink(missing_ok=True)
    icon_path(DATA).unlink(missing_ok=True)
    _update_desktop_database()
    STATE_FILE.unlink(missing_ok=True)
    print(f"unregistered {SCHEME}: links")
    return 0


def status() -> int:
    handler = subprocess.run(["xdg-mime", "query", "default", f"x-scheme-handler/{SCHEME}"],
                             capture_output=True, text=True).stdout.strip()
    print(f"{SCHEME}: handler: {handler or '(none)'}")
    for label, cfg_dir, data_dir in okular_targets():
        prov = data_dir / "kf6" / "searchproviders" / f"{PROVIDER_NAME}.desktop"
        prefs = _get(_read_lines(cfg_dir / "kuriikwsfilterrc"), "General", "PreferredWebShortcuts")
        print(f"{label}: provider {'present' if prov.exists() else 'missing'}; preferred = {prefs}")
    from . import okular
    from .claude import find_claude

    print(f"claude CLI: {find_claude() or 'not found'}")
    for d in okular.open_documents():
        print(f"open in Okular: {d.path} (page {d.page} of {d.pages})")
    return 0


# ---- pre-install checks -----------------------------------------------------

def check() -> int:
    """Check everything clokular needs. Returns 0 if it can be installed."""
    import importlib.util
    import sys

    from .claude import find_claude

    problems: list[str] = []
    warnings: list[str] = []

    def ok(msg: str) -> None:
        print(f"  ok    {msg}")

    def bad(msg: str, fix: str) -> None:
        print(f"  MISSING  {msg}")
        problems.append(f"{msg}\n      fix: {fix}")

    def warn(msg: str, note: str) -> None:
        print(f"  note  {msg}")
        warnings.append(f"{msg}\n      {note}")

    print("Checking requirements:")
    if sys.version_info >= (3, 10):
        ok(f"Python {sys.version.split()[0]}")
    else:
        bad(f"Python 3.10+ (found {sys.version.split()[0]})", "install a newer python3")

    if importlib.util.find_spec("PySide6") and importlib.util.find_spec("PySide6.QtXml"):
        ok("PySide6 (Qt for Python)")
    else:
        bad(f"PySide6 (Qt for Python) for {sys.executable}",
            "Fedora: sudo dnf install python3-pyside6   |   Aurora/atomic: pip install --user PySide6"
            "   (if another Python already has it, use ./install.sh, which finds that one)")

    for tool, why, fix in (
        ("pdftotext", "reads PDF text", "Fedora: sudo dnf install poppler-utils"),
        ("busctl", "asks Okular which page you're on", "part of systemd; should already be installed"),
        ("xdg-mime", "registers the clokular: link handler", "Fedora: sudo dnf install xdg-utils"),
    ):
        if shutil.which(tool):
            ok(f"{tool} ({why})")
        else:
            bad(f"{tool} ({why})", fix)

    targets = okular_targets()
    if targets:
        ok("Okular: " + ", ".join(t[0] for t in targets))
    else:
        bad("Okular", "flatpak install flathub org.kde.okular")

    claude = find_claude()
    if not claude:
        bad("Claude Code (the `claude` command)",
            "curl -fsSL https://claude.ai/install.sh | bash   then run `claude` once to sign in")
    else:
        ok(f"Claude Code at {claude}")
        try:
            r = subprocess.run([claude, "auth", "status", "--json"], capture_output=True, text=True, timeout=30)
            auth = json.loads(r.stdout) if r.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            auth = None
        if not isinstance(auth, dict) or "loggedIn" not in auth:
            auth = None  # older CLI, or output we don't understand: don't block install
        if auth is None:
            warn("couldn't read Claude Code's sign-in status", "make sure `claude` works in a terminal")
        elif not auth.get("loggedIn"):
            bad("Claude Code sign-in", "run `claude auth login` (or just `claude`) and sign in with your Claude account")
        elif auth.get("authMethod") not in ("claude.ai", None):
            warn(f"Claude Code is signed in with {auth.get('authMethod')}",
                 "clokular will use that (e.g. API billing), not a Claude subscription. "
                 "Run `claude auth login` to switch to your Claude account.")
        else:
            ok("Claude Code is signed in with your Claude account")

    if problems:
        print("\nclokular can't be installed yet:")
        for p in problems:
            print(f"  - {p}")
    for w in warnings:
        print(f"\nNote: {w}")
    return 1 if problems else 0
