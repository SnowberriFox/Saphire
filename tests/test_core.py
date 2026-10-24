import json
import zipfile
from pathlib import Path

import pytest
from helpers import make_game, make_vpk

from sapphire import archive, deploy, gameinfo, steam, vpk
from sapphire.core import GameRunning, Manager
from sapphire.gamebanana import Details, GameBananaClient, GBFile, Submission, parse_url
from sapphire.library import Library


# ------------------------------------------------------------------------ vpk

def test_vpk_listing_v1_and_v2(tmp_path):
    files = {"models/heroes/haze/haze.vmdl_c": b"x" * 10, "panorama/images/hud.png": b"y",
             "readme": b"z"}
    for v in (1, 2):
        p = make_vpk(tmp_path / f"v{v}.vpk", files, version=v)
        assert sorted(vpk.list_entries(p)) == sorted(files)
    (tmp_path / "bad.vpk").write_bytes(b"nope")
    with pytest.raises(vpk.VpkError):
        vpk.list_entries(tmp_path / "bad.vpk")


def test_find_sets_groups_chunks(tmp_path):
    make_vpk(tmp_path / "Blue" / "pak01_dir.vpk", {"a.txt": b"1"})
    (tmp_path / "Blue" / "pak01_000.vpk").write_bytes(b"data")
    make_vpk(tmp_path / "Red" / "pak01_dir.vpk", {"a.txt": b"2"})
    (tmp_path / "Red" / "notes.txt").write_text("hi")
    sets = vpk.find_sets(tmp_path)
    assert [s.rel for s in sets] == ["Blue/pak01_dir.vpk", "Red/pak01_dir.vpk"]
    assert [c.name for c in sets[0].chunks] == ["pak01_000.vpk"]


# ---------------------------------------------------------------------- steam

def test_finds_flatpak_steam_on_second_library(tmp_path):
    home = tmp_path / "h"
    root = home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    lib2 = tmp_path / "games"
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n'
        '\t\t"apps"\n\t\t{\n\t\t\t"1422450"\t\t"123"\n\t\t}\n\t}\n}\n' % (root, lib2))
    (lib2 / "steamapps").mkdir(parents=True)
    (lib2 / "steamapps" / "appmanifest_1422450.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"1422450"\n\t"installdir"\t\t"Deadlock"\n}\n')
    game = make_game(lib2 / "steamapps" / "common")
    assert steam.find_deadlock(home) == game


def test_finds_snap_steam(tmp_path):
    home = tmp_path / "h"
    root = home / "snap/steam/common/.local/share/Steam"
    game = make_game(root / "steamapps" / "common")
    assert steam.find_deadlock(home) == game


def test_running_detection_real_function(tmp_path):
    import importlib
    real = importlib.reload(steam).is_game_running
    proc = tmp_path / "proc"
    (proc / "1").mkdir(parents=True)
    (proc / "1" / "cmdline").write_bytes(b"python3\0sapphire\0")
    assert real(proc) is False
    (proc / "2").mkdir()
    (proc / "2" / "cmdline").write_bytes(b"Z:\\steam\\common\\Deadlock\\game\\bin\\win64\\deadlock.exe\0-dx11\0")
    assert real(proc) is True


# -------------------------------------------------------------------- archive

def test_zip_slip_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "find_7z", lambda: None)
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../evil.txt", "boom")
    with pytest.raises(archive.ArchiveError):
        archive.extract(z, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_7z_and_nested_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "find_7z", lambda: None)
    import py7zr
    v = make_vpk(tmp_path / "src" / "pak01_dir.vpk", {"a.txt": b"1"})
    seven = tmp_path / "m.7z"
    with py7zr.SevenZipFile(seven, "w") as zf:
        zf.write(v, "inner/pak01_dir.vpk")
    out = archive.extract(seven, tmp_path / "o1")
    assert [s.rel for s in vpk.find_sets(out)] == ["inner/pak01_dir.vpk"]
    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.write(v, "pak01_dir.vpk")
    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as zf:
        zf.write(inner, "inner.zip")
    out = archive.extract(outer, tmp_path / "o2")
    assert len(vpk.find_sets(out)) == 1


def test_bundled_7z_if_present(tmp_path):
    import shutil
    tool = archive.find_7z()
    if not tool:
        pytest.skip("no 7-Zip binary here")
    v = make_vpk(tmp_path / "pak01_dir.vpk", {"a.txt": b"1"})
    z = tmp_path / "m.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(v, "Variant A/pak01_dir.vpk")
    out = archive.extract(z, tmp_path / "o")
    assert [s.rel for s in vpk.find_sets(out)] == ["Variant A/pak01_dir.vpk"]


# ------------------------------------------------------------------ gamebanana

def test_parse_url():
    assert parse_url("https://gamebanana.com/mods/649307") == ("Mod", 649307)
    assert parse_url("gamebanana.com/sounds/12") == ("Sound", 12)
    assert parse_url("https://example.com") is None


def test_browse_drops_other_games(monkeypatch):
    c = GameBananaClient()
    payload = {"_aMetadata": {"_nRecordCount": 2, "_bIsComplete": True},
               "_aRecords": [
                   {"_idRow": 1, "_sModelName": "Mod", "_sName": "Haze skin",
                    "_aGame": {"_idRow": 20948}, "_aRootCategory": {"_sName": "Skins"},
                    "_aSubCategory": {"_sName": "Haze"}, "_nLikeCount": 5,
                    "_aPreviewMedia": {"_aImages": [{"_sBaseUrl": "https://images.gamebanana.com/img/ss/mods",
                                                     "_sFile": "a.jpg", "_sFile530": "530-90_a.jpg"}]},
                    "_aSubmitter": {"_idRow": 9, "_sName": "Artist &amp; Co"}},
                   {"_idRow": 2, "_sModelName": "Mod", "_sName": "CS map", "_aGame": {"_idRow": 4254}},
               ]}
    seen = {}

    def fake_get(path, params=None, ttl=0):
        seen["path"], seen["params"] = path, params
        return payload
    monkeypatch.setattr(c, "_get", fake_get)
    page = c.browse(sort="popular", category_id=33)
    assert [s.name for s in page.items] == ["Haze skin"]
    s = page.items[0]
    assert s.author == "Artist & Co" and s.category_label == "Skins › Haze"
    assert s.thumb_url.endswith("530-90_a.jpg")
    assert seen["path"] == "Mod/Index"
    assert seen["params"]["_aFilters[Generic_Category]"] == 33
    assert seen["params"]["_sSort"] == "Generic_MostLiked"
    # Searching keeps the category and sort (row 27): it's the same Index call
    # with a name filter, and commas (which end the filter value) become spaces.
    c.browse(search="  gold,  haze ", category_id=33, sort="popular")
    assert seen["path"] == "Mod/Index"
    assert seen["params"]["_aFilters[Generic_Name]"] == "contains,gold haze"
    assert seen["params"]["_aFilters[Generic_Category]"] == 33
    assert seen["params"]["_sSort"] == "Generic_MostLiked"


# --------------------------------------------------------------- full manager

class FakeGB(GameBananaClient):
    """Serves mod downloads from local zip files instead of the internet."""

    def __init__(self, zips: dict[int, list[tuple[GBFile, Path]]]):
        super().__init__()
        self.zips = zips

    def details(self, model, mod_id):
        files = [f for f, _ in self.zips[mod_id]]
        sub = Submission(id=mod_id, model=model, name=f"Mod {mod_id}", author="someone",
                         root_category="Skins", sub_category="Haze")
        return Details(submission=sub, files=sorted(files, key=lambda f: -f.date_added))

    def files(self, model, mod_id):
        return [f for f, _ in self.zips[mod_id]]

    def download(self, file, dest_dir, progress=None, cancel=None):
        for mid, entries in self.zips.items():
            for f, p in entries:
                if f.id == file.id:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    out = dest_dir / p.name
                    out.write_bytes(p.read_bytes())
                    return out
        raise KeyError(file.id)


def mod_zip(tmp_path: Path, name: str, variants: dict[str, dict[str, bytes]]) -> Path:
    z = tmp_path / "zips" / f"{name}.zip"
    z.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z, "w") as zf:
        for folder, files in variants.items():
            v = make_vpk(tmp_path / "build" / name / folder / "pak01_dir.vpk", files)
            zf.write(v, f"{folder}/pak01_dir.vpk" if folder else "pak01_dir.vpk")
    return z


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "find_7z", lambda: None)
    game = make_game(tmp_path / "lib")
    zips = {
        1: [(GBFile(id=11, filename="one.zip", date_added=100), mod_zip(tmp_path, "one", {"": {"models/haze.vmdl_c": b"A", "sounds/x.vsnd_c": b"1"}}))],
        2: [(GBFile(id=21, filename="two.zip", date_added=100), mod_zip(tmp_path, "two", {"": {"models/haze.vmdl_c": b"B"}}))],
        3: [(GBFile(id=31, filename="three.zip", date_added=100),
             mod_zip(tmp_path, "three", {"Blue": {"ui/hud.png": b"b"}, "Red": {"ui/hud.png": b"r"}}))],
    }
    mgr = Manager(Library(), FakeGB(zips))
    mgr.set_game_dir(game)
    return mgr, game, zips, tmp_path


def addons(game: Path) -> list[str]:
    root = game / "game" / "citadel"
    return sorted(p.relative_to(root).as_posix() for p in root.glob("addons*/*") if p.is_file())


def test_install_apply_order_and_conflicts(setup):
    mgr, game, zips, _ = setup
    mgr.install_gamebanana("Mod", 1)
    mgr.install_gamebanana("Mod", 2)  # newest install goes on top = wins
    mgr.apply()
    assert addons(game) == ["addons/pak01_dir.vpk", "addons/pak02_dir.vpk"]
    citadel = game / "game" / "citadel"
    assert vpk.list_entries(citadel / "addons/pak01_dir.vpk") == ["models/haze.vmdl_c"]  # mod 2
    assert gameinfo.inspect(gameinfo.read(game)).folders == ["citadel/addons"]

    c = mgr.conflicts()
    assert c["gb-Mod-2"].clashes[0].wins and c["gb-Mod-2"].clashes[0].files == ["models/haze.vmdl_c"]
    assert not c["gb-Mod-1"].clashes[0].wins

    # reorder: mod 1 on top
    mgr.set_order(["gb-Mod-1", "gb-Mod-2"])
    mgr.apply()
    assert len(vpk.list_entries(citadel / "addons/pak01_dir.vpk")) == 2  # mod 1 now pak01

    # disable mod 1 -> only one file, gameinfo still patched
    mgr.set_enabled("gb-Mod-1", False)
    res = mgr.apply()
    assert addons(game) == ["addons/pak01_dir.vpk"] and res.removed == 1

    # second apply with nothing changed rewrites nothing
    res = mgr.apply()
    assert res.written == 0 and res.kept == 1

    # disable all -> folder emptied, gameinfo back to vanilla
    mgr.set_enabled("gb-Mod-2", False)
    mgr.apply()
    assert addons(game) == []
    assert not gameinfo.inspect(gameinfo.read(game)).patched


def test_variant_chooser_and_update_keeps_choice(setup):
    mgr, game, zips, tmp_path = setup
    asked = []

    def choose(sets, name):
        asked.append([s.rel for s in sets])
        return [s for s in sets if s.rel.startswith("Red")]

    mod = mgr.install_gamebanana("Mod", 3, choose=choose)
    assert asked == [["Blue/pak01_dir.vpk", "Red/pak01_dir.vpk"]]
    # every variant is kept in the library; only the chosen one is active
    assert [(v.label, v.active) for v in mod.vpks] == [("Blue/pak01_dir.vpk", False), ("Red/pak01_dir.vpk", True)]
    mgr.apply()
    assert addons(game) == ["addons/pak01_dir.vpk"]
    assert vpk.list_entries(game / "game/citadel/addons/pak01_dir.vpk") == ["ui/hud.png"]
    assert (mod.folder / mod.vpks[0].main.stored).exists()
    # switch variant without downloading anything
    mgr.set_variants("gb-Mod-3", ["Blue/pak01_dir.vpk"])
    assert [v.active for v in mgr.lib.mods["gb-Mod-3"].vpks] == [True, False]
    mgr.apply()
    assert addons(game) == ["addons/pak01_dir.vpk"]
    with pytest.raises(Exception):
        mgr.set_variants("gb-Mod-3", [])
    mgr.set_variants("gb-Mod-3", ["Red/pak01_dir.vpk"])

    # author uploads a new version
    newer = GBFile(id=32, filename="three-v2.zip", date_added=200)
    zips[3].append((newer, mod_zip(tmp_path, "three2", {"Blue": {"ui/hud.png": b"B2"},
                                                         "Red": {"ui/hud.png": b"R2"}})))
    found = mgr.check_updates()
    assert [m.uid for m in found] == ["gb-Mod-3"]
    assert mgr.lib.mods["gb-Mod-3"].update.file_id == 32
    upd = mgr.update("gb-Mod-3", choose=lambda s, n: pytest.fail("should reuse Red"))
    assert upd.file_id == 32 and upd.update is None
    assert [(v.label, v.active) for v in upd.vpks] == [("Blue/pak01_dir.vpk", False), ("Red/pak01_dir.vpk", True)]
    assert mgr.check_updates() == []


def test_other_variants_are_separate_files(setup, tmp_path):
    """Most GameBanana colour options are separate files: list them, switch, come back."""
    mgr, game, zips, _ = setup
    blue = GBFile(id=41, filename="yamato_blue.zip", date_added=100, description="Blue outfit")
    red = GBFile(id=42, filename="yamato_red.zip", date_added=100, description="Red outfit")
    old = GBFile(id=40, filename="yamato_v1.zip", date_added=50, archived=True)
    zips[4] = [(blue, mod_zip(tmp_path, "yblue", {"": {"ui/hud.png": b"blue"}})),
               (red, mod_zip(tmp_path, "yred", {"": {"ui/hud.png": b"red"}})),
               (old, mod_zip(tmp_path, "yold", {"": {"ui/hud.png": b"old"}}))]
    mod = mgr.install_gamebanana("Mod", 4, blue)
    assert mod.file_id == 41 and len(mod.vpks) == 1
    files = mgr.variant_files(mod.uid)
    assert sorted(f.id for f in files) == [40, 41, 42]
    # switch to the red file
    switched = mgr.refetch(mod.uid, 42)
    assert switched.file_id == 42 and switched.file_name == "yamato_red.zip"
    mgr.apply()
    assert addons(game) == ["addons/pak01_dir.vpk"]
    assert vpk.read_entries(game / "game/citadel/addons/pak01_dir.vpk")[0].preload == 3  # "red"
    # same file again keeps working; a vanished file is a clear error
    again = mgr.refetch(mod.uid)
    assert again.file_id == 42
    with pytest.raises(Exception, match="isn't on GameBanana"):
        mgr.refetch(mod.uid, 99)
    # local mods have no GameBanana files to list
    local = mgr.install_local(make_vpk(tmp_path / "loc" / "x.vpk", {"a.txt": b"x"}))
    with pytest.raises(Exception, match="Only GameBanana"):
        mgr.variant_files(local.uid)


def test_add_optional_files_alongside_main(setup, tmp_path):
    """A main download plus optional add-on files can all be installed at once."""
    mgr, game, zips, _ = setup
    main = GBFile(id=51, filename="qollock_405.zip", date_added=300)
    ann = GBFile(id=52, filename="optional_announcer_pixie.zip", date_added=200)
    icons = GBFile(id=53, filename="optional_addon_icons.zip", date_added=100)
    zips[5] = [(main, mod_zip(tmp_path, "qmain", {"": {"ui/hud.txt": b"main"}})),
               (ann, mod_zip(tmp_path, "qann", {"": {"sounds/ann.vsnd_c": b"pix"}})),
               (icons, mod_zip(tmp_path, "qicons", {"": {"ui/icons.png": b"ic"}}))]
    m = mgr.install_gamebanana("Mod", 5, main)
    a = mgr.install_gamebanana("Mod", 5, ann, add=True)
    i = mgr.install_gamebanana("Mod", 5, icons, add=True)
    assert m.uid == "gb-Mod-5" and a.uid == "gb-Mod-5-f52" and i.uid == "gb-Mod-5-f53"
    assert a.name == "Mod 5 + optional announcer pixie"
    assert [x.uid for x in mgr.lib.by_gb_all("Mod", 5)] == ["gb-Mod-5", "gb-Mod-5-f53", "gb-Mod-5-f52"]
    assert mgr.lib.by_gb("Mod", 5).uid == "gb-Mod-5"
    mgr.apply()
    assert len(addons(game)) == 3
    # "add" of a file that's already installed refreshes that entry instead of duplicating it
    again = mgr.install_gamebanana("Mod", 5, ann, add=True)
    assert again.uid == "gb-Mod-5-f52" and len(mgr.lib.by_gb_all("Mod", 5)) == 3
    # without add=, a different file replaces the main entry and leaves the extras alone
    mgr.install_gamebanana("Mod", 5, GBFile(id=51, filename="qollock_405.zip", date_added=300))
    assert len(mgr.lib.by_gb_all("Mod", 5)) == 3
    # update check: the newest file is the main one, so the add-ons are NOT flagged
    assert mgr.check_updates() == []
    # the author replaces the announcer file: only that extra is flagged, and updates in place
    ann2 = GBFile(id=54, filename="optional_announcer_pixie_v2.zip", date_added=400)
    zips[5][1] = (GBFile(id=52, filename="optional_announcer_pixie.zip", date_added=200, archived=True), zips[5][1][1])
    zips[5].append((ann2, mod_zip(tmp_path, "qann2", {"": {"sounds/ann.vsnd_c": b"pix2"}})))
    found = mgr.check_updates()
    assert [x.uid for x in found] == ["gb-Mod-5-f52"]
    assert mgr.lib.mods["gb-Mod-5"].update is None  # a renamed add-on is not an update for the main file
    upd = mgr.update("gb-Mod-5-f52")
    assert upd.uid == "gb-Mod-5-f52" and upd.file_id == 54 and upd.name == "Mod 5 + optional announcer pixie"
    # removing the main entry leaves the extras, and by_gb still finds the mod
    mgr.remove("gb-Mod-5")
    assert mgr.lib.by_gb("Mod", 5).uid == "gb-Mod-5-f53"


def test_overflow_into_addons2(setup, tmp_path):
    mgr, game, _, _ = setup
    src = tmp_path / "many"
    for i in range(105):
        mgr.install_local(make_vpk(src / f"m{i:03d}" / f"mod{i:03d}.vpk", {f"f{i}.txt": b"x"}))
    mgr.apply()
    files = addons(game)
    assert len([f for f in files if f.startswith("addons/")]) == 99
    assert len([f for f in files if f.startswith("addons2/")]) == 6
    assert gameinfo.inspect(gameinfo.read(game)).folders == ["citadel/addons", "citadel/addons2"]
    # drop below 99 -> addons2 disappears and gameinfo shrinks
    for uid in mgr.lib.order[:10]:
        mgr.set_enabled(uid, False)
    mgr.apply()
    assert not (game / "game/citadel/addons2").exists()
    assert gameinfo.inspect(gameinfo.read(game)).folders == ["citadel/addons"]


def test_adopts_manual_installs_instead_of_deleting(setup, tmp_path):
    mgr, game, _, _ = setup
    citadel = game / "game" / "citadel"
    make_vpk(citadel / "addons" / "pak07_dir.vpk", {"manual.txt": b"m"})
    (citadel / "addons" / "readme.txt").write_text("keep me")
    mgr.install_gamebanana("Mod", 1)
    mgr.apply()
    names = {m.name for m in mgr.lib.mods.values()}
    assert any(n.startswith("Manual install") for n in names)
    assert addons(mgr.game_dir) == ["addons/pak01_dir.vpk", "addons/pak02_dir.vpk", "addons/readme.txt"]
    # and it's not adopted again on the next apply
    mgr.apply()
    assert len(mgr.lib.mods) == 2


def test_game_update_wipes_gameinfo_and_we_fix_it(setup):
    mgr, game, _, _ = setup
    from helpers import VANILLA
    mgr.install_gamebanana("Mod", 1)
    mgr.apply()
    assert not mgr.gameinfo_needs_fix()
    gameinfo.gameinfo_path(game).write_bytes(VANILLA.read_bytes())  # Steam update
    assert mgr.gameinfo_needs_fix()
    assert mgr.ensure_gameinfo() is True
    assert not mgr.gameinfo_needs_fix()


def test_profiles(setup):
    mgr, game, _, _ = setup
    mgr.install_gamebanana("Mod", 1)
    mgr.install_gamebanana("Mod", 2)
    mgr.save_profile("both")
    mgr.set_enabled("gb-Mod-2", False)
    mgr.save_profile("just one")
    mgr.load_profile("both")
    assert all(m.enabled for m in mgr.lib.mods.values())
    mgr.remove("gb-Mod-1")
    assert mgr.load_profile("both") == ["gb-Mod-1"]
    mgr.rename_profile("just one", "solo")
    assert set(mgr.lib.profiles) == {"both", "solo"}


def test_running_game_blocks_apply(setup, monkeypatch):
    mgr, game, _, _ = setup
    mgr.install_gamebanana("Mod", 1)
    monkeypatch.setattr(steam, "is_game_running", lambda *a: True)
    with pytest.raises(GameRunning):
        mgr.apply()
    assert mgr.pending
    assert addons(game) == []


def test_state_survives_restart(setup):
    mgr, game, _, _ = setup
    mgr.install_gamebanana("Mod", 1)
    mgr.apply()
    lib2 = Library()
    assert list(lib2.mods) == ["gb-Mod-1"] and lib2.deployed
    m = lib2.mods["gb-Mod-1"]
    assert m.vpks[0].main.stored.endswith("pak01_dir.vpk")
    # corrupt state file is moved aside, not crashed on
    lib2.path.write_text("{nope")
    lib3 = Library()
    assert lib3.mods == {}
    assert list(lib2.path.parent.glob("state.broken-*.json"))


def test_details_uses_profilepage_and_files_uses_slim_query(monkeypatch):
    c = GameBananaClient()
    seen = []

    def fake_get(path, params=None, ttl=0):
        seen.append((path, params))
        if path.endswith("/ProfilePage"):
            return {"_idRow": 5, "_sName": "X", "_sText": "<p>hi</p>", "_aGame": {"_idRow": 20948},
                    "_aSuperCategory": {"_sName": "Skins"}, "_aCategory": {"_sName": "Haze"},
                    "_aFiles": [{"_idRow": 2, "_sFile": "new.zip", "_tsDateAdded": 20}],
                    "_aArchivedFiles": [{"_idRow": 1, "_sFile": "old.zip", "_tsDateAdded": 10}]}
        return {"_idRow": 5, "_aFiles": [{"_idRow": 2, "_sFile": "new.zip", "_bIsArchived": False},
                                          {"_idRow": 1, "_sFile": "old.zip", "_bIsArchived": True}]}
    monkeypatch.setattr(c, "_get", fake_get)
    d = c.details("Mod", 5)
    assert seen[0][0] == "Mod/5/ProfilePage" and seen[0][1] is None
    assert d.submission.category_label == "Skins › Haze"
    assert [(f.id, f.archived) for f in d.files] == [(2, False), (1, True)]
    fs = c.files("Mod", 5)
    assert seen[1] == ("Mod/5", {"_csvProperties": "_idRow,_aFiles"})
    assert [(f.id, f.archived) for f in fs] == [(2, False), (1, True)]
    from sapphire.gamebanana import newest_file
    assert newest_file(fs).id == 2


def test_clear_all_data(setup):
    mgr, game, _, _ = setup
    mgr.install_gamebanana("Mod", 1)
    mgr.save_profile("p")
    mgr.apply()
    assert addons(game) and mgr.lib.profiles
    assert mgr.clear_all_data() == 1
    assert mgr.lib.mods == {} and mgr.lib.profiles == {} and addons(game) == []
    assert not gameinfo.inspect(gameinfo.read(game)).patched
    from sapphire import paths
    assert list(paths.library_dir().iterdir()) == []
    mgr.lib.game_dir == str(game)


def test_newer_version_rule():
    from sapphire.gamebanana import file_family, newer_version
    assert file_family("qollock_405_16october.zip") == file_family("QOLLock_406.zip") == "qollock"
    assert file_family("yamato_blue_cd01a.rar") != file_family("yamato_red_cd01a.rar")
    main = GBFile(id=1, filename="qollock_405.zip", date_added=300)
    addon = GBFile(id=2, filename="optional_announcer.zip", date_added=500)
    files = [main, addon]
    # a newer add-on is not an update for the main file, and vice versa
    assert newer_version(1, main.filename, 300, files) is None
    assert newer_version(2, addon.filename, 500, files) is None
    # a newer file of the same family is
    v2 = GBFile(id=3, filename="qollock_406.zip", date_added=600)
    assert newer_version(1, main.filename, 300, files + [v2]) is v2
    # my file archived with a same-family successor -> that; archived with none -> newest live
    gone = [GBFile(id=1, filename="qollock_405.zip", date_added=300, archived=True), addon, v2]
    assert newer_version(1, "qollock_405.zip", 300, gone) is v2
    assert newer_version(1, "qollock_405.zip", 300, [gone[0], addon]) is addon
    # my file removed entirely, renamed successor -> newest live file
    assert newer_version(9, "something_old.zip", 100, [addon]) is addon
    # another colour of a variant mod is never an update
    blue = GBFile(id=5, filename="yamato_blue.rar", date_added=100)
    red = GBFile(id=6, filename="yamato_red.rar", date_added=200)
    assert newer_version(5, blue.filename, 100, [blue, red]) is None
