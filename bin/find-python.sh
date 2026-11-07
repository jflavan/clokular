# Sourced by install.sh and uninstall.sh: sets PYTHON to a Python 3.10+
# interpreter, preferring one that has PySide6. A Homebrew or pyenv python3
# earlier on PATH often lacks PySide6, so the system one is tried first.
PYTHON=""
for _candidate in /usr/bin/python3 "$(command -v python3 2>/dev/null || true)" /usr/local/bin/python3; do
    [ -n "$_candidate" ] && [ -x "$_candidate" ] || continue
    if "$_candidate" -c 'import sys, PySide6.QtWidgets, PySide6.QtXml; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
        PYTHON="$_candidate"
        break
    fi
done
if [ -z "$PYTHON" ]; then
    # None has PySide6: use any python3 and let `clokular check` explain what's missing.
    PYTHON="$(command -v python3 2>/dev/null || true)"
fi
if [ -z "$PYTHON" ]; then
    echo "clokular needs Python 3.10 or newer, but no python3 was found." >&2
    exit 1
fi
unset _candidate
