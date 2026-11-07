#!/usr/bin/env bash
# Remove clokular's Okular menu entry, link handler and icon.
#
#   ./uninstall.sh           remove the integration (keeps cache and settings)
#   ./uninstall.sh --purge   also delete ~/.cache/clokular and ~/.config/clokular
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=bin/find-python.sh
. "$REPO/bin/find-python.sh"

"$PYTHON" "$REPO/bin/clokular" uninstall

if [ "${1:-}" = "--purge" ]; then
    rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/clokular" "${XDG_CONFIG_HOME:-$HOME/.config}/clokular"
    echo "deleted clokular's cache (book text, past sessions, log) and settings"
else
    echo "kept ${XDG_CACHE_HOME:-$HOME/.cache}/clokular and ${XDG_CONFIG_HOME:-$HOME/.config}/clokular (use --purge to delete)"
fi
echo "Restart Okular to drop the menu entry."
