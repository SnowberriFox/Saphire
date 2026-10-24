"""Valve VPK files (v1 and v2, Source 2 included).

Listing only reads the tree at the start of the file, so listing a 500 MB skin
takes milliseconds (used for conflict detection). `VpkReader` pulls single
files out (from the directory file or its numbered chunks), and `write_vpk`
makes a small single-file v2 VPK (used for the camera-fix overlay).
"""

from __future__ import annotations

import hashlib
import re
import struct
import zlib
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


EMBEDDED = 0x7FFF   # archive index meaning "data is in the directory file itself"


@dataclass
class Entry:
    path: str          # as stored, e.g. "models/heroes/haze/haze.vmdl_c"
    crc: int
    length: int        # bytes in the data archive (not counting preload)
    preload: int
    archive: int = EMBEDDED   # chunk number (pak01_000.vpk = 0), or EMBEDDED
    offset: int = 0           # in the chunk, or from the start of the embedded data
    preload_at: int = 0       # where the preload bytes sit inside the tree


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
                crc, preload, idx, off, length, term = _ENTRY.unpack_from(tree, pos)
                if term != 0xFFFF:
                    raise VpkError("VPK tree is corrupt (bad terminator)")
                preload_at = pos + _ENTRY.size
                pos += _ENTRY.size + preload
                parts = []
                if directory.strip():
                    parts.append(directory.strip().strip("/"))
                filename = name if ext.strip() == "" else f"{name}.{ext}"
                parts.append(filename)
                out.append(Entry(path="/".join(parts), crc=crc, length=length, preload=preload,
                                 archive=idx, offset=off, preload_at=preload_at))
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


# ---------------------------------------------------------------------- reading files

class VpkReader:
    """Reads files out of one VPK. `chunks` maps chunk numbers to their files; by
    default they're found next to the directory file (pak01_dir.vpk -> pak01_000.vpk)."""

    def __init__(self, path: Path | str, chunks: dict[int, Path] | None = None):
        self.path = Path(path)
        with open(self.path, "rb") as fh:
            header = fh.read(12)
            if len(header) < 12:
                raise VpkError("file too small to be a VPK")
            sig, version, tree_size = struct.unpack("<III", header)
            if sig != VPK_SIGNATURE:
                raise VpkError("not a VPK file")
            if version == 2:
                fh.read(16)
                header_len = 28
            elif version == 1:
                header_len = 12
            else:
                raise VpkError(f"unsupported VPK version {version}")
            if tree_size > MAX_TREE:
                raise VpkError("VPK tree is unreasonably large")
            self.tree = fh.read(tree_size)
        self.data_start = header_len + tree_size
        self.entries = {e.path.lower(): e for e in _parse_tree(self.tree)}
        self._chunks = dict(chunks or {})
        if chunks is None and self.path.name.lower().endswith("_dir.vpk"):
            stem = self.path.name[: -len("_dir.vpk")]
            for p in self.path.parent.iterdir():
                m = CHUNK_RE.match(p.name)
                if m and m.group("stem").lower() == stem.lower():
                    self._chunks[int(m.group("idx"))] = p

    def __contains__(self, path: str) -> bool:
        return path.lower() in self.entries

    def read(self, path: str) -> bytes:
        e = self.entries.get(path.lower())
        if e is None:
            raise KeyError(path)
        data = self.tree[e.preload_at:e.preload_at + e.preload]
        if e.length:
            if e.archive == EMBEDDED:
                src, at = self.path, self.data_start + e.offset
            else:
                src = self._chunks.get(e.archive)
                if src is None:
                    raise VpkError(f"missing data chunk {e.archive:03d} for {self.path.name}")
                at = e.offset
            with open(src, "rb") as fh:
                fh.seek(at)
                body = fh.read(e.length)
            if len(body) != e.length:
                raise VpkError(f"{path} is truncated in {Path(src).name}")
            data += body
        return data


# ---------------------------------------------------------------------- writing

def write_vpk(dest: Path | str, files: dict[str, bytes]) -> None:
    """Write a single-file v2 VPK holding `files` ({"models/x/y.vmdl_c": bytes}),
    the layout ValvePak and Valve's own tool produce (tree, embedded data, then
    the tree/archive/whole-file MD5s; no signature)."""
    groups: dict[str, dict[str, list[tuple[str, bytes]]]] = {}
    for path, data in files.items():
        path = path.replace("\\", "/").strip("/")
        folder, _, filename = path.rpartition("/")
        name, dot, ext = filename.rpartition(".")
        if not dot:
            name, ext = filename, ""
        groups.setdefault(ext or " ", {}).setdefault(folder or " ", []).append((name, data))
    tree = bytearray()
    body = bytearray()
    for ext in sorted(groups):
        tree += ext.encode() + b"\0"
        for folder in sorted(groups[ext]):
            tree += folder.encode() + b"\0"
            for name, data in sorted(groups[ext][folder]):
                tree += name.encode() + b"\0"
                tree += _ENTRY.pack(zlib.crc32(data) & 0xFFFFFFFF, 0, EMBEDDED, len(body), len(data), 0xFFFF)
                body += data
            tree += b"\0"
        tree += b"\0"
    tree += b"\0"
    header = struct.pack("<IIIIIII", VPK_SIGNATURE, 2, len(tree), len(body), 0, 48, 0)
    archive_md5s = b""
    md5s = hashlib.md5(bytes(tree)).digest() + hashlib.md5(archive_md5s).digest()
    whole = hashlib.md5(header + bytes(tree) + bytes(body) + archive_md5s + md5s).digest()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_bytes(header + bytes(tree) + bytes(body) + archive_md5s + md5s + whole)
    tmp.replace(dest)
