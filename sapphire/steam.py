"""Finding Deadlock across every way Steam gets installed on Linux.

Covers native Steam (Bazzite, Ubuntu .deb), Flatpak Steam and Snap Steam,
plus every extra library folder listed in libraryfolders.vdf.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

DEADLOCK_APP_ID = 1422450
STEAM_RUN_URL = f"steam://rungameid/{DEADLOCK_APP_ID}"

# Relative to $HOME. Order matters only for display; duplicates are removed.
STEAM_ROOT_CANDIDATES = (
    ".local/share/Steam",                                   # native (Bazzite, Ubuntu .deb)
    ".steam/steam",                                         # native symlink
    ".steam/root",                                          # native symlink
    ".steam/debian-installation",                           # older Debian/Ubuntu package
    ".var/app/com.valvesoftware.Steam/.local/share/Steam",  # Flatpak
    ".var/app/com.valvesoftware.Steam/data/Steam",          # older Flatpak layout
    "snap/steam/common/.local/share/Steam",                 # Snap (Ubuntu)
)


# --------------------------------------------------------------------------- VDF

class VdfError(ValueError):
    pass


def _tokenize(text: str) -> Iterable[str]:
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "/" and text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
        elif c in "{}":
            yield c
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, nxt))
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1
            yield '"' + "".join(buf)
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in '{}"':
                j += 1
            yield '"' + text[i:j]
            i = j


def parse_vdf(text: str) -> dict:
    """Parse Valve KeyValues text (libraryfolders.vdf, appmanifest .acf)."""
    tokens = list(_tokenize(text))
    pos = 0

    def parse_obj(top: bool) -> dict:
        nonlocal pos
        out: dict = {}
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "}":
                if top:
                    raise VdfError("unexpected }")
                pos += 1
                return out
            if tok == "{":
                raise VdfError("unexpected {")
            key = tok[1:]
            pos += 1
            if pos >= len(tokens):
                raise VdfError("key without value")
            nxt = tokens[pos]
            if nxt == "{":
                pos += 1
                out[key] = parse_obj(False)
            elif nxt == "}":
                raise VdfError("key without value")
            else:
                out[key] = nxt[1:]
                pos += 1
        if not top:
            raise VdfError("unterminated block")
        return out

    return parse_obj(True)


def _ci_get(d: dict, key: str, default=None):
    for k, v in d.items():
        if k.lower() == key.lower():
            return v
    return default


# ---------------------------------------------------------------------- detection

def steam_roots(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    seen: set[Path] = set()
    roots: list[Path] = []
    for rel in STEAM_ROOT_CANDIDATES:
        p = home / rel
        try:
            if not (p / "steamapps").is_dir():
                continue
            real = p.resolve()
        except OSError:
            continue
        if real not in seen:
            seen.add(real)
            roots.append(real)
    return roots


def library_folders(root: Path) -> list[Path]:
    libs = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
    except (OSError, VdfError) as exc:
        log.debug("could not read %s: %s", vdf, exc)
        return libs
    folders = _ci_get(data, "libraryfolders", {}) or {}
    for entry in folders.values():
        if isinstance(entry, dict):
            path = _ci_get(entry, "path")
        else:  # very old format: "1" "/path"
            path = entry
        if path:
            p = Path(path)
            if p not in libs:
                libs.append(p)
    return libs


def is_valid_game_dir(path: Path | str | None) -> bool:
    if not path:
        return False
    return (Path(path) / "game" / "citadel" / "gameinfo.gi").is_file()


def find_deadlock(home: Path | None = None) -> Path | None:
    """Return Deadlock's install folder (the one containing game/), or None."""
    for root in steam_roots(home):
        for lib in library_folders(root):
            steamapps = lib / "steamapps"
            installdir = "Deadlock"
            manifest = steamapps / f"appmanifest_{DEADLOCK_APP_ID}.acf"
            try:
                if manifest.is_file():
                    data = parse_vdf(manifest.read_text(encoding="utf-8", errors="replace"))
                    state = _ci_get(data, "AppState", {}) or {}
                    installdir = _ci_get(state, "installdir", installdir) or installdir
            except (OSError, VdfError) as exc:
                log.debug("bad manifest %s: %s", manifest, exc)
            candidate = steamapps / "common" / installdir
            if is_valid_game_dir(candidate):
                log.info("found Deadlock at %s", candidate)
                return candidate
    return None


# ------------------------------------------------------------------ game process

REGISTRY_CANDIDATES = (".steam/registry.vdf", "snap/steam/common/.steam/registry.vdf",
                       ".var/app/com.valvesoftware.Steam/.steam/registry.vdf")


def steam_running_app(home: Path | None = None) -> str | None:
    """The app id Steam says is running (registry.vdf's RunningAppID), if any."""
    home = home or Path.home()
    for rel in REGISTRY_CANDIDATES:
        try:
            data = parse_vdf((home / rel).read_text(encoding="utf-8", errors="replace"))
        except (OSError, VdfError):
            continue
        node = data
        for key in ("registry", "hkcu", "software", "valve", "steam"):
            node = next((v for k, v in node.items() if k.lower() == key and isinstance(v, dict)), None) \
                if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, dict):
            val = next((v for k, v in node.items() if k.lower() == "runningappid"), None)
            if isinstance(val, str) and val.strip() not in ("", "0"):
                return val.strip()
    return None


def is_game_running(proc: Path = Path("/proc")) -> bool:
    """True if Deadlock (deadlock.exe under Proton) is running."""
    if os.environ.get("FLATPAK_ID"):
        # A Flatpak can't see the host's processes; ask Steam instead.
        return steam_running_app() == str(DEADLOCK_APP_ID)
    try:
        entries = list(proc.iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            cmd = (entry / "cmdline").read_bytes().lower()
        except OSError:
            continue
        if b"deadlock.exe" in cmd or b"project8.exe" in cmd:
            return True
    return False


def launch_game() -> None:
    """Ask Steam to launch Deadlock (works for native, Flatpak and Snap Steam)."""
    attempts = []
    if shutil.which("xdg-open"):
        attempts.append(["xdg-open", STEAM_RUN_URL])
    if shutil.which("steam"):
        attempts.append(["steam", STEAM_RUN_URL])
    if shutil.which("flatpak"):
        attempts.append(["flatpak", "run", "com.valvesoftware.Steam", STEAM_RUN_URL])
    for cmd in attempts:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True, env=_clean_env())
            return
        except OSError as exc:
            log.warning("launch via %s failed: %s", cmd[0], exc)
    raise RuntimeError("Couldn't find a way to start Steam (no xdg-open, steam or flatpak).")


def _clean_env() -> dict:
    """Strip our bundled Qt/Python vars so child processes use the system ones."""
    env = dict(os.environ)
    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONHOME", "PYTHONPATH",
                "LD_LIBRARY_PATH"):
        env.pop(key, None)
    return env


def open_path(path: Path | str) -> None:
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, env=_clean_env())
