"""1.5.0 features: roll back, one skin per hero, shared profiles, helper, GameBanana parsing."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from helpers import make_game, make_vpk
from sapphire import archive, gameinfo, helper
from sapphire.core import Manager, ManagerError
from sapphire.gamebanana import (Details, GameBananaClient, GBFile, Submission, parse_collection_url,
                                 parse_submission)
from sapphire.library import Library


def mod_zip(tmp: Path, name: str, files: dict[str, bytes]) -> Path:
    z = tmp / "zips" / f"{name}.zip"
    z.parent.mkdir(parents=True, exist_ok=True)
    v = make_vpk(tmp / "build" / name / "pak01_dir.vpk", files)
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(v, "pak01_dir.vpk")
    return z


class FakeGB(GameBananaClient):
    def __init__(self, zips):
        super().__init__()
        self.zips = zips          # mod_id -> [(GBFile, zip path)]
        self.collections = {}

    def details(self, model, mod_id):
        files = [f for f, _ in self.zips[mod_id]]
        sub = Submission(id=mod_id, model=model, name=f"Mod {mod_id}", author="someone",
                         audio_url="https://files.gamebanana.com/preview/sounds/x.mp3" if model == "Sound" else "")
        return Details(submission=sub, files=sorted(files, key=lambda f: -f.date_added))

    def files(self, model, mod_id):
        return [f for f, _ in self.zips[mod_id]]

    def download(self, file, dest_dir, progress=None, cancel=None):
        for entries in self.zips.values():
            for f, p in entries:
                if f.id == file.id:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    out = dest_dir / p.name
                    out.write_bytes(p.read_bytes())
                    return out
        raise KeyError(file.id)


HAZE = "models/heroes_wip/haze/haze.vmdl_c"
INFERNO_V4 = "models/heroes_wip/inferno_v4/inferno_v4.vmdl_c"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "find_7z", lambda: None)
    game = make_game(tmp_path / "lib")
    zips = {
        1: [(GBFile(id=11, filename="haze_red_v1.zip", date_added=100), mod_zip(tmp_path, "h1", {HAZE: b"red1"}))],
        2: [(GBFile(id=21, filename="haze_blue.zip", date_added=100), mod_zip(tmp_path, "h2", {HAZE: b"blue"}))],
        3: [(GBFile(id=31, filename="inferno.zip", date_added=100), mod_zip(tmp_path, "i1", {INFERNO_V4: b"inf"}))],
        4: [(GBFile(id=41, filename="hud.zip", date_added=100), mod_zip(tmp_path, "hud", {"panorama/x.vjs_c": b"h"}))],
    }
    mgr = Manager(Library(), FakeGB(zips))
    mgr.set_game_dir(game)
    return mgr, game, zips, tmp_path


# ---------------------------------------------------------------------- roll back

def test_update_keeps_the_previous_version_for_roll_back(env):
    mgr, game, zips, tmp = env
    mod = mgr.install_gamebanana("Mod", 1)
    assert not mgr.can_roll_back(mod.uid)
    zips[1].append((GBFile(id=12, filename="haze_red_v2.zip", date_added=200), mod_zip(tmp, "h1b", {HAZE: b"red2"})))
    assert [m.uid for m in mgr.check_updates()] == [mod.uid]
    mgr.update(mod.uid)
    m = mgr.lib.mods[mod.uid]
    assert m.file_id == 12 and m.previous["file_id"] == 11 and mgr.can_roll_back(mod.uid)
    mgr.apply()
    pak = game / "game/citadel/addons/pak01_dir.vpk"
    assert b"red2" in pak.read_bytes()

    back = mgr.roll_back(mod.uid)
    assert back.file_id == 11 and back.file_name == "haze_red_v1.zip"
    assert back.update.file_id == 12 and back.skip_file_id == 12      # offered again, but not auto
    assert mgr.auto_update_targets([back]) == []
    mgr.apply()
    assert b"red1" in pak.read_bytes()
    # rolling back again undoes the roll back
    again = mgr.roll_back(mod.uid)
    assert again.file_id == 12
    # an explicit update clears the skip
    mgr.roll_back(mod.uid)
    mgr.update(mod.uid)
    assert mgr.lib.mods[mod.uid].skip_file_id == 0
    # uninstall removes the parked version too
    mgr.remove(mod.uid)
    assert not mgr.previous_dir(mod.uid).exists()


def test_reinstalling_the_same_file_keeps_no_previous(env):
    mgr, *_ = env
    mod = mgr.install_gamebanana("Mod", 1)
    mgr.refetch(mod.uid)
    assert not mgr.can_roll_back(mod.uid)
    with pytest.raises(ManagerError):
        mgr.roll_back(mod.uid)


# ---------------------------------------------------------------------- heroes

def test_hero_detection_and_one_skin_per_hero(env):
    mgr, *_ = env
    a = mgr.install_gamebanana("Mod", 1)
    b = mgr.install_gamebanana("Mod", 2)
    inf = mgr.install_gamebanana("Mod", 3)
    hud = mgr.install_gamebanana("Mod", 4)
    assert mgr.hero_of(a) == mgr.hero_of(b) == "haze"
    assert mgr.hero_of(inf) == "inferno"          # inferno_v4 folds into inferno
    assert mgr.hero_of(hud) is None
    # setting off: both haze skins stay on
    assert mgr.lib.mods[a.uid].enabled and mgr.lib.mods[b.uid].enabled
    mgr.lib.settings.one_skin_per_hero = True
    off = mgr.set_enabled(a.uid, True)
    assert [m.uid for m in off] == [b.uid] and not mgr.lib.mods[b.uid].enabled
    assert mgr.lib.mods[inf.uid].enabled and mgr.lib.mods[hud.uid].enabled
    # installing another haze skin switches the current one off
    mgr.gb.zips[5] = [(GBFile(id=51, filename="haze_green.zip", date_added=100),
                       mod_zip(mgr.lib.mods[a.uid].folder.parent.parent, "h5", {HAZE: b"g"}))]
    c = mgr.install_gamebanana("Mod", 5)
    assert mgr.lib.mods[c.uid].enabled and not mgr.lib.mods[a.uid].enabled
    assert [m.uid for m in mgr.skins_for("haze")] == [c.uid, b.uid, a.uid]


# ---------------------------------------------------------------------- shared profiles

def test_profile_round_trip_downloads_missing_mods(env, tmp_path):
    mgr, game, zips, tmp = env
    a = mgr.install_gamebanana("Mod", 1)
    inf = mgr.install_gamebanana("Mod", 3)
    local = mgr.install_local(make_vpk(tmp / "src" / "mine.vpk", {"x.txt": b"x"}))
    mgr.set_enabled(inf.uid, False)
    mgr.save_profile("Ranked")
    out = tmp_path / "ranked.sapphire-profile"
    assert mgr.export_profile("Ranked", out) == 3
    data = json.loads(out.read_text())
    assert data["format"] == "sapphire-profile" and data["name"] == "Ranked"
    assert [(m["name"], m["enabled"]) for m in data["mods"]] == [
        ("mine", True), ("Mod 3", False), ("Mod 1", True)]

    # a friend with nothing installed
    friend = Manager(Library(tmp_path / "friend-state.json"), mgr.gb)
    friend.set_game_dir(game)
    shared = friend.read_shared_profile(out)
    assert friend.match_shared(shared["mods"][1]) is None
    res = friend.import_shared_profile(shared, "Ranked (shared)")
    assert res["downloaded"] == 2 and res["missing"] == ["mine"] and res["failed"] == []
    # downloads stay off until the profile is switched to
    assert all(not m.enabled for m in friend.lib.mods.values())
    assert friend.load_profile("Ranked (shared)") == []
    assert [(m.name, m.enabled) for m in friend.lib.ordered()] == [("Mod 3", False), ("Mod 1", True)]
    # importing again reuses what's installed
    assert friend.import_shared_profile(shared, "again")["downloaded"] == 0


def test_bad_profile_files_are_rejected(tmp_path):
    p = tmp_path / "x.json"
    p.write_text('{"format": "something-else", "mods": []}')
    with pytest.raises(ManagerError):
        Manager.read_shared_profile(p)
    p.write_text("not json")
    with pytest.raises(ManagerError):
        Manager.read_shared_profile(p)
    p.write_text(json.dumps({"format": "sapphire-profile", "mods": [
        {"name": "ok", "source": "gamebanana", "model": "Mod", "gb_id": 5, "file_id": 7},
        {"name": "no id", "source": "gamebanana", "model": "Mod"},
        "junk", {"name": 3}]}))
    shared = Manager.read_shared_profile(p)
    assert [m["name"] for m in shared["mods"]] == ["ok"] and shared["name"] == "Shared profile"


# ---------------------------------------------------------------------- helper

def test_helper_repairs_gameinfo_only_when_the_window_is_closed(env, monkeypatch, tmp_path):
    mgr, game, *_ = env
    mgr.install_gamebanana("Mod", 1)
    mgr.apply()
    gi = game / "game/citadel/gameinfo.gi"
    patched = gi.read_text()
    assert "citadel/addons" in patched
    state = json.loads(Path(mgr.lib.path).read_text())
    assert helper.deployed_folders(state) == ["citadel/addons"]
    # a game update resets the file
    from helpers import VANILLA
    gi.write_bytes(VANILLA.read_bytes())
    assert helper.check_once(state) is True
    assert "citadel/addons" in gi.read_text()
    assert helper.check_once(state) is False      # already fine

    # the loop: with the window's lock held it leaves things alone
    mgr.lib.settings.helper = True
    mgr.lib.save()
    gi.write_bytes(VANILLA.read_bytes())
    lock = helper.hold_gui_lock()
    helper.run(stop_after=0.6)
    assert "citadel/addons" not in gi.read_text()
    lock.close()
    helper.run(stop_after=0.6)
    assert "citadel/addons" in gi.read_text()


def test_helper_autostart_entry(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    f = helper.enable(start_now=False)
    text = f.read_text()
    assert f.name == "sapphire-helper.desktop" and "--helper" in text and "NoDisplay=true" in text
    assert helper.is_enabled()
    helper.disable()
    assert not helper.is_enabled()
    monkeypatch.setenv("FLATPAK_ID", "io.github.snowberrifox.Sapphire")
    assert helper.command()[:2] == ["flatpak", "run"]


# ---------------------------------------------------------------------- GameBanana parsing

def test_sound_preview_and_collection_parsing():
    raw = {"_idRow": 87134, "_sModelName": "Sound", "_sName": "Animal",
           "_aPreviewMedia": {"_aMetadata": {"_sAudioUrl": "https://files.gamebanana.com/preview/sounds/a.mp3"}}}
    assert parse_submission(raw, "Sound").audio_url == "https://files.gamebanana.com/preview/sounds/a.mp3"
    raw["_aPreviewMedia"]["_aMetadata"]["_sAudioUrl"] = "http://evil.example/a.mp3"
    assert parse_submission(raw, "Sound").audio_url == ""
    assert parse_collection_url("see https://gamebanana.com/collections/164637 !") == 164637
    assert parse_collection_url("https://gamebanana.com/mods/1") is None


def test_collection_paging_and_filtering(monkeypatch):
    c = GameBananaClient()
    rec = lambda i, model="Mod", game=20948: {"_idRow": i, "_sModelName": model, "_sName": f"m{i}",
                                              "_aGame": {"_idRow": game}, "_bHasFiles": True}
    pages = {1: {"_aMetadata": {"_bIsComplete": False}, "_aRecords": [rec(1), rec(2, "Wip"), rec(3, game=1)]},
             2: {"_aMetadata": {"_bIsComplete": True}, "_aRecords": [rec(4, "Sound"), rec(1)]}}

    def fake_get(path, params=None, ttl=90):
        if path.endswith("ProfilePage"):
            return {"_sName": "Tamie&#039;s picks", "_aSubmitter": {"_sName": "Tamie"}}
        return pages[params["_nPage"]]
    monkeypatch.setattr(c, "_get", fake_get)
    col = c.collection(164637)
    assert col.name == "Tamie's picks" and col.author == "Tamie"
    assert [(s.model, s.id) for s in col.items] == [("Mod", 1), ("Sound", 4)] and col.skipped == 2


def test_audio_backend_choice(tmp_path):
    from sapphire.ui.audio import pick_audio_backend
    run = tmp_path / "run"
    (run / "pulse").mkdir(parents=True)
    assert pick_audio_backend({"QT_AUDIO_BACKEND": "alsa"}) is None          # the user's choice stands
    env = {"XDG_RUNTIME_DIR": str(run)}
    assert pick_audio_backend(env) == "alsa" and env["QT_AUDIO_BACKEND"] == "alsa"   # no socket yet
    (run / "pulse" / "native").write_text("")
    env = {"XDG_RUNTIME_DIR": str(run)}
    assert pick_audio_backend(env) == "pulseaudio"


def test_steam_registry_running_app(tmp_path, monkeypatch):
    from sapphire import steam
    reg = tmp_path / ".steam" / "registry.vdf"
    reg.parent.mkdir()
    reg.write_text('"Registry"\n{\n\t"HKCU"\n\t{\n\t\t"Software"\n\t\t{\n\t\t\t"Valve"\n\t\t\t{\n\t\t\t\t"Steam"\n'
                   '\t\t\t\t{\n\t\t\t\t\t"RunningAppID"\t\t"1422450"\n\t\t\t\t\t"language"\t\t"english"\n'
                   '\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
    assert steam.steam_running_app(tmp_path) == "1422450"
    monkeypatch.undo()                      # drop conftest's is_game_running stub for this check
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("FLATPAK_ID", "io.github.snowberrifox.Sapphire")
    assert steam.is_game_running() is True
    reg.write_text(reg.read_text().replace('"1422450"', '"0"'))
    assert steam.is_game_running() is False


def test_flatpak_autostart_goes_to_the_real_config(tmp_path, monkeypatch):
    monkeypatch.setenv("FLATPAK_ID", "io.github.snowberrifox.Sapphire")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "sandbox-config"))
    from pathlib import Path
    assert helper.autostart_file() == Path.home() / ".config" / "autostart" / "sapphire-helper.desktop"
