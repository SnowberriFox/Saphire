"""Background helper: keeps gameinfo.gi patched while Sapphire's window is closed.

A Deadlock update replaces gameinfo.gi, which drops the line that loads mods.
Sapphire puts it back whenever it's open, but launching straight from Steam
after an update would run unmodded. The helper is a tiny headless loop
(no Qt) started at login through an XDG autostart entry. Every few seconds it
looks at gameinfo.gi's timestamp; if the file changed and the mod folders
Sapphire deployed are missing from it, it adds them back. It never touches mods,
and it stays quiet while the Sapphire window is open (the window does the job
itself then). Turning it off in Settings removes the autostart entry and the
running helper exits on its next check.
"""

from __future__ import annotations

import fcntl
import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from sapphire import gameinfo, paths, steam

log = logging.getLogger("sapphire.helper")

POLL = 5.0            # seconds between gameinfo.gi timestamp checks
SETTINGS_EVERY = 30   # re-read state.json (helper switched off? game folder moved?) this often
AUTOSTART_NAME = "sapphire-helper.desktop"


# ---------------------------------------------------------------------- locks

def _lock(path: Path):
    """Hold an exclusive lock on `path` for this process's lifetime; None if taken."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def gui_lock_path() -> Path:
    return paths.data_dir() / "gui.lock"


def helper_lock_path() -> Path:
    return paths.data_dir() / "helper.lock"


def hold_gui_lock():
    """Called by the window at start: tells the helper the window is in charge."""
    return _lock(gui_lock_path())


def gui_running() -> bool:
    fh = _lock(gui_lock_path())
    if fh is None:
        return True
    fh.close()
    return False


def helper_running() -> bool:
    fh = _lock(helper_lock_path())
    if fh is None:
        return True
    fh.close()
    return False


# ---------------------------------------------------------------------- the check

def deployed_folders(state: dict) -> list[str]:
    """The addons folders Sapphire last deployed to, as gameinfo.gi paths."""
    deployed = state.get("deployed") or {}
    folders = sorted({k.split("/", 1)[0] for k in deployed if "/" in k},
                     key=lambda f: (len(f), f))     # addons, addons2, addons3 ...
    return [f"citadel/{f}" for f in folders]


def _read_state() -> dict:
    import json
    try:
        return json.loads(paths.state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check_once(state: dict) -> bool:
    """Re-add the mod folders to gameinfo.gi if they're missing. True if it fixed it."""
    game_dir = state.get("game_dir")
    if not game_dir or not steam.is_valid_game_dir(game_dir):
        return False
    folders = deployed_folders(state)
    if not folders:
        return False
    try:
        text = gameinfo.read(Path(game_dir))
    except gameinfo.GameInfoError as exc:
        log.warning("can't read gameinfo.gi: %s", exc)
        return False
    if not gameinfo.needs_patch(text, folders):
        return False
    gameinfo.apply(Path(game_dir), folders, paths.data_dir() / "backups")
    log.info("gameinfo.gi was reset (game update?); mod folders added back: %s", ", ".join(folders))
    return True


def run(stop_after: float | None = None) -> int:
    """The helper loop. `stop_after` (seconds) is for tests."""
    _setup_logging()
    lock = _lock(helper_lock_path())
    if lock is None:
        log.info("helper already running")
        return 0
    stopping = False

    def _stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("helper started (pid %d)", os.getpid())
    started = time.monotonic()
    state, state_at, last_mtime = {}, 0.0, None
    while not stopping:
        now = time.monotonic()
        if stop_after is not None and now - started > stop_after:
            break
        if now - state_at > SETTINGS_EVERY or not state:
            state, state_at = _read_state(), now
            if not (state.get("settings") or {}).get("helper", False):
                log.info("helper switched off in Settings; exiting")
                break
        game_dir = state.get("game_dir")
        gi = Path(game_dir) / "game" / "citadel" / "gameinfo.gi" if game_dir else None
        try:
            mtime = gi.stat().st_mtime_ns if gi else None
        except OSError:
            mtime = None
        if mtime is not None and mtime != last_mtime:
            if not gui_running():
                try:
                    check_once(_read_state())
                except Exception:  # noqa: BLE001 - keep running whatever happens
                    log.exception("helper check failed")
            last_mtime = mtime
        time.sleep(0.2 if stop_after is not None else POLL)
    lock.close()
    return 0


def _setup_logging():
    if logging.getLogger().handlers:
        return
    try:
        paths.data_dir().mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=paths.data_dir() / "helper.log", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
    except OSError:
        logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------- autostart

def autostart_file() -> Path:
    # Inside a Flatpak, XDG_CONFIG_HOME is the app's private folder, which the
    # desktop never reads; the entry has to go in the real ~/.config/autostart.
    if os.environ.get("FLATPAK_ID"):
        base = Path.home() / ".config"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / AUTOSTART_NAME


def command() -> list[str]:
    """How to start the helper from outside this process."""
    flatpak = os.environ.get("FLATPAK_ID")
    if flatpak:
        return ["flatpak", "run", f"--command=sapphire", flatpak, "--helper"]
    launcher = Path.home() / ".local" / "bin" / "sapphire"
    if launcher.is_file() and os.access(launcher, os.X_OK):
        return [str(launcher), "--helper"]
    return [sys.executable, "-m", "sapphire", "--helper"]


def enable(start_now: bool = True) -> Path:
    f = autostart_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Sapphire helper",
        "Comment=Keeps Deadlock mods loading after game updates",
        f"Exec={shlex.join(command())}",
        "Icon=sapphire",
        "Terminal=false",
        "NoDisplay=true",
        "X-GNOME-Autostart-enabled=true",
        "",
    ]))
    if start_now and not helper_running():
        start()
    return f


def disable() -> None:
    autostart_file().unlink(missing_ok=True)


def is_enabled() -> bool:
    return autostart_file().is_file()


def start() -> None:
    try:
        subprocess.Popen(command(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    except OSError as exc:
        log.warning("couldn't start the helper: %s", exc)


if __name__ == "__main__":
    sys.exit(run())
