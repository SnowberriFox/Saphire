"""Binary KeyValues3 (the data inside compiled Source 2 files), read and patched in place.

Compiled resources such as a hero model (`.vmdl_c`) keep their data in binary
KV3 blocks. Sapphire never re-encodes one from scratch: the engine's model
loader is strict about details a re-encode loses (value flags, typed and
auxiliary-buffer arrays). Instead a block is decompressed with every
structural byte kept, numbers are overwritten where they sit, and the block
is shipped uncompressed (which the engine reads directly).

Supported: KV3 v4 (one buffer) and v5 (two buffers, what Deadlock uses),
LZ4 or Zstandard compressed. Layout and node types follow ValveResourceFormat
and Deadlock Mod Manager's byte-faithful patcher (both MIT).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC_BASE = 0x4B563300          # "\0" "3" "V" "K" little-endian, low byte = version
BLOB_TRAILER = 0xFFEEDD00

# node types (VRF KV3BinaryNodeType)
NULL, BOOLEAN, INT64, UINT64, DOUBLE, STRING, BINARY_BLOB, ARRAY, OBJECT, ARRAY_TYPED = range(1, 11)
INT32, UINT32, BOOLEAN_TRUE, BOOLEAN_FALSE, INT64_ZERO, INT64_ONE, DOUBLE_ZERO, DOUBLE_ONE = range(11, 19)
FLOAT, INT16, UINT16, INT8, INT32_AS_BYTE, ARRAY_TYPE_BYTE_LENGTH, ARRAY_TYPE_AUXILIARY_BUFFER = range(19, 26)
UINT32_ZERO, UINT32_ONE = 26, 27

B1, B2, B4, B8 = range(4)


class Kv3Error(ValueError):
    pass


class Unpatchable(Kv3Error):
    """The value can't be changed in place (stored as a constant with no bytes, or missing)."""


def _i32(b, o) -> int:
    if o + 4 > len(b):
        raise Kv3Error("header field out of range")
    return struct.unpack_from("<i", b, o)[0]


def _u32(b, o) -> int:
    if o + 4 > len(b):
        raise Kv3Error("read out of range")
    return struct.unpack_from("<I", b, o)[0]


def version_of(block: bytes) -> int:
    if len(block) < 24:
        raise Kv3Error("block too short for KV3")
    magic = _u32(block, 0)
    if magic & 0xFFFFFF00 != MAGIC_BASE:
        raise Kv3Error("not a binary KV3 block")
    return magic & 0xFF


# ---------------------------------------------------------------------- compression

def _decompress(src: bytes, method: int, size_unc: int, size_comp: int) -> bytes:
    if method == 0:
        return bytes(src[:size_unc])
    data = bytes(src[:size_comp])
    if len(data) < size_comp:
        raise Kv3Error("compressed buffer is truncated")
    if method == 1:
        import lz4.block
        out = lz4.block.decompress(data, uncompressed_size=size_unc)
    elif method == 2:
        import zstandard
        out = zstandard.ZstdDecompressor().decompress(data, max_output_size=size_unc)
    else:
        raise Kv3Error(f"unknown KV3 compression method {method}")
    if len(out) != size_unc:
        raise Kv3Error(f"decompressed to {len(out)} bytes, expected {size_unc}")
    return out


def _lz4(data: bytes) -> bytes:
    import lz4.block
    return lz4.block.compress(data, store_size=False)


def _has_blobs(block: bytes) -> bool:
    return len(block) >= 60 and _i32(block, 56) != 0


def working_copy(block: bytes) -> bytearray:
    """The block with its typed buffers decompressed in place: same header, same
    bytes, walkable. For a block without a binary-blob section this is also a
    valid uncompressed block the engine loads as is (`compressionMethod = 0`)."""
    version = version_of(block)
    if version not in (4, 5):
        raise Kv3Error(f"KV3 v{version} isn't supported")
    method = _u32(block, 20)
    blobs = _has_blobs(block)
    if version == 5:
        unc1, comp1, unc2, comp2 = (_i32(block, o) for o in (72, 76, 80, 84))
        if min(unc1, comp1, unc2, comp2) < 0:
            raise Kv3Error("negative buffer size")
        if method == 0:
            comp1, comp2 = unc1, unc2
        b1 = _decompress(block[120:120 + comp1], method, unc1, comp1)
        b2 = _decompress(block[120 + comp1:120 + comp1 + comp2], method, unc2, comp2)
        out = bytearray(block[:120]) + b1 + b2
        if not blobs:
            struct.pack_into("<I", out, 20, 0)          # compressionMethod
            struct.pack_into("<H", out, 26, 0)          # frame size
            struct.pack_into("<i", out, 52, _i32(block, 48))
            struct.pack_into("<I", out, 68, 0)          # sizeBlockCompressed
            struct.pack_into("<i", out, 76, unc1)
            struct.pack_into("<i", out, 84, unc2)
        return out
    # v4: [header 72][one buffer]
    if blobs and method != 0:
        raise Kv3Error("v4 block with binary blobs isn't supported")
    unc, comp = _i32(block, 48), _i32(block, 52)
    if method == 0:
        comp = unc
    buf = _decompress(block[72:72 + comp], method, unc, comp)
    out = bytearray(block[:72]) + buf
    struct.pack_into("<I", out, 20, 0)
    struct.pack_into("<H", out, 26, 0)
    struct.pack_into("<i", out, 52, unc)
    struct.pack_into("<I", out, 68, 0)
    return out


def _reassemble_blobbed_v5(orig: bytes, work: bytes) -> bytes:
    """Re-emit a compressed v5 block that has a binary-blob section from a patched
    working copy, recompressing only the typed buffer that changed (LZ4) and
    carrying the blob frames through byte for byte. Flipping such a block to
    uncompressed would leave a stale frame table the engine still reads."""
    method = _u32(orig, 20)
    unc1, comp1, unc2, comp2 = (_i32(orig, o) for o in (72, 76, 80, 84))
    frames = orig[120 + comp1 + comp2:]
    new1 = bytes(work[120:120 + unc1])
    new2 = bytes(work[120 + unc1:120 + unc1 + unc2])
    old_c1 = orig[120:120 + comp1]
    old_c2 = orig[120 + comp1:120 + comp1 + comp2]
    parts = []
    for new, old_c, unc in ((new1, old_c1, unc1), (new2, old_c2, unc2)):
        if new == _decompress(old_c, method, unc, len(old_c)):
            parts.append(bytes(old_c))
        elif method == 1:
            parts.append(_lz4(new))
        else:
            raise Kv3Error("can only recompress LZ4 blocks with binary blobs")
    out = bytearray(orig[:120])
    struct.pack_into("<i", out, 52, len(parts[0]) + len(parts[1]))
    struct.pack_into("<i", out, 76, len(parts[0]))
    struct.pack_into("<i", out, 84, len(parts[1]))
    return bytes(out) + parts[0] + parts[1] + frames


# ---------------------------------------------------------------------- layout + walk

class _Lane:
    __slots__ = ("base", "pos")

    def __init__(self, base: int):
        self.base, self.pos = base, 0

    @property
    def at(self) -> int:
        return self.base + self.pos


def _align(off: int, a: int) -> int:
    return (off + a - 1) & ~(a - 1)


def _lane(off: int, count: int, elem: int) -> tuple[int, int]:
    """(start, offset after) of a lane of `count` items of `elem` bytes."""
    if count == 0:
        return off, off
    start = _align(off, elem)
    return start, start + count * elem


def _cstr(b: bytes, pos: int) -> tuple[str, int]:
    end = b.find(b"\0", pos)
    if end < 0:
        raise Kv3Error("unterminated string")
    return b[pos:end].decode("utf-8", errors="replace"), end + 1


@dataclass
class Slot:
    """Where one number lives in the working copy."""
    offset: int        # absolute byte offset, or -1 for a tagless constant
    datatype: int


class _Walker:
    def __init__(self, work: bytes):
        self.b = work
        self.version = version_of(work)
        if self.version == 5:
            self._layout_v5()
        elif self.version == 4:
            self._layout_v4()
        else:
            raise Kv3Error(f"KV3 v{self.version} isn't supported")
        self.slots: dict[tuple, Slot] = {}
        self.dupes: set[tuple] = set()

    def _layout_v5(self):
        b = self.b
        aux_b1, aux_b4, aux_b8, aux_b2 = _i32(b, 28), _i32(b, 32), _i32(b, 36), _i32(b, 64)
        unc1 = _i32(b, 72)
        m_b1, m_b2, m_b4, m_b8, m_obj = (_i32(b, o) for o in (88, 92, 96, 100, 108))
        buf1, buf2 = 120, 120 + unc1
        off = aux_b1
        a_b2, off = _lane(off, aux_b2, 2)
        a_b4, off = _lane(off, aux_b4, 4)
        a_b8, off = _lane(off, aux_b8, 8)
        n_strings = _u32(b, buf1 + a_b4) if aux_b4 else 0
        sp = buf1
        self.strings = []
        for _ in range(n_strings):
            s, sp = _cstr(b, sp)
            self.strings.append(s)
        self.aux = [_Lane(sp), _Lane(buf1 + a_b2), _Lane(buf1 + a_b4 + 4), _Lane(buf1 + a_b8)]
        off = 0
        ol = off
        off += m_obj * 4
        mb1 = off
        off += m_b1
        mb2, off = _lane(off, m_b2, 2)
        mb4, off = _lane(off, m_b4, 4)
        mb8, off = _lane(off, m_b8, 8)
        self.main = [_Lane(buf2 + mb1), _Lane(buf2 + mb2), _Lane(buf2 + mb4), _Lane(buf2 + mb8)]
        self.types = _Lane(buf2 + off)
        self.obj_lengths = _Lane(buf2 + ol)

    def _layout_v4(self):
        b = self.b
        c_b1, c_b4, c_b8, c_b2 = _i32(b, 28), _i32(b, 32), _i32(b, 36), _i32(b, 64)
        base = 72
        off = c_b1
        b2s, off = _lane(off, c_b2, 2)
        b4s, off = _lane(off, c_b4, 4)
        if c_b8:
            b8s, off = _lane(off, c_b8, 8)
        else:
            off = _align(off, 8)
            b8s = off
        n_strings = _u32(b, base + b4s)
        sp = base + off
        self.strings = []
        for _ in range(n_strings):
            s, sp = _cstr(b, sp)
            self.strings.append(s)
        self.types = _Lane(sp)
        self.main = [_Lane(base), _Lane(base + b2s), _Lane(base + b4s + 4), _Lane(base + b8s)]
        self.aux = [_Lane(0)] * 4
        self.obj_lengths = _Lane(0)

    # -- primitive reads
    def _type(self) -> int:
        if self.types.at >= len(self.b):
            raise Kv3Error("type stream underrun")
        t = self.b[self.types.at]
        self.types.pos += 1
        if t & 0x80:
            t &= 0x3F
            self.types.pos += 1   # flag byte
        return t

    def _take(self, lane: int, fmt: str, size: int, path: tuple, datatype: int):
        ln = self.main[lane]
        at = ln.at
        if at + size > len(self.b):
            raise Kv3Error("value lane underrun")
        v = struct.unpack_from(fmt, self.b, at)[0]
        ln.pos += size
        if datatype in (DOUBLE, FLOAT):
            self._slot(path, Slot(at, datatype))
        return v

    def _slot(self, path: tuple, slot: Slot):
        if path in self.slots:
            self.dupes.add(path)
        self.slots[path] = slot

    def _count(self, lane: int, size: int) -> int:
        ln = self.main[lane]
        if ln.at + size > len(self.b):
            raise Kv3Error("count lane underrun")
        v = self.b[ln.at] if size == 1 else struct.unpack_from("<I", self.b, ln.at)[0]
        ln.pos += size
        return v

    def _key(self, i: int) -> str:
        if i == 0xFFFFFFFF:
            return ""
        return self.strings[i] if 0 <= i < len(self.strings) else ""

    # -- the walk (cursor discipline identical to the reader)
    def value(self, t: int, path: tuple):
        if t == INT32:
            return self._take(B4, "<i", 4, path, t)
        if t == UINT32:
            return self._take(B4, "<I", 4, path, t)
        if t == FLOAT:
            return self._take(B4, "<f", 4, path, t)
        if t == STRING:
            i = self._take(B4, "<I", 4, path, t)
            return self._key(i)
        if t == INT64:
            return self._take(B8, "<q", 8, path, t)
        if t == UINT64:
            return self._take(B8, "<Q", 8, path, t)
        if t == DOUBLE:
            return self._take(B8, "<d", 8, path, t)
        if t == INT16:
            return self._take(B2, "<h", 2, path, t)
        if t == UINT16:
            return self._take(B2, "<H", 2, path, t)
        if t in (INT8, INT32_AS_BYTE):
            return self._take(B1, "<b", 1, path, t)
        if t == BOOLEAN:
            return bool(self._take(B1, "<B", 1, path, t))
        if t == NULL:
            return None
        if t == BOOLEAN_TRUE:
            return True
        if t == BOOLEAN_FALSE:
            return False
        if t in (INT64_ZERO, UINT32_ZERO):
            return 0
        if t in (INT64_ONE, UINT32_ONE):
            return 1
        if t == DOUBLE_ZERO:
            self._slot(path, Slot(-1, t))
            return 0.0
        if t == DOUBLE_ONE:
            self._slot(path, Slot(-1, t))
            return 1.0
        if t == BINARY_BLOB:
            return b""     # its bytes live in the blob section, not in a lane
        if t == ARRAY:
            n = self._count(B4, 4)
            out = []
            for i in range(n):
                out.append(self.value(self._type(), path + (i,)))
            return out
        if t in (ARRAY_TYPED, ARRAY_TYPE_BYTE_LENGTH, ARRAY_TYPE_AUXILIARY_BUFFER):
            n = self._count(B4, 4) if t == ARRAY_TYPED else self._count(B1, 1)
            sub = self._type()
            if t == ARRAY_TYPE_AUXILIARY_BUFFER:
                self.main, self.aux = self.aux, self.main
            try:
                return [self.value(sub, path + (i,)) for i in range(n)]
            finally:
                if t == ARRAY_TYPE_AUXILIARY_BUFFER:
                    self.main, self.aux = self.aux, self.main
        if t == OBJECT:
            if self.version >= 5:
                ln = self.obj_lengths
                n = _u32(self.b, ln.at)
                ln.pos += 4
            else:
                n = self._count(B4, 4)
            out: dict = {}
            for _ in range(n):
                vt = self._type()
                key = self._key(self._count(B4, 4))
                out[key] = self.value(vt, path + (key,))
            return out
        raise Kv3Error(f"unknown KV3 node type {t}")


@dataclass
class Decoded:
    value: object                 # dicts, lists, numbers, strings
    slots: dict[tuple, Slot]      # path -> where each float/double sits
    dupes: set[tuple]             # paths seen twice (duplicate keys): never patched
    work: bytearray               # the walkable working copy the slots point into
    version: int


def decode(block: bytes) -> Decoded:
    work = working_copy(block)
    w = _Walker(work)
    root = w._type()
    value = w.value(root, ())
    return Decoded(value=value, slots=w.slots, dupes=w.dupes, work=work, version=w.version)


def patch_numbers(block: bytes, edits: dict[tuple, float]) -> bytes:
    """`block` with the floats/doubles at `edits` paths set, every other byte kept.
    Raises Unpatchable when a path is missing, ambiguous, or a tagless constant
    that would need to change (it has no bytes to overwrite)."""
    d = decode(block)
    out = d.work
    for path, value in edits.items():
        slot = d.slots.get(path)
        if slot is None or path in d.dupes:
            raise Unpatchable(f"no single number at {'/'.join(map(str, path))}")
        if slot.offset < 0:
            const = 0.0 if slot.datatype == DOUBLE_ZERO else 1.0
            if float(value) != const:
                raise Unpatchable(f"{'/'.join(map(str, path))} is stored as a constant")
            continue
        if slot.datatype == FLOAT:
            struct.pack_into("<f", out, slot.offset, value)
        else:
            struct.pack_into("<d", out, slot.offset, value)
    if d.version == 5 and _has_blobs(block):
        return _reassemble_blobbed_v5(block, bytes(out))
    return bytes(out)


def get(value, path: tuple):
    """Follow `path` through decoded dicts/lists; None if it isn't there."""
    for seg in path:
        if isinstance(seg, int):
            if not isinstance(value, list) or not 0 <= seg < len(value):
                return None
        elif not isinstance(value, dict) or seg not in value:
            return None
        value = value[seg]
    return value
