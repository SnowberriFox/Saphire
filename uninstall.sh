#!/usr/bin/env bash
# Removes Sapphire. Your mod library and settings are kept unless you pass --purge.
# Mods already in the game keep working until you remove them; to clean the game
# folder first, use Settings > "Turn everything off and restore the game".
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/sapphire"

rm -rf "$PREFIX/venv" "$PREFIX/bin"
rm -f "$HOME/.local/bin/sapphire" "$DATA/applications/sapphire.desktop" \
      "$DATA/icons/hicolor/scalable/apps/sapphire.svg"

if [ "${1:-}" = "--purge" ]; then
    rm -rf "$PREFIX" "${XDG_CACHE_HOME:-$HOME/.cache}/sapphire"
    echo "Sapphire and all its data removed."
else
    echo "Sapphire removed. Your mod library is still in $PREFIX (use --purge to delete it)."
fi
