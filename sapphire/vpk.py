"""Reading the directory tree of Valve VPK files (v1 and v2, Source 2 included).

Only the tree at the start of the file is read, so listing a 500 MB skin
takes milliseconds. Used for conflict detection.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

VPK_SIGNATURE = 0x55AA1234
_ENTRY = struct.Struct("<IHHIIH")  # crc, preload, archive index, offset, length, terminator
MAX_TREE = 256 * 1024 * 1024

# pak01_dir.vpk, pak01_000.vpk, Pak42_DIR.VPK ...
PAK_NAME_RE = re.compile(r"^pak(\d{2})_(dir|\d{3})\.vpk$", re.IGNORECASE)
CHUNK_RE = re.compile(r"^(?P<stem>.+)_(?P<idx>\d{3})\.vpk$", re.IGNORECASE)


class VpkError(ValueError):
    pass


@dataclass
class Entry:
    path: str          # as stored, e.g. "models/heroes/haze/haze.vmdl_c"
    crc: int
    length: int        # bytes in the data archive (not counting preload)
    preload: int


def list_entries(path: Path | str) -> list[str]:
    """Return every file path stored in the VPK, lower-cased, '/' separated."""
    return [e.path.lower() for e in read_entries(path)]


def read_entries(path: Path | str) -> list[Entry]:
    """Return every entry in the VPK's directory tree (paths as stored)."""
    with open(path, "rb") as fh:
        header = fh.read(12)
        if len(header) < 12:
            raise VpkError("file too small to be a VPK")
        sig, version, tree_size = struct.unpack("<III", header)
        if sig != VPK_SIGNATURE:
            raise VpkError("not a VPK file")
        if version == 2:
            fh.read(16)
        elif version != 1:
            raise VpkError(f"unsupported VPK version {version}")
        if tree_size > MAX_TREE:
            raise VpkError("VPK tree is unreasonably large")
        tree = fh.read(tree_size)
    if len(tree) < tree_size:
        raise VpkError("VPK tree is truncated")
    return _parse_tree(tree)


def _parse_tree(tree: bytes) -> list[Entry]:
    pos = 0
    out: list[Entry] = []

    def read_str() -> str:
        nonlocal pos
        end = tree.find(b"\0", pos)
        if end == -1:
            raise VpkError("VPK tree is corrupt")
        s = tree[pos:end].decode("utf-8", errors="replace")
        pos = end + 1
        return s

    while True:
        ext = read_str()
        if not ext:
            break
        while True:
            directory = read_str()
            if not directory:
                break
            while True:
                name = read_str()
                if not name:
                    break
                if pos + _ENTRY.size > len(tree):
                    raise VpkError("VPK tree is corrupt")
                crc, preload, _idx, _off, length, term = _ENTRY.unpack_from(tree, pos)
                if term != 0xFFFF:
                    raise VpkError("VPK tree is corrupt (bad terminator)")
                pos += _ENTRY.size + preload
                parts = []
                if directory.strip():
                    parts.append(directory.strip().strip("/"))
                filename = name if ext.strip() == "" else f"{name}.{ext}"
                parts.append(filename)
                out.append(Entry(path="/".join(parts), crc=crc, length=length, preload=preload))
    return out


def is_vpk(path: Path | str) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    return len(head) == 4 and struct.unpack("<I", head)[0] == VPK_SIGNATURE


@dataclass
class VpkSet:
    """One loadable VPK: the main file plus any numbered data chunks."""
    main: Path                 # e.g. .../pak01_dir.vpk or .../cool_skin.vpk
    chunks: list[Path]         # e.g. [.../pak01_000.vpk, .../pak01_001.vpk]
    rel: str                   # path inside the extracted archive, for display/matching

    @property
    def files(self) -> list[Path]:
        return [self.main, *self.chunks]

    @property
    def size(self) -> int:
        total = 0
        for f in self.files:
            try:
                total += f.stat().st_size
            except OSError:
                pass
        return total


def find_sets(root: Path) -> list[VpkSet]:
    """Group the VPKs found under `root` into loadable sets."""
    root = Path(root)
    all_vpks = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".vpk")
    chunk_owner: dict[Path, list[Path]] = {}
    mains: list[Path] = []
    for p in all_vpks:
        m = CHUNK_RE.match(p.name)
        if m:
            stem = m.group("stem")
            # A chunk belongs to <stem>_dir.vpk in the same folder.
            owner = next((q for q in p.parent.iterdir()
                          if q.name.lower() == f"{stem.lower()}_dir.vpk"), None)
            if owner is not None:
                chunk_owner.setdefault(owner, []).append(p)
                continue
        mains.append(p)
    sets = []
    for p in mains:
        if not is_vpk(p):
            continue
        rel = p.relative_to(root).as_posix()
        sets.append(VpkSet(main=p, chunks=sorted(chunk_owner.get(p, [])), rel=rel))
    return sets


def chunk_index(path: Path) -> str | None:
    m = CHUNK_RE.match(path.name)
    return m.group("idx") if m else None
