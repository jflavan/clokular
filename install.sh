#!/usr/bin/env bash
# Install clokular: adds "Claude" to Okular's right-click menu.
#
#   ./install.sh            check requirements, then install
#   ./install.sh --check    only check requirements
#
# Safe to re-run (e.g. after moving this folder or updating Okular).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/find-python.sh
. "$REPO/bin/find-python.sh"

if [ "${1:-}" = "--check" ]; then
    exec "$PYTHON" "$REPO/bin/clokular" check
fi

# `clokular install` runs the requirement check itself before changing anything.
"$PYTHON" "$REPO/bin/clokular" install || exit 1

echo
# grep without -q reads all of busctl's output, so pipefail can't trip on SIGPIPE.
if busctl --user list 2>/dev/null | grep 'org\.kde\.okular' >/dev/null; then
    echo "Okular is running: quit it completely and open it again to see the new menu entry."
else
    echo "Open Okular to try it."
fi
cat <<'EOF'

How to use it:
  1. Select some text in a book (EPUB or PDF).
  2. Right-click the selection > "Search for '...' with" > Claude.
  3. A window explains the passage, using only what you've read so far.
EOF
