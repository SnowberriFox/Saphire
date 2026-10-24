"""Crosshair settings file editing, restore, sharing and autoexec."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import make_game
from sapphire import crosshair as ch

SAMPLE = Path(__file__).with_name("hero_settings_sample.lst")


@pytest.fixture
def game(tmp_path):
    g = make_game(tmp_path / "lib")
    cfg = g / "game/citadel/cfg"
    cfg.mkdir(parents=True)
    (cfg / ch.SETTINGS_FILE).write_bytes(SAMPLE.read_bytes())
    return g


def settings(game) -> bytes:
    return (game / "game/citadel/cfg" / ch.SETTINGS_FILE).read_bytes()


def test_read_apply_restore_keeps_everything_else(game):
    vals, themed = ch.current(game)
    assert vals["crosshair_pip_gap"] == 4 and vals["crosshair_pip_opacity"] == 0.5 and not themed
    assert vals["crosshair_dot_size"] == 4          # missing key -> default
    before = settings(game)
    new = dict(vals, crosshair_color_r=10, crosshair_pip_gap=-3, crosshair_dot_size=6)
    assert ch.apply(game, new)
    after = settings(game)
    text = after.decode()
    assert 'crosshair_color_r = "10"' in text and 'crosshair_pip_gap = "-3"' in text
    assert 'crosshair_dot_size = "6"' in text                # added inside base
    assert 'mouse_sensitivity = "1"' in text and after.count(b"\r\n") > before.count(b"\r\n")
    assert b"\n" not in after.replace(b"\r\n", b"")          # still all CRLF
    ch.HeroSettings(text)                                    # still parses
    assert ch.has_backup()
    ch.apply(game, dict(new, crosshair_color_r=20))          # a second apply keeps the first original
    ch.restore(game)
    assert settings(game) == before and not ch.has_backup()


def test_restore_leaves_values_changed_in_game_since(game):
    vals, _ = ch.current(game)
    ch.apply(game, dict(vals, crosshair_color_r=10, crosshair_color_g=20))
    p = game / "game/citadel/cfg" / ch.SETTINGS_FILE
    p.write_bytes(p.read_bytes().replace(b'crosshair_color_g = "20"', b'crosshair_color_g = "99"'))
    ch.restore(game)
    text = p.read_text()
    assert 'crosshair_color_r = "255"' in text and 'crosshair_color_g = "99"' in text


def test_steam_cloud_copy_is_updated_too(game, tmp_path, monkeypatch):
    root = tmp_path / "home/.local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    cloud = root / "userdata/12345/1422450/remote/cfg"
    cloud.mkdir(parents=True)
    (cloud / ch.SETTINGS_FILE).write_bytes(SAMPLE.read_bytes())
    vals, _ = ch.current(game)
    changed = ch.apply(game, dict(vals, crosshair_pip_width=5))
    assert len(changed) == 2 and 'crosshair_pip_width = "5"' in (cloud / ch.SETTINGS_FILE).read_text()


def test_game_running_blocks_writes(game, monkeypatch):
    from sapphire import steam
    monkeypatch.setattr(steam, "is_game_running", lambda *a, **k: True)
    with pytest.raises(ch.CrosshairError):
        ch.apply(game, ch.defaults())


def test_missing_file_is_created(tmp_path):
    g = make_game(tmp_path / "lib2")
    ch.apply(g, ch.defaults())
    text = (g / "game/citadel/cfg" / ch.SETTINGS_FILE).read_text()
    assert 'crosshair_themed = "false"' in text and "heroes" in text


def test_refuses_bad_files_and_keys():
    with pytest.raises(ch.CrosshairError):
        ch.HeroSettings("not kv3")
    hs = ch.HeroSettings(SAMPLE.read_text())
    with pytest.raises(ch.CrosshairError):
        hs.update({"mouse_sensitivity": '"9"'})
    with pytest.raises(ch.CrosshairError):
        hs.update({"crosshair_pip_gap": "{"})


def test_commands_round_trip_and_dmm_codes():
    vals = dict(ch.defaults(), crosshair_color_g=0, crosshair_pip_gap_static=1, crosshair_pip_width=2.5)
    back = ch.from_commands(ch.to_commands(vals))
    assert back == {k: ch.clamp(k, v) for k, v in vals.items()}
    dmm = "citadel_crosshair_color_r 255; citadel_crosshair_pip_border true; citadel_crosshair_pip_gap 99"
    got = ch.from_commands(dmm)
    assert got == {"crosshair_color_r": 255, "crosshair_pip_outline_border": 1, "crosshair_pip_gap": 50}  # clamped
    assert ch.from_commands('crosshair_dot_size = "6"\ncrosshair_bogus 3') == {"crosshair_dot_size": 6}


def test_presets(tmp_path):
    ch.save_preset("Green dot", dict(ch.defaults(), crosshair_color_r=0))
    assert ch.presets()["Green dot"]["crosshair_color_r"] == 0
    ch.delete_preset("Green dot")
    assert ch.presets() == {}


def test_autoexec_is_never_saved_empty(game):
    assert ch.read_autoexec(game) == ""
    assert ch.write_autoexec(game, "   \n") == ch.AUTOEXEC_PLACEHOLDER
    assert ch.write_autoexec(game, "fps_max 240") == "fps_max 240\n"
    assert ch.read_autoexec(game) == "fps_max 240\n"
