#!/usr/bin/env bash
# Sapphire installer for Ubuntu, Bazzite and other Linux desktops.
#
# Installs into your home folder only (no sudo, works on immutable distros):
#   ~/.local/share/sapphire/venv   private Python + Qt (managed by uv)
#   ~/.local/share/sapphire/bin    bundled 7-Zip (handles .rar/.7z mods)
#   ~/.local/bin/sapphire          launcher
#   app menu entry + icon
#
# Re-run it any time to update. Your mods and settings are kept.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/sapphire"
BIN="$HOME/.local/bin"
SEVENZIP_VERSION="2501"   # 7-Zip 25.01

say()  { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; }

fetch() {  # fetch URL OUTFILE  (curl, wget or python - whichever exists)
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$2" "$1"
    else
        python3 -c 'import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$1" "$2"
    fi
}

mkdir -p "$PREFIX/bin" "$BIN"

# --- 1. uv (gives us our own Python, so system packages don't matter) ---------
UV="$(command -v uv || true)"
[ -z "$UV" ] && [ -x "$BIN/uv" ] && UV="$BIN/uv"
[ -z "$UV" ] && [ -x "$HOME/.cargo/bin/uv" ] && UV="$HOME/.cargo/bin/uv"
if [ -z "$UV" ]; then
    say "Installing uv (Python manager) into $BIN"
    tmp="$(mktemp)"
    fetch https://astral.sh/uv/install.sh "$tmp"
    env UV_INSTALL_DIR="$BIN" UV_NO_MODIFY_PATH=1 sh "$tmp" >/dev/null
    rm -f "$tmp"
    UV="$BIN/uv"
fi
say "Using uv: $("$UV" --version)"

# --- 2. Python environment ----------------------------------------------------
say "Setting up Python 3.12 + Qt (first run downloads ~150 MB)"
rm -rf "$PREFIX/venv"
"$UV" venv --quiet --python 3.12 --python-preference only-managed "$PREFIX/venv"
"$UV" pip install --quiet --python "$PREFIX/venv/bin/python" "$SRC"

# --- 3. 7-Zip (official static build, for .rar and .7z mods) -------------------
case "$(uname -m)" in
    x86_64)  SZ_ARCH="x64" ;;
    aarch64) SZ_ARCH="arm64" ;;
    *)       SZ_ARCH="" ;;
esac
if [ -n "$SZ_ARCH" ]; then
    say "Fetching 7-Zip"
    tmpd="$(mktemp -d)"
    if fetch "https://github.com/ip7z/7zip/releases/download/${SEVENZIP_VERSION:0:2}.${SEVENZIP_VERSION:2}/7z${SEVENZIP_VERSION}-linux-${SZ_ARCH}.tar.xz" "$tmpd/7z.tar.xz" \
        && tar -xJf "$tmpd/7z.tar.xz" -C "$tmpd" 7zz \
        && "$tmpd/7zz" i >/dev/null 2>&1; then
        install -m 755 "$tmpd/7zz" "$PREFIX/bin/7zz"
    else
        warn "Couldn't fetch 7-Zip. .zip mods still work; for .rar mods install 7zip or unrar."
    fi
    rm -rf "$tmpd"
fi

# --- 4. Launcher, menu entry, icon --------------------------------------------
cat > "$BIN/sapphire" <<EOF
#!/bin/sh
# Prefer native Wayland, fall back to X11.
if [ -n "\${WAYLAND_DISPLAY:-}" ] && [ -z "\${QT_QPA_PLATFORM:-}" ]; then
    export QT_QPA_PLATFORM="wayland;xcb"
fi
exec "$PREFIX/venv/bin/python" -m sapphire "\$@"
EOF
chmod 755 "$BIN/sapphire"

ICON_DIR="$DATA/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR" "$DATA/applications"
cp "$SRC/sapphire/assets/sapphire.svg" "$ICON_DIR/sapphire.svg"
sed "s|@EXEC@|$BIN/sapphire|" "$SRC/packaging/sapphire.desktop" > "$DATA/applications/sapphire.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DATA/applications" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATA/icons/hicolor" 2>/dev/null || true

# --- 5. Sanity check ----------------------------------------------------------
if QT_QPA_PLATFORM=offscreen "$PREFIX/venv/bin/python" -c "import sapphire.ui.app" 2>/dev/null; then
    say "Sapphire installed. Open it from your app menu, or run: sapphire"
else
    warn "Installed, but the app failed to import. Run '$PREFIX/venv/bin/python -m sapphire' to see why."
    exit 1
fi
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) warn "$BIN isn't on your PATH, so use the app menu (or add it to PATH)." ;;
esac
