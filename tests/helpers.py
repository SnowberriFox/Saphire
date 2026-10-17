"""Test helpers: build real VPK files and fake game installs."""

from __future__ import annotations

import struct
from pathlib import Path

VANILLA = Path(__file__).with_name("vanilla_gameinfo.gi")


def make_vpk(path: Path, files: dict[str, bytes], version: int = 2) -> Path:
    """Write a minimal but valid single-file VPK (data embedded as preload bytes)."""
    tree: dict[str, dict[str, list[tuple[str, bytes]]]] = {}
    for full, data in files.items():
        directory, _, filename = full.rpartition("/")
        if "." in filename:
            name, _, ext = filename.rpartition(".")
        else:
            name, ext = filename, ""
        tree.setdefault(ext or " ", {}).setdefault(directory or " ", []).append((name, data))
    out = bytearray()
    for ext, dirs in tree.items():
        out += ext.encode() + b"\0"
        for directory, entries in dirs.items():
            out += directory.encode() + b"\0"
            for name, data in entries:
                out += name.encode() + b"\0"
                out += struct.pack("<IHHIIH", 0, len(data), 0x7FFF, 0, 0, 0xFFFF)
                out += data
            out += b"\0"
        out += b"\0"
    out += b"\0"
    header = struct.pack("<III", 0x55AA1234, version, len(out))
    if version == 2:
        header += struct.pack("<IIII", 0, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + bytes(out))
    return path


def make_game(root: Path) -> Path:
    """A fake Deadlock install: <root>/Deadlock/game/citadel/gameinfo.gi."""
    game = root / "Deadlock"
    citadel = game / "game" / "citadel"
    citadel.mkdir(parents=True)
    (citadel / "gameinfo.gi").write_bytes(VANILLA.read_bytes())
    return game
