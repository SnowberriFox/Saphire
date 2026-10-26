"""1.8.0: which heroes a mod really changes (Ham's "profiles leak" report).

The leak turned out to be a sound mod that carried a whole Billy reskin. These
tests pin down the file-path -> hero matching, which comes from the game's own
hero list (scripts/heroes.vdata_c) so renamed heroes match correctly.
"""

from __future__ import annotations

from kv3_build import container, encode
from sapphire import heroes
from sapphire.heroes import HeroIndex, heroes_from_vdata, read_game_heroes, surprises
from sapphire.vpk import write_vpk

# A cut-down heroes.vdata, shaped like the real one (October 2026).
VDATA = {
    "generic_data_type": "CitadelHeroData",
    "hero_base": {"m_strModelName": "models/heroes_wip/gen_man/gen_man.vmdl"},
    "hero_atlas": {
        "m_strModelName": "models/heroes_wip/abrams/abrams.vmdl",
        "m_strIconImageSmall": "file://{images}/heroes/bull_sm.psd",
        "m_strIconHeroCard": "file://{images}/heroes/bull_card.psd",
        "m_strLogoImageEnglish": "file://{images}/heroes/hero_names/abrams.svg",
        "m_strUIShoppingMap": "maps/ui/hero_shop/abrams_shop.vmap",
        "m_strUIPortraitMap": "maps/ui/hero_prefabs/abrams.vmap",
        "m_bDisabled": False, "m_bInDevelopment": False,
    },
    "hero_viper": {   # Vyper: portraits still named after the old codename
        "m_strModelName": "models/heroes_staging/viper/viper.vmdl",
        "m_strIconHeroCard": "file://{images}/heroes/kali_card.psd",
        "m_strMinimapImage": "file://{images}/heroes/kali_mm.psd",
        "m_strLogoImageEnglish": "file://{images}/heroes/hero_names/vyper.svg",
        "m_bDisabled": False, "m_bInDevelopment": False,
    },
    "hero_punkgoat": {
        "m_strModelName": "models/heroes_wip/punkgoat/punkgoat.vmdl",
        "m_strIconHeroCard": "file://{images}/heroes/punkgoat_card.psd",
        "m_strLogoImageEnglish": "file://{images}/heroes/hero_names/billy.svg",
        "m_strUIPortraitMap": "maps/ui/hero_prefabs/punkgoat.vmap",
        "m_bDisabled": False, "m_bInDevelopment": False,
    },
    "hero_unicorn": {
        "m_strModelName": "models/heroes_wip/unicorn/unicorn.vmdl",
        "m_strIconHeroCard": "file://{images}/heroes/unicorn_card.psd",
        "m_strUIPortraitMap": "maps/ui/hero_prefabs/unicorn.vmap",
        "m_bDisabled": False, "m_bInDevelopment": False,
    },
    "hero_kali": {"m_strModelName": "models/heroes_wip/gen_man/gen_man.vmdl", "m_bDisabled": True},
    "hero_wrecker": {"m_strModelName": "models/heroes_wip/wrecker/wrecker.vmdl", "m_bInDevelopment": True},
}
NAMES = {"atlas": "Abrams", "viper": "Vyper", "punkgoat": "Billy", "unicorn": "Celeste", "kali": "Kali"}

BALATRO = [  # the sound mod from Ham's report, as it ships
    "sounds/abilities/celeste/mult.vsnd_c",
    "models/heroes_wip/punkgoat/punkgoat.vmdl_c",
    "models/heroes_wip/punkgoat/materials/body_basecolor_png_6fb0cefd.vtex_c",
    "panorama/images/heroes/punkgoat_card_psd.vtex_c",
    "panorama/images/heroes/hero_names/billy.vsvg_c",
]


def index() -> HeroIndex:
    return HeroIndex(heroes_from_vdata(VDATA, NAMES))


def test_heroes_from_vdata_keeps_playable_heroes_only():
    hs = {h.codename: h for h in heroes_from_vdata(VDATA, NAMES)}
    assert set(hs) == {"atlas", "viper", "punkgoat", "unicorn"}   # no base/kali/wrecker
    assert hs["atlas"].name == "Abrams" and hs["atlas"].model_dir == "models/heroes_wip/abrams/"
    assert hs["atlas"].images == {"bull"} and hs["viper"].images == {"kali"}
    assert "maps/ui/hero_shop/abrams_shop" in hs["atlas"].scenes


def test_classify_paths():
    hi = index()
    assert hi.classify("models/heroes_wip/abrams/abrams.vmdl_c") == ("Abrams", "model")
    assert hi.classify("models/heroes_wip/abrams/materials/skin.vtex_c") == ("Abrams", "textures")
    assert hi.classify("panorama/images/heroes/bull_card_psd.vtex_c") == ("Abrams", "portraits")
    assert hi.classify("panorama/images/heroes/kali_card_psd.vtex_c") == ("Vyper", "portraits")
    assert hi.classify("panorama/images/heroes/hero_names/billy.vsvg_c") == ("Billy", "portraits")
    assert hi.classify("maps/ui/hero_shop/abrams_shop.vpk") == ("Abrams", "menu scenes")
    assert hi.classify("maps/ui/hero_prefabs/punkgoat/entities/unnamed_9.vmdl_c") == ("Billy", "menu scenes")
    # folders the game doesn't use for any playable hero change nothing
    assert hi.classify("models/heroes_wip/kali/materials/kali_hat.vtex_c") is None
    assert hi.classify("sounds/abilities/celeste/mult.vsnd_c") is None


def test_surprises_catch_hidden_reskins():
    hi = index()
    ch = hi.changes(BALATRO)
    assert ch.reskinned == {"Billy"} and ch.describe("Billy") == "model, textures, portraits"
    # Ham's case: a sound mod named after Celeste that reskins Billy
    assert surprises(ch, "Celeste Balatro Mult Ult", "Other/Misc", "Sound", hi) == ["Billy"]
    # a "Billy" skin whose files are really Celeste's
    deer = hi.changes(["models/heroes_wip/unicorn/materials/unicorn_head_color_png_62edb543.vtex_c"])
    assert surprises(deer, "[New Icons!] Deer Billy Skin", "Skins", "Mod", hi) == ["Celeste"]
    # a skin that says which hero it's for: nothing to flag
    assert surprises(ch, "Punk Billy", "Skins › Billy", "Mod", hi) == []
    # a skin that names no hero at all gets the benefit of the doubt
    assert surprises(ch, "Faithful recolour", "Skins", "Mod", hi) == []
    # portraits alone (HUD packs) aren't a reskin
    hud = hi.changes(["panorama/images/heroes/bull_card_psd.vtex_c"])
    assert hud.reskinned == set() and surprises(hud, "Kitty portraits", "HUD", "Mod", hi) == []
    # Vyper's hat touching the unused "kali" folder isn't flagged as Kali
    hat = hi.changes(["models/heroes_staging/viper/viper.vmdl_c", "models/heroes_wip/kali/materials/x.vtex_c"])
    assert surprises(hat, "Vyper Propeller Hat", "Vyper › Faithful/Vanilla+", "Mod", hi) == []


def test_reads_the_games_hero_list_and_caches_it(tmp_path):
    citadel = tmp_path / "citadel"
    names = citadel / heroes.NAMES_FILE
    names.parent.mkdir(parents=True)
    names.write_text('﻿"lang"\n{\n\t"Tokens"\n\t{\n\t\t"hero_punkgoat:n" "Billy"\n'
                     '\t\t"hero_punkgoat_search:n" "Billy"\n\t\t"hero_atlas:n" "Abrams"\n\t}\n}\n', encoding="utf-8")
    vdata = container([("DATA", encode(VDATA))])
    write_vpk(citadel / "pak01_dir.vpk", {"scripts/heroes.vdata_c": vdata})
    cache = tmp_path / "heroes.json"
    hs = read_game_heroes(citadel, cache)
    assert {h.name for h in hs} >= {"Billy", "Abrams"} and cache.is_file()
    # the second read comes from the cache: the archive isn't opened again
    import sapphire.vpk as vpk_mod

    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("read the archive again")
    real = vpk_mod.VpkReader
    vpk_mod.VpkReader = Boom
    try:
        assert {h.name for h in read_game_heroes(citadel, cache)} == {h.name for h in hs}
    finally:
        vpk_mod.VpkReader = real


def test_falls_back_to_built_in_list_without_a_game(tmp_path):
    hi = HeroIndex.for_game(None)
    assert "Billy" in hi.names and "Celeste" in hi.names and "Kali" not in hi.names
    assert hi.classify("models/heroes_wip/punkgoat/punkgoat.vmdl_c") == ("Billy", "model")
    assert hi.classify("panorama/images/heroes/kali_card_psd.vtex_c") == ("Vyper", "portraits")
    broken = tmp_path / "citadel"
    broken.mkdir()
    (broken / "pak01_dir.vpk").write_bytes(b"not a vpk at all")
    assert "Billy" in HeroIndex.for_game(broken).names


def test_manager_flags_the_sound_mod(tmp_path):
    from helpers import make_vpk
    from sapphire.core import Manager
    from sapphire.library import InstalledMod, Library, StoredFile, StoredVpk
    lib = Library()
    mgr = Manager(lib)
    mod = InstalledMod(uid="gb-Sound-85955", name="Celeste Balatro Mult Ult", model="Sound",
                       category="Other/Misc", vpks=[StoredVpk("pak01_dir.vpk", [StoredFile("00_pak01_dir.vpk")])])
    mod.folder.mkdir(parents=True)
    make_vpk(mod.folder / "00_pak01_dir.vpk", {p: b"x" for p in BALATRO})
    lib.add(mod)
    assert mgr.hero_surprises(mod) == ["Billy"]     # built-in hero list: no game here
    assert mgr.hero_changes(mod).describe("Billy") == "model, textures, portraits"
