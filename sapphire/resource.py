"""Source 2 compiled resource containers (.vmdl_c and friends).

Layout: a 16-byte header (file size, header version 12, resource version,
offset to the block table, block count), then 12-byte entries (FOURCC, offset
relative to the entry's offset field, size), then the block payloads.
Rebuilding keeps block order and count (models reference blocks by index) and
16-byte-aligns each payload, as Valve's files do.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER_LEN = 16
HEADER_VERSION = 12


class ResourceError(ValueError):
    pass


@dataclass
class Block:
    kind: str
    offset: int
    size: int


class Resource:
    def __init__(self, raw: bytes):
        if len(raw) < HEADER_LEN:
            raise ResourceError("file too small to be a compiled resource")
        _size, hver, self.version, block_off, count = struct.unpack_from("<IHHII", raw, 0)
        if hver != HEADER_VERSION:
            raise ResourceError(f"unexpected resource header version {hver}")
        table = 8 + block_off
        if table < HEADER_LEN or table + count * 12 > len(raw) or count > 4096:
            raise ResourceError("block table out of range")
        self.raw = raw
        self.blocks: list[Block] = []
        for i in range(count):
            e = table + i * 12
            kind = raw[e:e + 4].decode("latin-1")
            rel, size = struct.unpack_from("<II", raw, e + 4)
            off = e + 4 + rel
            if off + size > len(raw):
                raise ResourceError("block payload out of range")
            self.blocks.append(Block(kind, off, size))

    def block(self, index: int) -> bytes:
        b = self.blocks[index]
        return self.raw[b.offset:b.offset + b.size]

    def indices(self, kind: str) -> list[int]:
        return [i for i, b in enumerate(self.blocks) if b.kind == kind]

    def first(self, kind: str) -> bytes | None:
        idx = self.indices(kind)
        return self.block(idx[0]) if idx else None

    def rebuild(self, replace: dict[int, bytes]) -> bytes:
        """The resource with the given blocks swapped, every other block byte-identical."""
        end = max((b.offset + b.size for b in self.blocks), default=HEADER_LEN)
        tail = self.raw[end:]
        if len(tail) > 15 or any(tail):
            raise ResourceError("resource has data outside its blocks; not rebuilding it")
        payloads = [replace.get(i, self.block(i)) for i in range(len(self.blocks))]
        cursor = _align16(HEADER_LEN + 12 * len(payloads))
        offsets = []
        for p in payloads:
            offsets.append(cursor)
            cursor = _align16(cursor + len(p))
        out = bytearray(cursor)
        struct.pack_into("<IHHII", out, 0, cursor, HEADER_VERSION, self.version, 8, len(payloads))
        for i, (b, p) in enumerate(zip(self.blocks, payloads)):
            e = HEADER_LEN + 12 * i
            out[e:e + 4] = b.kind.encode("latin-1")
            struct.pack_into("<II", out, e + 4, offsets[i] - (e + 4), len(p))
            out[offsets[i]:offsets[i] + len(p)] = p
        rebuilt = bytes(out)
        check = Resource(rebuilt)
        if len(check.blocks) != len(self.blocks) or any(
                a.kind != b.kind or (i not in replace and self.block(i) != check.block(i))
                for i, (a, b) in enumerate(zip(self.blocks, check.blocks))):
            raise ResourceError("rebuild changed another block")
        return rebuilt


def _align16(n: int) -> int:
    return (n + 15) & ~15
