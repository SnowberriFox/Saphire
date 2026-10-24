"""The first-person camera fix for skins made before Deadlock's camera update."""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

import pytest

from helpers import make_game, make_vpk
from kv3_build import (IDENT, OLD, Aux, F, Flagged, Typed, container, encode, mesh, model_data, point,
                       vmdl)
from sapphire import archive, camera_fix, kv3, vpk
from sapphire.core import Manager
from sapphire.gamebanana import GameBananaClient
from sapphire.library import Library
from sapphire.resource import Resource

HAZE = "models/heroes_wip/haze/haze.vmdl_c"


def attachments(model: bytes, block: int = 1) -> dict:
    m = kv3.decode(Resource(model).block(block)).value
    return {a["key"]: (tuple(round(v, 4) for v in a["value"]["m_vInfluenceOffsets"][0]),
                       tuple(round(v, 4) for v in a["value"]["m_vInfluenceRotations"][0]))
            for a in m["m_attachments"]}


# ---------------------------------------------------------------------- kv3 codec

@pytest.mark.parametrize("method", [0, 1, 2])
def test_kv3_decodes_every_lane_and_compression(method):
    root = {"i": 7, "f": F(1.5), "d": 2.25, "s": "hello", "zero": 0.0, "one": 1.0, "yes": True,
            "none": None, "flag": Flagged("materials/a.vmat"), "typed": Typed([F(1), F(2)], kv3.FLOAT),
            "aux": Aux([F(3), F(4)], kv3.FLOAT), "list": [1, "x", {"k": 5}], "nested": {"deep": {"v": 9.5}}}
    d = kv3.decode(encode(root, method))
    assert d.value == {"i": 7, "f": 1.5, "d": 2.25, "s": "hello", "zero": 0.0, "one": 1.0, "yes": True,
                       "none": None, "flag": "materials/a.vmat", "typed": [1.0, 2.0], "aux": [3.0, 4.0],
                       "list": [1, "x", {"k": 5}], "nested": {"deep": {"v": 9.5}}}
    assert d.slots[("f",)].datatype == kv3.FLOAT and d.slots[("d",)].datatype == kv3.DOUBLE
    assert d.slots[("zero",)].offset == -1          # tagless constant: no bytes
    assert ("aux", 1) in d.slots


def test_patch_changes_only_the_numbers():
    root = {"a": Typed([F(1), F(2), F(3)], kv3.FLOAT), "b": 4.5, "tag": Flagged("keep"), "z": 0.0}
    block = encode(root, 1)
    out = kv3.patch_numbers(block, {("a", 1): 20.0, ("b",): -1.25})
    assert kv3.decode(out).value == {"a": [1.0, 20.0, 3.0], "b": -1.25, "tag": "keep", "z": 0.0}
    before, after = kv3.working_copy(block), bytearray(out)
    diff = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
    # header fields flip to "uncompressed", and exactly 4 + 8 value bytes move at most
    assert all(i < 120 for i in diff[: len(diff) - 12]) and len(before) == len(after)
    assert struct.unpack_from("<I", out, 20)[0] == 0
    with pytest.raises(kv3.Unpatchable):
        kv3.patch_numbers(block, {("z",): 3.0})       # constant zero has no bytes to overwrite
    assert kv3.decode(kv3.patch_numbers(block, {("z",): 0.0})).value["z"] == 0.0
    with pytest.raises(kv3.Unpatchable):
        kv3.patch_numbers(block, {("missing",): 1.0})


def test_patch_keeps_a_blobbed_block_compressed():
    block = bytearray(encode({"v": 2.5, "w": Typed([F(1), F(2)], kv3.FLOAT)}, 1))
    struct.pack_into("<i", block, 56, 1)              # pretend it has a binary-blob section
    out = kv3.patch_numbers(bytes(block), {("v",): 9.0})
    assert struct.unpack_from("<I", out, 20)[0] == 1  # still LZ4
    assert kv3.decode(out).value == {"v": 9.0, "w": [1.0, 2.0]}


# ---------------------------------------------------------------------- the repair

@pytest.mark.parametrize("as_float", [True, False])
@pytest.mark.parametrize("method", [1, 2])
def test_old_frame_is_migrated_and_custom_offsets_kept(as_float, method):
    src = vmdl(OLD, as_float=as_float, method=method)
    out = camera_fix.repair(src, vmdl(IDENT))
    assert out.status == "fixed", out.detail
    assert out.attachments == ["aim", "crouching_pivot", "standing_pivot"]
    pts = attachments(out.data)
    assert pts["standing_pivot"] == ((-3.0, 2.0, 94.0), IDENT)
    assert pts["crouching_pivot"] == ((4.0, 1.0, 55.0), IDENT)
    assert pts["aim"] == ((6.0, 5.0, 70.0), IDENT)
    assert pts["custom_fx"] == ((7.0, 8.0, 9.0), OLD)           # hangs off the head: untouched
    old, new = Resource(src), Resource(out.data)
    assert new.block(0) == old.block(0) and new.block(2) == old.block(2)   # DATA, VBIB byte-identical
    assert kv3.decode(new.block(1)).value["m_material"] == "materials/x.vmat"
    assert camera_fix.repair(out.data, vmdl(IDENT)).status == "ok"         # idempotent


def test_authored_tweaks_near_the_old_frame_are_converted():
    tilt = (-0.47, -0.53, -0.5, 0.5)
    n = sum(v * v for v in tilt) ** 0.5
    tilt = tuple(v / n for v in tilt)
    extra = [point("near_00", "root_motion", (1.0, 2.0, 3.0), tilt)]
    out = camera_fix.repair(vmdl(OLD, extra=extra), vmdl(IDENT))
    assert out.status == "fixed"
    want = tuple(round(v, 4) for v in camera_fix.convert(tilt))
    assert attachments(out.data)["near_00"] == ((3.0, 1.0, 2.0), want)


def test_every_mesh_block_is_fixed():
    out = camera_fix.repair(vmdl(OLD, meshes=2), vmdl(IDENT))
    assert out.status == "fixed"
    assert attachments(out.data, 1)["aim"] == attachments(out.data, 2)["aim"] == ((6.0, 5.0, 70.0), IDENT)


def test_nothing_to_do_cases():
    assert camera_fix.repair(vmdl(IDENT), vmdl(IDENT)).status == "ok"      # skin already current
    assert camera_fix.repair(vmdl(OLD), vmdl(OLD)).status == "ok"          # game not updated
    assert camera_fix.repair(b"not a model", vmdl(IDENT)).status == "skipped"


def _custom(model_root, meshes) -> bytes:
    return container([("DATA", encode(model_root)), *[("MDAT", encode(m)) for m in meshes]])


def test_unsafe_models_are_left_alone():
    game = vmdl(IDENT)
    # one pivot old, one current
    m = mesh(OLD)
    m["m_attachments"][1] = point("crouching_pivot", "root_motion", (1.0, 55.0, 4.0), IDENT)
    assert camera_fix.repair(_custom(model_data(), [m]), game).status == "warning"
    # root bone rotated differently from the game's
    bad_root = model_data(root_rot=(0.0, 0.0, 0.7071068, 0.7071068))
    assert camera_fix.repair(_custom(bad_root, [mesh(OLD)]), game).status == "warning"
    # an attachment blended over two bones
    m = mesh(OLD)
    m["m_attachments"][2]["value"]["m_nInfluences"] = 2
    m["m_attachments"][2]["value"]["m_influenceNames"] = Typed(["root_motion", "pelvis", ""], kv3.STRING)
    assert camera_fix.repair(_custom(model_data(), [m]), game).status == "warning"
    # duplicate names
    m = mesh(OLD)
    m["m_attachments"].append(point("aim", "root_motion", (1.0, 1.0, 1.0), OLD))
    assert camera_fix.repair(_custom(model_data(), [m]), game).status == "warning"


def test_value_stored_as_a_constant_is_a_warning_not_a_broken_file():
    # plain (untyped) arrays let zeros be tagless constants; moving one isn't possible in place
    m = mesh(OLD)
    m["m_attachments"][0]["value"]["m_vInfluenceOffsets"][0] = [0.0, 94.0, 2.0]
    out = camera_fix.repair(_custom(model_data(), [m]), vmdl(IDENT))
    assert out.status == "warning" and out.data is None


def test_half_migrated_skin_finishes_the_job():
    # pivots already current, but `aim` still in the old frame while the game has an `aim`
    m = mesh(IDENT)
    m["m_attachments"][2] = point("aim", "root_motion", (5.0, 70.0, 6.0), OLD)
    game = _custom(model_data(), [mesh(IDENT)])
    out = camera_fix.repair(_custom(model_data(), [m]), game)
    assert out.status == "fixed" and out.attachments == ["aim"]
    pts = attachments(out.data)
    assert pts["aim"] == ((6.0, 5.0, 70.0), IDENT)
    assert pts["standing_pivot"] == ((2.0, 94.0, -3.0), IDENT)   # already right: untouched


# ---------------------------------------------------------------------- vpk + apply

def chunked_vpk(folder: Path, files: dict[str, bytes]) -> Path:
    """A game-style pak01_dir.vpk whose data sits in pak01_000.vpk."""
    folder.mkdir(parents=True, exist_ok=True)
    data = bytearray()
    tree = bytearray()
    groups: dict = {}
    for p, b in files.items():
        d, _, f = p.rpartition("/")
        name, _, ext = f.rpartition(".")
        groups.setdefault(ext, {}).setdefault(d, []).append((name, b))
    for ext, dirs in groups.items():
        tree += ext.encode() + b"\0"
        for d, items in dirs.items():
            tree += d.encode() + b"\0"
            for name, b in items:
                tree += name.encode() + b"\0" + struct.pack("<IHHIIH", 0, 0, 0, len(data), len(b), 0xFFFF)
                data += b
            tree += b"\0"
        tree += b"\0"
    tree += b"\0"
    (folder / "pak01_dir.vpk").write_bytes(struct.pack("<IIIIIII", 0x55AA1234, 2, len(tree), 0, 0, 0, 0) + tree)
    (folder / "pak01_000.vpk").write_bytes(bytes(data))
    return folder / "pak01_dir.vpk"


def test_vpk_reader_reads_chunks_preload_and_embedded(tmp_path):
    g = chunked_vpk(tmp_path / "g", {HAZE: b"chunked-bytes"})
    assert vpk.VpkReader(g).read(HAZE) == b"chunked-bytes"
    p = make_vpk(tmp_path / "m" / "mod.vpk", {HAZE: b"preloaded"})
    assert vpk.VpkReader(p).read(HAZE) == b"preloaded"
    vpk.write_vpk(tmp_path / "o" / "pak01_dir.vpk", {HAZE: b"embedded", "scripts/a.txt": b"t"})
    r = vpk.VpkReader(tmp_path / "o" / "pak01_dir.vpk")
    assert r.read(HAZE) == b"embedded" and r.read("scripts/a.txt") == b"t"
    assert sorted(vpk.list_entries(tmp_path / "o" / "pak01_dir.vpk")) == ["models/heroes_wip/haze/haze.vmdl_c", "scripts/a.txt"]


class NoGB(GameBananaClient):
    pass


@pytest.fixture
def game_with_haze(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "find_7z", lambda: None)
    game = make_game(tmp_path / "lib")
    chunked_vpk(game / "game" / "citadel", {HAZE: vmdl(IDENT)})
    mgr = Manager(Library(), NoGB())
    mgr.set_game_dir(game)
    return mgr, game, tmp_path


def test_apply_deploys_the_overlay_ahead_of_the_mods(game_with_haze, monkeypatch):
    mgr, game, tmp = game_with_haze
    old_skin = mgr.install_local(make_vpk(tmp / "src" / "old_haze.vpk", {HAZE: vmdl(OLD), "ui/x.txt": b"x"}))
    other = mgr.install_local(make_vpk(tmp / "src" / "sounds.vpk", {"sounds/a.vsnd_c": b"s"}))
    mgr.apply()
    addons = game / "game" / "citadel" / "addons"
    assert sorted(p.name for p in addons.iterdir()) == ["pak01_dir.vpk", "pak02_dir.vpk", "pak03_dir.vpk"]
    overlay = vpk.VpkReader(addons / "pak01_dir.vpk")
    assert list(overlay.entries) == [HAZE]
    assert attachments(overlay.read(HAZE))["standing_pivot"] == ((-3.0, 2.0, 94.0), IDENT)
    # the mod's own file is untouched
    assert attachments(vpk.VpkReader(mgr.lib.mods[old_skin.uid].file_path(old_skin.vpks[0].main)).read(HAZE)
                       )["standing_pivot"] == ((2.0, 94.0, -3.0), OLD)
    rep = mgr.camera_report[old_skin.uid]
    assert [(r.path, r.status) for r in rep] == [(HAZE, "fixed")] and other.uid not in mgr.camera_report

    # applying again reuses the cached result
    monkeypatch.setattr(camera_fix, "repair", lambda *a: pytest.fail("should use the cache"))
    mgr.apply()
    assert (addons / "pak01_dir.vpk").is_file()

    # switching the fix off removes the overlay and the mods move up
    mgr.lib.settings.fix_camera = False
    mgr.apply()
    assert sorted(p.name for p in addons.iterdir()) == ["pak01_dir.vpk", "pak02_dir.vpk"]
    assert HAZE in vpk.list_entries(addons / "pak02_dir.vpk") and mgr.camera_report == {}   # sounds is #1


def test_only_the_winning_copy_is_repaired(game_with_haze):
    mgr, game, tmp = game_with_haze
    a = mgr.install_local(make_vpk(tmp / "src" / "a.vpk", {HAZE: vmdl(OLD)}))
    b = mgr.install_local(make_vpk(tmp / "src" / "b.vpk", {HAZE: vmdl(IDENT)}))   # newest install: on top, wins
    mgr.apply()
    assert mgr.camera_report == {}                     # the winner is already current
    assert len(list((game / "game" / "citadel" / "addons").iterdir())) == 2
    mgr.set_order([a.uid, b.uid])
    mgr.apply()
    assert list(mgr.camera_report) == [a.uid]


def test_no_game_models_means_no_overlay(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "find_7z", lambda: None)
    game = make_game(tmp_path / "lib")      # no pak01_dir.vpk at all
    mgr = Manager(Library(), NoGB())
    mgr.set_game_dir(game)
    mgr.install_local(make_vpk(tmp_path / "src" / "old.vpk", {HAZE: vmdl(OLD)}))
    mgr.apply()
    assert [p.name for p in (game / "game" / "citadel" / "addons").iterdir()] == ["pak01_dir.vpk"]
