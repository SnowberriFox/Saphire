"""Fixing the first-person camera on hero skins made before Deadlock's camera update.

A Deadlock update turned the attachment points that hang off a hero's
`root_motion` bone by 120 degrees, including `standing_pivot` and
`crouching_pivot`, which the first-person camera and aim come from. A skin
compiled before the update still carries the old orientation, so in game the
camera sits in the wrong spot.

The repair (ported from Deadlock Mod Manager's camera-frame migration):

  * the installed game's own model must already use the new frame (pivots at
    the identity rotation), otherwise there's nothing to migrate to;
  * the skin's pivots must all be in the old frame (quaternion
    [-0.5, -0.5, -0.5, 0.5]), within 30 degrees so authored tweaks still count;
  * its root_motion bone must match the game's (no parent, same scale and
    rotation), so the conversion is valid in its coordinates;
  * then every attachment on root_motion gets its offset remapped
    (x, y, z) -> (z, x, y) and its rotation turned by the inverse of the old
    basis. Custom offsets survive; they're converted, not replaced.

Anything blended across several bones, mixed frames or duplicate names is left
alone with a warning: guessing would be worse than the original bug. Numbers
are overwritten in place (see kv3.py), the result is checked by decoding it
again, and the original mod file is never changed; the fixed model goes in a
separate overlay VPK.
"""

from __future__ import annotations

import logging
import math
import struct
from dataclasses import dataclass, field

from sapphire import kv3
from sapphire.resource import Resource, ResourceError

log = logging.getLogger(__name__)

PIVOTS = ("standing_pivot", "crouching_pivot")
OLD_FRAME = (-0.5, -0.5, -0.5, 0.5)
IDENTITY = (0.0, 0.0, 0.0, 1.0)
FRAME_TOLERANCE = math.pi / 6      # the update turned things by 120 degrees; tweaks sit well inside 30
ROOT_ANGLE_TOLERANCE = 0.001
SAME_ROTATION = 0.0002


@dataclass
class Outcome:
    status: str                    # "fixed", "warning", "ok" (nothing to do), "skipped" (not checkable)
    detail: str = ""
    data: bytes | None = None      # the repaired model, when fixed
    attachments: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------- quaternion helpers

def _norm(q) -> float:
    return math.sqrt(sum(v * v for v in q))


def angle(a, b) -> float | None:
    na, nb = _norm(a), _norm(b)
    if not (math.isfinite(na) and math.isfinite(nb)) or abs(na - 1) > 0.001 or abs(nb - 1) > 0.001:
        return None
    dot = sum(x * y for x, y in zip(a, b)) / (na * nb)
    return 2.0 * math.acos(min(1.0, abs(dot)))


def convert(q):
    """Undo the old root attachment basis (which mapped (x, y, z) to (y, z, x))."""
    x, y, z, w = q
    return ((x + w + z - y) * 0.5, (y + w + x - z) * 0.5, (z + w + y - x) * 0.5, (w - x - y - z) * 0.5)


def _vec(value, n: int):
    if not isinstance(value, list) or len(value) != n:
        return None
    out = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return None
        out.append(float(v))
    return tuple(out)


# ---------------------------------------------------------------------- reading attachments

def _items(mesh) -> list:
    a = mesh.get("m_attachments") if isinstance(mesh, dict) else None
    return a if isinstance(a, list) else []


def _single_root(v) -> bool:
    if not isinstance(v, dict) or v.get("m_nInfluences") != 1:
        return False
    names = v.get("m_influenceNames")
    flags = v.get("m_bInfluenceRootTransform")
    return (isinstance(names, list) and names and names[0] == "root_motion"
            and all(n == "" for n in names[1:])
            and isinstance(flags, list) and flags and flags[0] is False)


def attachment(mesh, name: str):
    hits = [it.get("value") for it in _items(mesh) if isinstance(it, dict) and it.get("key") == name]
    if len(hits) != 1 or not _single_root(hits[0]):
        return None
    return hits[0]


def rotation(v):
    rots = v.get("m_vInfluenceRotations") if isinstance(v, dict) else None
    if not isinstance(rots, list) or not rots:
        return None
    return _vec(rots[0], 4)


def _has(mesh, name: str) -> bool:
    return any(isinstance(it, dict) and it.get("key") == name for it in _items(mesh))


def pivot_frame(mesh, name: str) -> str | None:
    """'old', 'current', 'other', or None when the pivot isn't there."""
    if not _has(mesh, name):
        return None
    att = attachment(mesh, name)
    q = rotation(att) if att is not None else None

    def near(frame):
        a = angle(q, frame) if q else None
        return a is not None and a <= FRAME_TOLERANCE

    if near(OLD_FRAME):
        return "old"
    if near(IDENTITY):
        return "current"
    return "other"


def pivots_at(mesh, frame) -> bool:
    for name in PIVOTS:
        att = attachment(mesh, name)
        q = rotation(att) if att is not None else None
        a = angle(q, frame) if q else None
        if a is None or a > SAME_ROTATION:
            return False
    return True


def stale_attachments(mesh, current) -> set[str]:
    """Root attachments a half-done migration left in the old frame: the game has
    an attachment of the same name that matches only after conversion."""
    out = set()
    for it in _items(mesh):
        name = it.get("key") if isinstance(it, dict) else None
        if not isinstance(name, str) or name in PIVOTS or not _has(current, name):
            continue
        att, game = attachment(mesh, name), attachment(current, name)
        q = rotation(att) if att is not None else None
        g = rotation(game) if game is not None else None
        if not q or not g:
            continue
        a_conv, a_raw = angle(convert(q), g), angle(q, g)
        if a_conv is not None and a_raw is not None and a_conv <= FRAME_TOLERANCE and a_raw > 2 * FRAME_TOLERANCE:
            out.add(name)
    return out


# ---------------------------------------------------------------------- root bone check

def _root_pose(model):
    sk = model.get("m_modelSkeleton") if isinstance(model, dict) else None
    if not isinstance(sk, dict):
        return None
    names, parents = sk.get("m_boneName"), sk.get("m_nParent")
    pos, rot = sk.get("m_bonePosParent"), sk.get("m_boneRotParent")
    scale = sk.get("m_boneScaleParent")
    if not all(isinstance(x, list) for x in (names, parents, pos, rot, scale)):
        return None
    if not (len(names) == len(parents) == len(pos) == len(rot) == len(scale)):
        return None
    if names.count("root_motion") != 1:
        return None
    i = names.index("root_motion")
    q = _vec(rot[i], 4)
    s = scale[i]
    if q is None or isinstance(s, bool) or not isinstance(s, (int, float)):
        return None
    return parents[i], float(s), q


def compatible_root(source_model, game_model) -> bool:
    a, b = _root_pose(source_model), _root_pose(game_model)
    if a is None or b is None:
        return False
    (pa, sa, qa), (pb, sb, qb) = a, b
    if pa != -1 or pb != -1 or sa <= 0 or sb <= 0 or abs(sa - sb) > 0.001:
        return False
    na, nb = _norm(qa), _norm(qb)
    if abs(na - 1) > 0.001 or abs(nb - 1) > 0.001:
        return False
    qa, qb = tuple(v / na for v in qa), tuple(v / nb for v in qb)
    dot = sum(x * y for x, y in zip(qa, qb))
    return 2.0 * math.acos(min(1.0, abs(dot))) <= ROOT_ANGLE_TOLERANCE


# ---------------------------------------------------------------------- the migration

def _edits_for(mesh, only: set[str] | None) -> tuple[dict, list[str]]:
    """Number edits that convert every root attachment (or just `only`)."""
    edits: dict[tuple, float] = {}
    changed: list[str] = []
    seen: set[str] = set()
    for i, it in enumerate(_items(mesh)):
        if not isinstance(it, dict) or not isinstance(it.get("key"), str):
            raise ValueError("unnamed attachment")
        name = it["key"]
        if only is not None and name not in only:
            continue
        if name in seen:
            raise ValueError("duplicate attachment names")
        seen.add(name)
        v = it.get("value")
        names = v.get("m_influenceNames") if isinstance(v, dict) else None
        if not isinstance(names, list) or "root_motion" not in names:
            continue
        if not _single_root(v):
            raise ValueError(f"“{name}” blends several bones; needs the mod author")
        q = rotation(v)
        if q is None or abs(_norm(q) - 1) > 0.001:
            raise ValueError(f"“{name}” has an invalid rotation")
        offs = v.get("m_vInfluenceOffsets")
        o = _vec(offs[0], 3) if isinstance(offs, list) and offs else None
        if o is None:
            raise ValueError(f"“{name}” has an invalid offset")
        x, y, z = o
        base = ("m_attachments", i, "value")
        for j, val in enumerate((z, x, y)):
            edits[base + ("m_vInfluenceOffsets", 0, j)] = val
        for j, val in enumerate(convert(q)):
            edits[base + ("m_vInfluenceRotations", 0, j)] = val
        changed.append(name)
    return edits, changed


def _model_data(res: Resource):
    raw = res.first("DATA")
    if raw is None:
        return None
    return kv3.decode(raw).value


def repair(source: bytes, game: bytes) -> Outcome:
    """Check one skin model against the installed game's model of the same path."""
    try:
        res = Resource(source)
        cur = Resource(game)
    except ResourceError as exc:
        return Outcome("skipped", f"not a readable model ({exc})")

    current_mesh = None
    for i in cur.indices("MDAT"):
        try:
            mesh = kv3.decode(cur.block(i)).value
        except kv3.Kv3Error:
            continue
        if pivots_at(mesh, IDENTITY):
            current_mesh = mesh
            break
    if current_mesh is None:
        return Outcome("ok", "the game's model doesn't use the new camera frame")

    migrations: list[tuple[int, set[str] | None]] = []
    for i in res.indices("MDAT"):
        try:
            mesh = kv3.decode(res.block(i)).value
        except kv3.Kv3Error as exc:
            return Outcome("skipped", f"mesh data unreadable ({exc})")
        frames = [f for f in (pivot_frame(mesh, n) for n in PIVOTS) if f is not None]
        old = frames.count("old")
        if old and old == len(frames):
            migrations.append((i, None))
        elif old:
            return Outcome("warning", "camera pivots use mixed frames; left as is")
        elif frames and all(f == "current" for f in frames):
            stale = stale_attachments(mesh, current_mesh)
            if stale:
                migrations.append((i, stale))
    if not migrations:
        return Outcome("ok")

    try:
        src_model, game_model = _model_data(res), _model_data(cur)
    except kv3.Kv3Error as exc:
        return Outcome("skipped", f"model data unreadable ({exc})")
    if not compatible_root(src_model, game_model):
        return Outcome("warning", "root_motion bone differs from the game's; left as is")

    replace: dict[int, bytes] = {}
    names: list[str] = []
    for index, only in migrations:
        raw = res.block(index)
        mesh = kv3.decode(raw).value
        try:
            edits, changed = _edits_for(mesh, only)
        except ValueError as exc:
            return Outcome("warning", f"{exc}; left as is")
        if not edits:
            continue
        try:
            patched = kv3.patch_numbers(raw, edits)
        except kv3.Unpatchable as exc:
            return Outcome("warning", f"can't change a value in place ({exc}); left as is")
        except kv3.Kv3Error as exc:
            return Outcome("skipped", str(exc))
        # Verify: decode what we wrote and compare every edited number (f32 lanes round).
        check = kv3.decode(patched)
        for path, want in edits.items():
            got = kv3.get(check.value, path)
            slot = check.slots.get(path)
            if slot is not None and slot.datatype == kv3.FLOAT:
                want = struct.unpack("<f", struct.pack("<f", want))[0]
            if not isinstance(got, float) or abs(got - want) > 1e-9 * max(1.0, abs(want)):
                return Outcome("warning", "fix failed its check; left as is")
        replace[index] = patched
        names += changed
    if not replace:
        return Outcome("ok")
    try:
        out = res.rebuild(replace)
    except ResourceError as exc:
        return Outcome("warning", f"{exc}; left as is")
    return Outcome("fixed", "camera and aim attachments moved to the current frame", data=out,
                   attachments=sorted(set(names)))


# ---------------------------------------------------------------------- across the load order

FIX_VERSION = 1           # bump when the repair changes, so cached results are redone
OVERLAY_UID = "__camera_fix__"


@dataclass
class ModelReport:
    path: str
    status: str               # "fixed" / "warning" / "skipped"
    detail: str = ""
    attachments: list[str] = field(default_factory=list)


@dataclass
class OverlayPlan:
    files: dict[str, bytes] = field(default_factory=dict)          # model path -> repaired bytes
    report: dict[str, list[ModelReport]] = field(default_factory=dict)  # mod uid -> findings

    @property
    def fixed_count(self) -> int:
        return len(self.files)


def _is_model(path: str) -> bool:
    return path.startswith("models/") and path.endswith(".vmdl_c") and ".." not in path


class Fixer:
    """Repairs the winning copy of every hero model the enabled mods replace.
    Results are cached by (model bytes, game model checksum), so applying again
    costs a hash per model."""

    def __init__(self, cache_dir, index):
        from pathlib import Path
        self.cache_dir = Path(cache_dir)
        self.index = index      # conflicts.VpkIndex

    def plan(self, mods, citadel) -> OverlayPlan:
        import hashlib
        import json
        from pathlib import Path

        from sapphire.vpk import VpkError, VpkReader

        out = OverlayPlan()
        game_vpk = Path(citadel) / "pak01_dir.vpk"
        try:
            game = VpkReader(game_vpk)
        except (OSError, VpkError) as exc:
            log.warning("camera fix: can't read the game's models (%s)", exc)
            return out
        winners: dict[str, tuple] = {}
        for mod in mods:
            if not mod.enabled:
                continue
            for vpk in mod.active_vpks:
                main = mod.file_path(vpk.main)
                for path in self.index.entries(main):
                    if _is_model(path) and path not in winners and path in game:
                        winners[path] = (mod, vpk)
        if not winners:
            return out
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        readers: dict = {}
        for path, (mod, vpk) in winners.items():
            key_files = tuple(mod.file_path(f) for f in vpk.files)
            try:
                reader = readers.get(key_files)
                if reader is None:
                    chunks = {int(f.chunk): mod.file_path(f) for f in vpk.files if f.chunk is not None}
                    reader = readers[key_files] = VpkReader(mod.file_path(vpk.main), chunks)
                source = reader.read(path)
                game_crc = game.entries[path].crc
            except (OSError, VpkError, KeyError) as exc:
                out.report.setdefault(mod.uid, []).append(ModelReport(path, "skipped", f"couldn't read it ({exc})"))
                continue
            key = hashlib.sha1(source + struct.pack("<II", game_crc, FIX_VERSION)).hexdigest()
            meta_file = self.cache_dir / f"{key}.json"
            data_file = self.cache_dir / f"{key}.vmdl_c"
            outcome = None
            try:
                meta = json.loads(meta_file.read_text())
                data = data_file.read_bytes() if meta["status"] == "fixed" else None
                outcome = Outcome(meta["status"], meta.get("detail", ""), data, meta.get("attachments", []))
            except (OSError, ValueError, KeyError):
                pass
            if outcome is None:
                try:
                    outcome = repair(source, game.read(path))
                except Exception as exc:  # noqa: BLE001 - one odd model must not stop applying
                    log.exception("camera fix crashed on %s", path)
                    outcome = Outcome("skipped", f"unexpected error ({exc.__class__.__name__})")
                try:
                    if outcome.data is not None:
                        data_file.write_bytes(outcome.data)
                    meta_file.write_text(json.dumps({"status": outcome.status, "detail": outcome.detail,
                                                     "attachments": outcome.attachments}))
                except OSError:
                    pass
            if outcome.status == "fixed" and outcome.data:
                out.files[path] = outcome.data
            if outcome.status in ("fixed", "warning"):
                out.report.setdefault(mod.uid, []).append(
                    ModelReport(path, outcome.status, outcome.detail, outcome.attachments))
            if outcome.status != "ok":
                log.info("camera fix %s %s: %s %s", mod.name, path, outcome.status, outcome.detail)
        return out
