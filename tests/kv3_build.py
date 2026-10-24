"""Builds binary KV3 v5 blocks and .vmdl_c-style containers for tests.

Wrappers pick the wire encoding the way Valve's compiler does for model data:
  F(x)              -> FLOAT (4-byte lane)       (plain floats are DOUBLE)
  Typed(xs, sub)    -> ARRAY_TYPE_BYTE_LENGTH with one subtype for every item
  Aux(xs, sub)      -> ARRAY_TYPE_AUXILIARY_BUFFER (items in the aux buffer)
  Flagged(v, flag)  -> the value's type byte carries a flag byte
Zeros and ones in plain arrays become DOUBLE_ZERO / DOUBLE_ONE (no payload).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from sapphire import kv3 as K


@dataclass
class F:
    v: float


@dataclass
class Typed:
    items: list
    sub: int


@dataclass
class Aux:
    items: list
    sub: int


@dataclass
class Flagged:
    v: object
    flag: int = 1


class _Lanes:
    def __init__(self):
        self.b1, self.b2, self.b4, self.b8 = bytearray(), bytearray(), bytearray(), bytearray()

    def counts(self):
        return len(self.b1), len(self.b2) // 2, len(self.b4) // 4, len(self.b8) // 8


class Builder:
    def __init__(self, constants: bool = True):
        self.strings: list[str] = []
        self.types = bytearray()
        self.main, self.aux = _Lanes(), _Lanes()
        self.objs: list[int] = []
        self.constants = constants

    def sid(self, s: str) -> int:
        if s not in self.strings:
            self.strings.append(s)
        return self.strings.index(s)

    def type_of(self, v) -> int:
        if isinstance(v, Flagged):
            return self.type_of(v.v)
        if v is None:
            return K.NULL
        if isinstance(v, bool):
            return K.BOOLEAN_TRUE if v else K.BOOLEAN_FALSE
        if isinstance(v, int):
            return K.INT32
        if isinstance(v, F):
            return K.FLOAT
        if isinstance(v, float):
            if self.constants and v == 0.0:
                return K.DOUBLE_ZERO
            if self.constants and v == 1.0:
                return K.DOUBLE_ONE
            return K.DOUBLE
        if isinstance(v, str):
            return K.STRING
        if isinstance(v, Typed):
            return K.ARRAY_TYPE_BYTE_LENGTH
        if isinstance(v, Aux):
            return K.ARRAY_TYPE_AUXILIARY_BUFFER
        if isinstance(v, list):
            return K.ARRAY
        if isinstance(v, dict):
            return K.OBJECT
        raise TypeError(v)

    def emit_type(self, v):
        t = self.type_of(v)
        if isinstance(v, Flagged):
            self.types += bytes([t | 0x80, v.flag])
        else:
            self.types.append(t)
        return t

    def payload(self, v, t: int, lanes: _Lanes):
        if isinstance(v, Flagged):
            v = v.v
        if t == K.INT32:
            lanes.b4 += struct.pack("<i", v)
        elif t == K.FLOAT:
            lanes.b4 += struct.pack("<f", v.v if isinstance(v, F) else v)
        elif t == K.DOUBLE:
            lanes.b8 += struct.pack("<d", float(v.v if isinstance(v, F) else v))
        elif t == K.STRING:
            lanes.b4 += struct.pack("<I", self.sid(v))
        elif t == K.ARRAY:
            lanes.b4 += struct.pack("<I", len(v))
            for item in v:
                self.payload(item, self.emit_type(item), lanes)
        elif t in (K.ARRAY_TYPE_BYTE_LENGTH, K.ARRAY_TYPE_AUXILIARY_BUFFER):
            lanes.b1.append(len(v.items))
            self.types.append(v.sub)
            target = self.aux if t == K.ARRAY_TYPE_AUXILIARY_BUFFER else lanes
            for item in v.items:
                self.payload(item, v.sub, target)
        elif t == K.OBJECT:
            self.objs.append(len(v))
            for key, item in v.items():
                it = self.emit_type(item)
                lanes.b4 += struct.pack("<I", self.sid(key))
                self.payload(item, it, lanes)
        # constants carry nothing

    def build(self, root, method: int = 1) -> bytes:
        t = self.emit_type(root)
        self.payload(root, t, self.main)
        strings = b"".join(s.encode() + b"\0" for s in self.strings)

        def pad(buf: bytearray, a: int):
            while len(buf) % a:
                buf.append(0)

        # aux buffer: [strings][b1] [b2] [count + b4] [b8]
        a = self.aux
        buf1 = bytearray(strings + a.b1)
        if a.b2:
            pad(buf1, 2); buf1 += a.b2
        pad(buf1, 4); buf1 += struct.pack("<I", len(self.strings)) + a.b4
        if a.b8:
            pad(buf1, 8); buf1 += a.b8
        # main buffer: [object lengths][b1][b2][b4][b8][types][trailer]
        m = self.main
        buf2 = bytearray(b"".join(struct.pack("<I", n) for n in self.objs) + m.b1)
        if m.b2:
            pad(buf2, 2); buf2 += m.b2
        if m.b4:
            pad(buf2, 4); buf2 += m.b4
        if m.b8:
            pad(buf2, 8); buf2 += m.b8
        buf2 += self.types + struct.pack("<I", K.BLOB_TRAILER)

        if method == 1:
            import lz4.block
            c1, c2 = (lz4.block.compress(bytes(b), store_size=False) for b in (buf1, buf2))
        elif method == 2:
            import zstandard
            c1, c2 = (zstandard.ZstdCompressor().compress(bytes(b)) for b in (buf1, buf2))
        else:
            c1, c2 = bytes(buf1), bytes(buf2)
        h = bytearray(120)
        struct.pack_into("<I", h, 0, K.MAGIC_BASE | 5)
        h[4:20] = b"\x7c\x16\x12\x74\xe9\x06\x98\x46\xaf\xf2\xe6\x3e\xb5\x90\x37\xe7"
        struct.pack_into("<I", h, 20, method)
        struct.pack_into("<iii", h, 28, len(strings) + len(a.b1), len(a.b4) // 4 + 1, len(a.b8) // 8)
        struct.pack_into("<i", h, 64, len(a.b2) // 2)
        struct.pack_into("<ii", h, 48, len(buf1) + len(buf2), len(c1) + len(c2))
        struct.pack_into("<iiii", h, 72, len(buf1), len(c1), len(buf2), len(c2))
        mb1, mb2, mb4, mb8 = m.counts()
        struct.pack_into("<iiii", h, 88, mb1, mb2, mb4, mb8)
        struct.pack_into("<i", h, 108, len(self.objs))
        return bytes(h) + c1 + c2


def encode(root, method: int = 1, constants: bool = True) -> bytes:
    return Builder(constants=constants).build(root, method)


def container(blocks: list[tuple[str, bytes]]) -> bytes:
    """A compiled-resource file holding `blocks` in order."""
    out = bytearray(16 + 12 * len(blocks))
    struct.pack_into("<IHHII", out, 0, 0, 12, 0, 8, len(blocks))
    for i, (kind, data) in enumerate(blocks):
        while len(out) % 16:
            out.append(0)
        entry = 16 + 12 * i
        off = len(out)
        out[entry:entry + 4] = kind.encode()
        struct.pack_into("<II", out, entry + 4, off - entry - 4, len(data))
        out += data
    while len(out) % 16:
        out.append(0)
    struct.pack_into("<I", out, 0, len(out))
    return bytes(out)


# ---------------------------------------------------------------------- hero-model fixtures

OLD = (-0.5, -0.5, -0.5, 0.5)
IDENT = (0.0, 0.0, 0.0, 1.0)


def vec(xs, as_float=True):
    return Typed([F(x) for x in xs] if as_float else [float(x) for x in xs], K.FLOAT if as_float else K.DOUBLE)


def point(name, parent, offset, q, as_float=True):
    return {"key": name, "value": {
        "m_name": name,
        "m_influenceNames": Typed([parent, "", ""], K.STRING),
        "m_vInfluenceRotations": [vec(q, as_float), vec(IDENT, as_float), vec(IDENT, as_float)],
        "m_vInfluenceOffsets": [vec(offset, as_float), vec((0, 0, 0), as_float), vec((0, 0, 0), as_float)],
        "m_influenceWeights": Typed([F(1.0), F(0.0), F(0.0)], K.FLOAT),
        "m_bInfluenceRootTransform": [False, False, False],
        "m_nInfluences": 1,
    }}


def mesh(frame, extra=(), as_float=True):
    pts = [
        point("standing_pivot", "root_motion", (2.0, 94.0, -3.0), frame, as_float),
        point("crouching_pivot", "root_motion", (1.0, 55.0, 4.0), frame, as_float),
        point("aim", "root_motion", (5.0, 70.0, 6.0), frame, as_float),
        point("custom_fx", "head", (7.0, 8.0, 9.0), frame, as_float),
        *extra,
    ]
    return {"m_attachments": pts, "m_material": Flagged("materials/x.vmat", 1),
            "m_sceneObjects": Aux([F(0.25), F(0.5)], K.FLOAT)}


def model_data(root_rot=IDENT, root_parent=-1, scale=1.0):
    return {"m_modelSkeleton": {
        "m_boneName": ["root_motion", "pelvis", "head"],
        "m_nParent": [root_parent, 0, 1],
        "m_bonePosParent": [Typed([F(0), F(0), F(0)], K.FLOAT)] * 3,
        "m_boneRotParent": [Typed([F(v) for v in root_rot], K.FLOAT), vec(IDENT), vec(IDENT)],
        "m_boneScaleParent": [F(scale), F(1.0), F(1.0)],
    }, "m_modelInfo": {"m_keyValueText": "<!-- kv3 -->{}"}}


def vmdl(frame, *, extra=(), root_rot=IDENT, as_float=True, method=1, meshes=1) -> bytes:
    blocks = [("DATA", encode(model_data(root_rot), method))]
    for _ in range(meshes):
        blocks.append(("MDAT", encode(mesh(frame, extra, as_float), method)))
    blocks.append(("VBIB", b"\x01\x02\x03\x04\x05"))
    return container(blocks)
