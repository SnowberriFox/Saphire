"""Where Sapphire keeps its own files (XDG base directories)."""

from __future__ import annotations

import os
from pathlib import Path

from sapphire import APP_ID


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "").strip()
    return Path(value) if value else Path.home() / fallback


def data_dir() -> Path:
    """Library, state and logs. Override with SAPPHIRE_HOME (handy for testing)."""
    override = os.environ.get("SAPPHIRE_HOME")
    path = Path(override) if override else _xdg("XDG_DATA_HOME", ".local/share") / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    override = os.environ.get("SAPPHIRE_HOME")
    path = Path(override) / "cache" if override else _xdg("XDG_CACHE_HOME", ".cache") / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def library_dir() -> Path:
    path = data_dir() / "library"
    path.mkdir(parents=True, exist_ok=True)
    return path


def downloads_dir() -> Path:
    path = cache_dir() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumbs_dir() -> Path:
    path = cache_dir() / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_file() -> Path:
    return data_dir() / "state.json"


def log_file() -> Path:
    return data_dir() / "sapphire.log"
