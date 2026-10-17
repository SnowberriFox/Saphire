import hashlib
import json
from pathlib import Path

import pytest
from helpers import make_game, make_vpk

from sapphire import archive, identify, importers
from sapphire.core import Manager
from sapphire.gamebanana import Details, GameBananaClient, GBFile, Submission
from sapphire.library import Library


# --------------------------------------------------------------- fixtures

class FakeGB(GameBananaClient):
    """Answers details() from a dict and 'downloads' by writing a zip of VPKs."""

    def __init__(self, subs: dict[int, Submission], files: dict[int, list[GBFile]], zips: dict[int, Path]):
        super().__init__()
        self.subs, self.file_lists, self.zips = subs, files, zips

    def details(self, model, mod_id):
        return Details(submission=self.subs[mod_id], files=self.file_lists.get(mod_id, []))

    def files(self, model, mod_id):
        return self.file_lists.get(mod_id, [])

    def download(self, file, dest_dir, progress=None, cancel=None):
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / file.filename
        out.write_bytes(self.zips[file.id].read_bytes())
        return out


@pytest.fixture
def no7z(monkeypatch):
    monkeypatch.setattr(archive, "find_7z", lambda: None)


def make_dmm(home: Path, cache_mods: dict[str, dict[str, bytes]]) -> Path:
    """A fake DMM install: state.json with two profiles and a download cache."""
    data = home / ".local/share" / importers.DMM_ID
    for rid, files in cache_mods.items():
        make_vpk(data / "mods" / rid / "files" / "pak01_dir.vpk", files)
    mods = [
        {"remoteId": "111", "name": "Haze Noir", "author": "velvet", "category": "Skins", "installOrder": 1,
         "selectedDownloads": [{"url": "https://gamebanana.com/dl/9111", "name": "haze_noir.zip"}],
         "images": ["https://images.gamebanana.com/img/ss/mods/a.jpg"]},
        {"remoteId": "222", "name": "Clean HUD", "author": "ink", "category": "HUD", "installOrder": 0,
         "selectedDownloads": [{"url": "gamebanana-file://222/9222", "name": "clean_hud.zip"}],
         "installedFileTree": {"files": [{"name": "pak01_dir.vpk", "is_selected": True}]}},
        {"remoteId": "snd-333", "name": "Orb Sounds", "installOrder": 2,
         "selectedDownloads": [{"url": "https://gamebanana.com/dl/9333", "name": "orbs.zip"}]},
        {"remoteId": "local-0f0f0f0f-0000-4000-8000-000000000000", "name": "My local thing", "installOrder": 3},
    ]
    state = {"localMods": mods, "activeProfileId": "p1",
             "profiles": {"p1": {"name": "Main", "isDefault": True, "mods": mods,
                                 "enabledMods": {"111": {"enabled": True}, "222": {"enabled": True},
                                                 "snd-333": {"enabled": False}}},
                          "p2": {"name": "Quiet", "mods": mods,
                                 "enabledMods": {"111": {"enabled": True}, "222": {"enabled": False},
                                                 "snd-333": {"enabled": False}}}}}
    data.mkdir(parents=True, exist_ok=True)
    (data / "state.json").write_text(json.dumps({"local-config": json.dumps({"state": state, "version": 12})}))
    return data


def make_grimoire(home: Path, game: Path) -> Path:
    data = home / ".config" / "Grimoire"
    citadel = game / "game" / "citadel"
    make_vpk(citadel / "addons" / "pak01_dir.vpk", {"models/haze.vmdl_c": b"a"})
    make_vpk(citadel / "addons" / "pak02_dir.vpk", {"models/haze_gold.vmdl_c": b"b"})   # variant of same mod
    make_vpk(citadel / "addons" / "pak03_dir.vpk", {"hud/x.vxml_c": b"c"})
    make_vpk(citadel / "addons1" / "pak01_dir.vpk", {"sounds/y.vsnd_c": b"d"})
    make_vpk(citadel / "addons" / ".disabled" / "old_skin.vpk", {"models/old.vmdl_c": b"e"})
    make_vpk(citadel / "grimoire" / "pak01_dir.vpk", {"locker.txt": b"L"})              # reserved, skipped
    meta = {
        "pak01_dir.vpk": {"modName": "Haze Noir", "author": "velvet", "gameBananaId": 111, "gameBananaFileId": 9111,
                          "categoryName": "Haze", "archiveVpkPath": "Base/pak01_dir.vpk", "vpkIndex": 0},
        "pak02_dir.vpk": {"modName": "Haze Noir", "author": "velvet", "gameBananaId": 111, "gameBananaFileId": 9111,
                          "categoryName": "Haze", "archiveVpkPath": "Gold/pak01_dir.vpk", "vpkIndex": 1},
        "pak03_dir.vpk": {"modName": "Clean HUD", "gameBananaId": 222, "gameBananaFileId": 9222},
        "addons1/pak01_dir.vpk": {"modName": "Orb Sounds", "gameBananaId": 333, "sourceSection": "Sound"},
        "old_skin.vpk": {"modName": "Old skin"},
        "grimoire/pak01_dir.vpk": {"lockerCosmetics": {"x": 1}},
    }
    data.mkdir(parents=True)
    (data / "mod-metadata.json").write_text(json.dumps(meta))
    (data / "settings.json").write_text(json.dumps({"deadlockPath": str(game)}))
    (data / "profiles.json").write_text(json.dumps([
        {"id": "a", "name": "Everything", "mods": [
            {"fileName": "pak03_dir.vpk", "enabled": True, "priority": 0, "gameBananaId": 222, "gameBananaFileId": 9222},
            {"fileName": "pak01_dir.vpk", "enabled": True, "priority": 1, "gameBananaId": 111, "gameBananaFileId": 9111},
            {"fileName": "old_skin.vpk", "enabled": True, "priority": 2},
        ]},
    ]))
    return data


# ------------------------------------------------------------------ DMM

def test_read_dmm(tmp_path):
    home = tmp_path / "home"
    make_dmm(home, {"111": {"models/haze.vmdl_c": b"a"}, "snd-333": {"sounds/orb.vsnd_c": b"s"}})
    plan = importers.read_dmm(home=home)
    assert plan.location == home / ".local/share" / importers.DMM_ID
    by = {m.key: m for m in plan.mods}
    assert [m.key for m in plan.mods] == ["222", "111", "snd-333", "local-0f0f0f0f-0000-4000-8000-000000000000"]
    assert by["111"].vpks and by["111"].gb_id == 111 and by["111"].file_id == 9111 and by["111"].enabled
    assert by["snd-333"].model == "Sound" and by["snd-333"].gb_id == 333 and not by["snd-333"].enabled
    assert not by["222"].vpks and by["222"].can_download and by["222"].file_id == 9222
    assert by["222"].wanted_names == ["pak01_dir.vpk"]
    assert [p.name for p in plan.profiles] == ["Main", "Quiet"]
    assert dict(plan.profiles[1].entries)["222"] is False
    assert [m.key for m in plan.skipped] == ["local-0f0f0f0f-0000-4000-8000-000000000000"]


def test_import_dmm_end_to_end(tmp_path, no7z):
    home = tmp_path / "home"
    make_dmm(home, {"111": {"models/haze.vmdl_c": b"a"}, "snd-333": {"sounds/orb.vsnd_c": b"s"}})
    game = make_game(tmp_path / "lib")
    # the HUD mod has to be re-downloaded: build its zip with two variants
    import zipfile
    z = tmp_path / "hud.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for v in ("pak01_dir.vpk", "alt_pak01_dir.vpk"):
            zf.write(make_vpk(tmp_path / "b" / v, {"hud/x.vxml_c": v.encode()}), v)
    subs = {222: Submission(id=222, model="Mod", name="Clean HUD (live name)", author="ink",
                            root_category="HUD", sub_category="Interface")}
    gb = FakeGB(subs, {222: [GBFile(id=9222, filename="clean_hud.zip", date_added=5)]}, {9222: z})
    mgr = Manager(Library(), gb)
    mgr.set_game_dir(game)
    plan = importers.read_dmm(home=home)
    asked = []
    res = mgr.run_import(plan, choose=lambda s, n: asked.append(n) or s)
    assert res == {"imported": 3, "downloaded": 1, "failed": 0, "profiles": 2}
    assert asked == []                                   # wanted_names picked the variant silently
    assert set(mgr.lib.mods) == {"gb-Mod-111", "gb-Mod-222", "gb-Sound-333"}
    hud = mgr.lib.mods["gb-Mod-222"]
    assert hud.name == "Clean HUD (live name)" and [v.label for v in hud.vpks] == ["pak01_dir.vpk"]
    assert mgr.lib.order == ["gb-Mod-222", "gb-Mod-111", "gb-Sound-333"]   # DMM installOrder
    assert mgr.lib.mods["gb-Sound-333"].enabled is False
    assert set(mgr.lib.profiles) == {"Main", "Quiet"}
    assert dict(mgr.lib.profiles["Quiet"].entries) == {"gb-Mod-111": True, "gb-Mod-222": False, "gb-Sound-333": False}
    mgr.apply()
    names = sorted(p.name for p in (game / "game/citadel/addons").iterdir())
    assert names == ["pak01_dir.vpk", "pak02_dir.vpk"]


# ------------------------------------------------------------- Grimoire

def test_read_and_import_grimoire(tmp_path, no7z):
    home = tmp_path / "home"
    game = make_game(tmp_path / "lib")
    make_grimoire(home, game)
    plan = importers.read_grimoire(game, home=home)
    assert plan.source == "Grimoire" and not plan.warnings
    keys = [m.key for m in plan.mods]
    assert keys == ["Mod-111-9111", "Mod-222-9222", "Sound-333", "file-old_skin.vpk"]
    haze = plan.mods[0]
    assert [v.label for v in haze.vpks] == ["Base/pak01_dir.vpk", "Gold/pak01_dir.vpk"]
    assert plan.mods[2].model == "Sound" and plan.mods[2].enabled
    assert plan.mods[3].enabled is False and plan.mods[3].name == "Old skin"
    assert plan.profiles[0].entries == [("Mod-222-9222", True), ("Mod-111-9111", True), ("file-old_skin.vpk", True)]

    gb = FakeGB({}, {}, {})
    mgr = Manager(Library(), gb)
    mgr.set_game_dir(game)
    res = mgr.run_import(plan)
    assert res["imported"] == 4 and res["downloaded"] == 0 and res["profiles"] == 1
    assert mgr.lib.order == ["gb-Mod-111", "gb-Mod-222", "gb-Sound-333", "local-import-file-old_skin.vpk"]
    assert mgr.lib.mods["gb-Mod-111"].file_id == 9111 and len(mgr.lib.mods["gb-Mod-111"].vpks) == 2
    assert mgr.lib.mods["local-import-file-old_skin.vpk"].enabled is False
    mgr.apply()   # Grimoire's gameinfo edits would be cleaned; its .disabled folder is left alone
    assert (game / "game/citadel/addons/.disabled/old_skin.vpk").exists()
    names = sorted(p.name for p in (game / "game/citadel/addons").iterdir() if p.is_file())
    assert names == ["pak01_dir.vpk", "pak02_dir.vpk", "pak03_dir.vpk", "pak04_dir.vpk"]


def test_grimoire_gameinfo_search_path_is_cleaned():
    from helpers import VANILLA
    from sapphire import gameinfo
    text = VANILLA.read_bytes().decode().replace(
        "\t\t\tGame\t\t\t\tcitadel\r\n",
        "\t\t\tGame\t\t\t\tcitadel/grimoire\r\n\t\t\tGame\t\t\t\tcitadel/addons\r\n\t\t\tGame\t\t\t\tcitadel\r\n")
    assert gameinfo.inspect(text).foreign
    out = gameinfo.patch(text, ["citadel/addons"])
    assert "citadel/grimoire" not in out
    assert sum(1 for l in out.splitlines() if l.split() == ["Game", "citadel/addons"]) == 1


# ------------------------------------------------------------- identify

def test_fingerprint_matches_dmm_algorithm(tmp_path):
    v = make_vpk(tmp_path / "x.vpk", {"models/a.vmdl_c": b"hello", "Thumbs.db": b"junk"})
    fp = identify.fingerprint(v)
    assert fp.sha256 == hashlib.sha256(v.read_bytes()).hexdigest()
    import zlib
    from sapphire.vpk import read_entries
    e = next(e for e in read_entries(v) if e.path == "models/a.vmdl_c")
    expect = hashlib.sha256(f"models/a.vmdl_c\x00{e.length}\x00{e.crc:08x}".encode()).hexdigest()
    assert fp.content_signature == expect       # junk file excluded, single tuple
    assert fp.size == v.stat().st_size


def test_identify_rekeys_local_mod(tmp_path, no7z, monkeypatch):
    game = make_game(tmp_path / "lib")
    subs = {777: Submission(id=777, model="Mod", name="Found Skin", author="who", root_category="Skins",
                            sub_category="Ivy", url="https://gamebanana.com/mods/777",
                            thumb_url="https://images.gamebanana.com/img/ss/mods/t.jpg")}
    gb = FakeGB(subs, {777: [GBFile(id=5001, filename="found_v3.zip", date_added=50)]}, {})
    mgr = Manager(Library(), gb)
    mgr.set_game_dir(game)
    local_uid = mgr.install_local(make_vpk(tmp_path / "mystery_skin.vpk", {"models/ivy.vmdl_c": b"i"})).uid
    mgr.save_profile("mine")

    calls = []

    class FakeResp:
        status_code = 200

        def json(self):
            return [{"matchedVpk": {"id": "v1", "submissionType": "mod", "submissionId": "777", "fileId": "5001",
                                    "sourcePath": "Green/pak01_dir.vpk",
                                    "mod": {"remoteId": "777", "name": "Found Skin", "author": "who"}},
                     "match": {"certainty": 100, "matchType": "sha256"}}]

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return FakeResp()
    monkeypatch.setattr(mgr.identifier.session, "post", fake_post)

    results = mgr.identify()
    assert len(calls) == 1 and calls[0][0] == identify.API
    assert set(calls[0][1]) == {"sha256", "contentSignature", "fileSize"}
    assert results[0][1].gb_id == 777 and results[0][1].file_id == 5001
    assert local_uid not in mgr.lib.mods and "gb-Mod-777" in mgr.lib.mods
    mod = mgr.lib.mods["gb-Mod-777"]
    assert mod.source == "gamebanana" and mod.name == "Found Skin" and mod.file_id == 5001
    assert mod.file_name == "found_v3.zip" and mod.category == "Skins › Ivy"
    assert mod.folder.exists() and mod.file_path(mod.vpks[0].main).exists()
    assert mgr.lib.profiles["mine"].entries == [("gb-Mod-777", True)]
    assert mgr.check_updates() == []               # same file id -> no bogus update
    # second run hits the cache, no network
    mgr.identify()
    assert len(calls) == 1
    mgr.apply()
    assert (game / "game/citadel/addons/pak01_dir.vpk").exists()


def test_identify_no_match_and_errors(tmp_path, no7z, monkeypatch):
    game = make_game(tmp_path / "lib")
    mgr = Manager(Library(), FakeGB({}, {}, {}))
    mgr.set_game_dir(game)
    mgr.install_local(make_vpk(tmp_path / "nobody_knows.vpk", {"a": b"1"}))

    class Empty:
        status_code = 200

        def json(self):
            return []
    monkeypatch.setattr(mgr.identifier.session, "post", lambda *a, **k: Empty())
    assert mgr.identify()[0][1] is None
    assert list(mgr.lib.mods)[0].startswith("local-")

    import requests
    mgr.identifier._cache.clear()

    def boom(*a, **k):
        raise requests.ConnectionError()
    monkeypatch.setattr(mgr.identifier.session, "post", boom)
    with pytest.raises(identify.IdentifyError):
        mgr.identify()


def test_apply_adopts_grimoire_files_with_their_names(tmp_path, no7z):
    """Skip the importer, just hit Apply: Grimoire's live files keep their identity."""
    home = tmp_path / "home"
    game = make_game(tmp_path / "lib")
    make_grimoire(home, game)
    mgr = Manager(Library(), FakeGB({}, {}, {}))
    mgr.set_game_dir(game)
    mgr.apply()
    names = {m.uid: m.name for m in mgr.lib.mods.values()}
    assert names == {"gb-Mod-111": "Haze Noir", "gb-Mod-222": "Clean HUD", "gb-Sound-333": "Orb Sounds"}
    assert len(mgr.lib.mods["gb-Mod-111"].vpks) == 2
    assert mgr.lib.mods["gb-Mod-111"].file_id == 9111
    assert all(m.enabled for m in mgr.lib.mods.values())
    assert [m.uid for m in mgr.lib.ordered()] == ["gb-Mod-111", "gb-Mod-222", "gb-Sound-333"]
    files = sorted(p.name for p in (game / "game/citadel/addons").iterdir() if p.is_file())
    assert files == ["pak01_dir.vpk", "pak02_dir.vpk", "pak03_dir.vpk", "pak04_dir.vpk"]
    assert not (game / "game/citadel/addons1").exists()
    # a second apply changes nothing
    assert mgr.apply().written == 0 and len(mgr.lib.mods) == 3


def test_apply_adopts_dmm_live_files(tmp_path, no7z):
    home = tmp_path / "home"
    make_dmm(home, {})
    game = make_game(tmp_path / "lib")
    citadel = game / "game" / "citadel"
    make_vpk(citadel / "addons" / "pak01_dir.vpk", {"models/haze.vmdl_c": b"a"})
    make_vpk(citadel / "addons" / "pak02_dir.vpk", {"hud/x": b"b"})
    (citadel / "addons" / ".dmm.json").write_text(json.dumps({"version": 3, "mods": {
        "111": {"enabled": True, "currentVpks": ["pak01_dir.vpk"], "order": 1},
        "222": {"enabled": True, "currentVpks": ["pak02_dir.vpk"], "order": 0}}}))
    mgr = Manager(Library(), FakeGB({}, {}, {}))
    mgr.set_game_dir(game)
    mgr.apply()
    names = {m.uid: m.name for m in mgr.lib.mods.values()}
    assert names == {"gb-Mod-111": "Haze Noir", "gb-Mod-222": "Clean HUD"}
    assert mgr.lib.mods["gb-Mod-222"].file_id == 9222


def test_identify_drops_duplicate_of_known_mod(tmp_path, no7z, monkeypatch):
    game = make_game(tmp_path / "lib")
    subs = {777: Submission(id=777, model="Mod", name="Found Skin")}
    mgr = Manager(Library(), FakeGB(subs, {777: [GBFile(id=5001, filename="f.zip")]}, {}))
    mgr.set_game_dir(game)
    v = make_vpk(tmp_path / "skin.vpk", {"models/ivy.vmdl_c": b"same"})
    first = mgr.install_local(v)
    mgr._adopt_match(first, identify.Match(model="Mod", gb_id=777, file_id=5001, certainty=100, match_type="sha256"))
    dup = mgr.install_local(make_vpk(tmp_path / "copy" / "skin_copy.vpk", {"models/ivy.vmdl_c": b"same"}))
    dup_uid = dup.uid

    class R:
        status_code = 200

        def json(self):
            return [{"matchedVpk": {"submissionType": "mod", "submissionId": "777", "fileId": "5001"},
                     "match": {"certainty": 100, "matchType": "sha256"}}]
    monkeypatch.setattr(mgr.identifier.session, "post", lambda *a, **k: R())
    mgr.identify()
    assert dup_uid not in mgr.lib.mods and list(mgr.lib.mods) == ["gb-Mod-777"]
