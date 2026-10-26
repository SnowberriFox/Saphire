"""Which heroes a mod actually changes, worked out from the files it ships.

GameBanana titles and categories are written by hand and can be wrong: a sound
mod can carry a whole reskin, a "Billy" skin can really change Celeste. So
Sapphire reads the game's own hero list (scripts/heroes.vdata_c: each hero's
model folder, portrait images, name logo and menu scenes, plus their names from
the game's localisation) and matches a mod's file paths against it. Renamed
heroes (Vyper's portraits are still "kali_*", Abrams's are "bull_*") and new
heroes come out right without Sapphire knowing about them in advance.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

NAMES_FILE = Path("resource/localization/citadel_gc_hero_names/citadel_gc_hero_names_english.txt")
_NAME_ENTRY = re.compile(r'"hero_([a-z0-9_]+):n"\s+"([^"]+)"')
_NOT_HEROES = {"base", "targetdummy", "genericperson", "testhero"}
KINDS = ("model", "textures", "portraits", "menu scenes")

# What the game said in October 2026, used when it can't be read:
# codename: [name, model folder, portrait prefixes, name logos, menu scenes]
FALLBACK = json.loads(r'''{
    "astro": ["Holliday", "models/heroes_staging/astro/", ["astro"], ["holliday", "holliday_localized"], ["maps/ui/hero_postgame_portrait/astro_postgame_portrait", "maps/ui/hero_prefabs/astro", "maps/ui/hero_shop/astro_shop", "maps/ui/team_reveal_hero/astro_team_reveal"]],
    "atlas": ["Abrams", "models/heroes_wip/abrams/", ["bull"], ["abrams", "abrams_localized"], ["maps/ui/hero_postgame_portrait/abrams_postgame_portrait", "maps/ui/hero_prefabs/abrams", "maps/ui/hero_shop/abrams_shop", "maps/ui/team_reveal_hero/abrams_team_reveal"]],
    "bebop": ["Bebop", "models/heroes_staging/bebop/", ["bebop"], ["bebop", "bebop_localized"], ["maps/ui/hero_postgame_portrait/bebop_postgame_portrait", "maps/ui/hero_prefabs/bebop", "maps/ui/hero_shop/bebop_shop", "maps/ui/team_reveal_hero/bebop_team_reveal"]],
    "bookworm": ["Paige", "models/heroes_wip/bookworm/", ["bookworm"], ["paige", "paige_localized"], ["maps/ui/hero_postgame_portrait/bookworm_postgame_portrait", "maps/ui/hero_prefabs/bookworm", "maps/ui/hero_shop/bookworm_shop", "maps/ui/team_reveal_hero/bookworm_team_reveal"]],
    "chessmaster": ["Solomon", "models/heroes_wip/chessmaster/", ["chessmaster"], ["solomon", "solomon_localized"], ["maps/ui/hero_postgame_portrait/chessmaster_postgame_portrait", "maps/ui/hero_prefabs/chessmaster", "maps/ui/hero_shop/chessmaster_shop", "maps/ui/team_reveal_hero/chessmaster_team_reveal"]],
    "chrono": ["Paradox", "models/heroes_staging/chrono/", ["chrono"], ["paradox", "paradox_localized"], ["maps/ui/hero_postgame_portrait/chrono_postgame_portrait", "maps/ui/hero_prefabs/chrono", "maps/ui/hero_shop/chrono_shop", "maps/ui/team_reveal_hero/chrono_team_reveal"]],
    "deadpack": ["Deadman Danny", "models/heroes_wip/deadpack/", ["deadpack"], ["deadpack", "deadpack_localized"], ["maps/ui/hero_postgame_portrait/deadpack_postgame_portrait", "maps/ui/hero_prefabs/deadpack", "maps/ui/hero_shop/deadpack_shop", "maps/ui/team_reveal_hero/deadpack_team_reveal"]],
    "doorman": ["The Doorman", "models/heroes_wip/doorman_v2/", ["doorman"], ["doorman", "doorman_localized"], ["maps/ui/hero_postgame_portrait/doorman_postgame_portrait", "maps/ui/hero_prefabs/doorman", "maps/ui/hero_shop/doorman_shop", "maps/ui/team_reveal_hero/doorman_team_reveal"]],
    "drifter": ["Drifter", "models/heroes_wip/drifter/", ["drifter"], ["drifter", "drifter_localized"], ["maps/ui/hero_postgame_portrait/drifter_postgame_portrait", "maps/ui/hero_prefabs/drifter", "maps/ui/hero_shop/drifter_shop", "maps/ui/team_reveal_hero/drifter_team_reveal"]],
    "dynamo": ["Dynamo", "models/heroes_wip/dynamo/", ["sumo"], ["dynamo", "dynamo_localized"], ["maps/ui/hero_postgame_portrait/prof_dynamo_postgame_portrait", "maps/ui/hero_prefabs/prof_dynamo", "maps/ui/hero_shop/prof_dynamo_shop", "maps/ui/team_reveal_hero/prof_dynamo_team_reveal"]],
    "familiar": ["Rem", "models/heroes_wip/familiar/", ["familiar"], ["familiar", "familiar_localized"], ["maps/ui/hero_postgame_portrait/familiar_postgame_portrait", "maps/ui/hero_prefabs/familiar", "maps/ui/hero_shop/familiar_shop", "maps/ui/team_reveal_hero/familiar_team_reveal"]],
    "fencer": ["Apollo", "models/heroes_wip/fencer/", ["fencer"], ["fencer", "fencer_localized"], ["maps/ui/hero_postgame_portrait/apollo_postgame_portrait", "maps/ui/hero_prefabs/apollo", "maps/ui/hero_shop/apollo_shop", "maps/ui/team_reveal_hero/apollo_team_reveal"]],
    "forge": ["McGinnis", "models/heroes_wip/mcginnis/", ["engineer"], ["mcginnis", "mcginnis_localized"], ["maps/ui/hero_postgame_portrait/engineer_postgame_portrait", "maps/ui/hero_prefabs/forge", "maps/ui/hero_shop/engineer_shop", "maps/ui/team_reveal_hero/engineer_team_reveal"]],
    "frank": ["Victor", "models/heroes_wip/frank/", ["frank"], ["victor", "victor_localized"], ["maps/ui/hero_postgame_portrait/frank_postgame_portrait", "maps/ui/hero_prefabs/frank", "maps/ui/hero_shop/frank_shop", "maps/ui/team_reveal_hero/frank_team_reveal"]],
    "ghost": ["Lady Geist", "models/heroes_wip/geist/", ["spectre"], ["lady_geist", "lady_geist_localized"], ["maps/ui/hero_postgame_portrait/ghost_postgame_portrait", "maps/ui/hero_prefabs/geist", "maps/ui/hero_shop/ghost_shop", "maps/ui/team_reveal_hero/ghost_team_reveal"]],
    "gigawatt": ["Seven", "models/heroes_staging/gigawatt_prisoner/", ["gigawatt"], ["seven", "seven_localized"], ["maps/ui/hero_postgame_portrait/gigawatt_postgame_portrait", "maps/ui/hero_prefabs/gigawatt", "maps/ui/hero_shop/gigawatt_shop", "maps/ui/team_reveal_hero/gigawatt_team_reveal"]],
    "haze": ["Haze", "models/heroes_staging/haze/", ["haze"], ["haze", "haze_localized"], ["maps/ui/hero_postgame_portrait/haze_postgame_portrait", "maps/ui/hero_prefabs/haze", "maps/ui/hero_shop/haze_shop", "maps/ui/team_reveal_hero/haze_team_reveal"]],
    "hornet": ["Vindicta", "models/heroes_staging/hornet_v3/", ["hornet"], ["vindicta", "vindicta_localized"], ["maps/ui/hero_postgame_portrait/hornet_postgame_portrait", "maps/ui/hero_prefabs/hornet", "maps/ui/hero_shop/hornet_shop", "maps/ui/team_reveal_hero/hornet_team_reveal"]],
    "inferno": ["Infernus", "models/heroes_wip/inferno/", ["inferno"], ["infernus", "infernus_localized"], ["maps/ui/hero_postgame_portrait/inferno_postgame_portrait", "maps/ui/hero_prefabs/inferno", "maps/ui/hero_shop/inferno_shop", "maps/ui/team_reveal_hero/inferno_team_reveal"]],
    "kelvin": ["Kelvin", "models/heroes_staging/kelvin_v2/", ["kelvin"], ["kelvin", "kelvin_localized"], ["maps/ui/hero_postgame_portrait/kelvin_postgame_portrait", "maps/ui/hero_prefabs/kelvin", "maps/ui/hero_shop/kelvin_shop", "maps/ui/team_reveal_hero/kelvin_team_reveal"]],
    "krill": ["Mo & Krill", "models/heroes_staging/digger/", ["digger"], ["mo_krill", "mo_krill_localized"], ["maps/ui/hero_postgame_portrait/digger_postgame_portrait", "maps/ui/hero_prefabs/digger", "maps/ui/hero_shop/digger_shop", "maps/ui/team_reveal_hero/digger_team_reveal"]],
    "lash": ["Lash", "models/heroes_wip/lash/", ["lash"], ["lash", "lash_localized"], ["maps/ui/hero_postgame_portrait/lash_postgame_portrait", "maps/ui/hero_prefabs/lash", "maps/ui/hero_shop/lash_shop", "maps/ui/team_reveal_hero/lash_team_reveal"]],
    "magician": ["Sinclair", "models/heroes_staging/magician_v2/", ["magician"], ["sinclair", "sinclair_localized"], ["maps/ui/hero_postgame_portrait/sinclair_postgame_portrait", "maps/ui/hero_prefabs/magician", "maps/ui/hero_shop/gigawatt_shop", "maps/ui/team_reveal_hero/sinclair_team_reveal"]],
    "mirage": ["Mirage", "models/heroes_staging/mirage_v2/", ["mirage"], ["mirage", "mirage_localized"], ["maps/ui/hero_postgame_portrait/mirage_postgame_portrait", "maps/ui/hero_prefabs/mirage", "maps/ui/hero_shop/mirage_shop", "maps/ui/team_reveal_hero/mirage_team_reveal"]],
    "nano": ["Calico", "models/heroes_staging/nano/nano_v2/", ["nano"], ["calico", "calico_localized"], ["maps/ui/hero_postgame_portrait/nano_postgame_portrait", "maps/ui/hero_prefabs/nano", "maps/ui/hero_shop/nano_shop", "maps/ui/team_reveal_hero/nano_team_reveal"]],
    "necro": ["Graves", "models/heroes_wip/necro/", ["necro"], ["necro", "necro_localized"], ["maps/ui/hero_postgame_portrait/necro_postgame_portrait", "maps/ui/hero_prefabs/necro", "maps/ui/hero_shop/necro_shop", "maps/ui/team_reveal_hero/necro_team_reveal"]],
    "nurse": ["Nurse Harrow", "models/heroes_wip/nurse/", ["nurse"], ["nurse", "nurse_localized"], ["maps/ui/hero_postgame_portrait/nurse_postgame_portrait", "maps/ui/hero_prefabs/nurse", "maps/ui/hero_shop/nurse_shop", "maps/ui/team_reveal_hero/nurse_team_reveal"]],
    "orion": ["Grey Talon", "models/heroes_staging/archer/", ["archer"], ["grey_talon", "grey_talon_localized"], ["maps/ui/hero_postgame_portrait/gray_talon_postgame_portrait", "maps/ui/hero_prefabs/archer", "maps/ui/hero_shop/gray_talon_shop", "maps/ui/team_reveal_hero/gray_talon_team_reveal"]],
    "priest": ["Venator", "models/heroes_wip/priest/", ["priest"], ["priest", "priest_localized"], ["maps/ui/hero_postgame_portrait/priest_postgame_portrait", "maps/ui/hero_prefabs/priest", "maps/ui/hero_shop/priest_shop", "maps/ui/team_reveal_hero/priest_team_reveal"]],
    "punkgoat": ["Billy", "models/heroes_wip/punkgoat/", ["punkgoat"], ["billy", "billy_localized"], ["maps/ui/hero_postgame_portrait/punkgoat_postgame_portrait", "maps/ui/hero_prefabs/punkgoat", "maps/ui/hero_shop/punkgoat_shop", "maps/ui/team_reveal_hero/punkgoat_team_reveal"]],
    "ratking": ["Rat King", "models/heroes_wip/ratking/", ["ratking"], ["ratking", "ratking_localized"], ["maps/ui/hero_postgame_portrait/ratking_postgame_portrait", "maps/ui/hero_prefabs/ratking", "maps/ui/hero_shop/ratking_shop", "maps/ui/team_reveal_hero/ratking_team_reveal"]],
    "shiv": ["Shiv", "models/heroes_staging/shiv/", ["shiv"], ["shiv", "shiv_localized"], ["maps/ui/hero_postgame_portrait/shiv_postgame_portrait", "maps/ui/hero_prefabs/shiv", "maps/ui/hero_shop/shiv_shop", "maps/ui/team_reveal_hero/shiv_team_reveal"]],
    "synth": ["Pocket", "models/heroes_wip/pocket/", ["synth"], ["pocket", "pocket_localized"], ["maps/ui/hero_postgame_portrait/pocket_postgame_portrait", "maps/ui/hero_prefabs/pocket", "maps/ui/hero_shop/pocket_shop", "maps/ui/team_reveal_hero/pocket_team_reveal"]],
    "tengu": ["Ivy", "models/heroes_wip/ivy/", ["tengu"], ["ivy", "ivy_localized"], ["maps/ui/hero_postgame_portrait/tengu_postgame_portrait", "maps/ui/hero_prefabs/tengu", "maps/ui/hero_shop/tengu_shop", "maps/ui/team_reveal_hero/tengu_team_reveal"]],
    "unicorn": ["Celeste", "models/heroes_wip/unicorn/", ["unicorn"], ["unicorn", "unicorn_localized"], ["maps/ui/hero_postgame_portrait/unicorn_postgame_portrait", "maps/ui/hero_prefabs/unicorn", "maps/ui/hero_shop/unicorn_shop", "maps/ui/team_reveal_hero/unicorn_team_reveal"]],
    "vampirebat": ["Mina", "models/heroes_wip/vampirebat/", ["vampirebat"], ["mina", "mina_localized"], ["maps/ui/hero_postgame_portrait/vampirebat_postgame_portrait", "maps/ui/hero_prefabs/vampirebat", "maps/ui/hero_shop/vampirebat_shop", "maps/ui/team_reveal_hero/vampirebat_team_reveal"]],
    "viper": ["Vyper", "models/heroes_staging/viper/", ["kali"], ["vyper", "vyper_localized"], ["maps/ui/hero_postgame_portrait/viper_postgame_portrait", "maps/ui/hero_prefabs/viper", "maps/ui/hero_shop/viper_shop", "maps/ui/team_reveal_hero/viper_team_reveal"]],
    "viscous": ["Viscous", "models/heroes_staging/viscous/", ["viscous"], ["viscous", "viscous_localized"], ["maps/ui/hero_postgame_portrait/viscous_postgame_portrait", "maps/ui/hero_prefabs/viscous", "maps/ui/hero_shop/viscous_shop", "maps/ui/team_reveal_hero/viscous_team_reveal"]],
    "warden": ["Warden", "models/heroes_staging/warden/", ["warden"], ["warden", "warden_localized"], ["maps/ui/hero_postgame_portrait/warden_postgame_portrait", "maps/ui/hero_prefabs/warden", "maps/ui/hero_shop/warden_shop", "maps/ui/team_reveal_hero/warden_team_reveal"]],
    "werewolf": ["Silver", "models/heroes_wip/werewolf/", ["werewolf"], ["werewolf", "werewolf_localized"], ["maps/ui/hero_postgame_portrait/werewolf_postgame_portrait", "maps/ui/hero_prefabs/werewolf", "maps/ui/hero_shop/werewolf_shop", "maps/ui/team_reveal_hero/werewolf_team_reveal"]],
    "wraith": ["Wraith", "models/heroes_wip/wraith/", ["wraith"], ["wraith", "wraith_localized"], ["maps/ui/hero_postgame_portrait/wraith_postgame_portrait", "maps/ui/hero_prefabs/wraith", "maps/ui/hero_shop/wraith_shop", "maps/ui/team_reveal_hero/wraith_team_reveal"]],
    "yamato": ["Yamato", "models/heroes_staging/yamato_v2/", ["yamato"], ["yamato", "yamato_localized"], ["maps/ui/hero_postgame_portrait/yamato_postgame_portrait", "maps/ui/hero_prefabs/yamato", "maps/ui/hero_shop/yamato_shop", "maps/ui/team_reveal_hero/yamato_team_reveal"]]
}''')


@dataclass
class Hero:
    codename: str
    name: str
    model_dir: str = ""                                  # "models/heroes_wip/abrams/"
    images: set[str] = field(default_factory=set)        # portrait file prefixes: {"bull"}
    logos: set[str] = field(default_factory=set)         # hero_names/<x>.vsvg_c: {"abrams", "abrams_localized"}
    scenes: set[str] = field(default_factory=set)        # "maps/ui/hero_shop/abrams_shop", ...


@dataclass
class HeroChanges:
    kinds: dict[str, set[str]] = field(default_factory=dict)   # hero name -> {"model", "textures", ...}

    @property
    def reskinned(self) -> set[str]:
        """Heroes whose look in a match changes (model or textures)."""
        return {h for h, k in self.kinds.items() if k & {"model", "textures"}}

    def describe(self, hero: str) -> str:
        return ", ".join(k for k in KINDS if k in self.kinds.get(hero, ()))


def _strip_image(path: str) -> str:
    # "file://{images}/heroes/bull_card.psd" -> "bull_card"
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def heroes_from_vdata(data: dict, names: dict[str, str]) -> list[Hero]:
    out = []
    for key, h in data.items():
        if not key.startswith("hero_") or not isinstance(h, dict):
            continue
        code = key[5:]
        if code in _NOT_HEROES or h.get("m_bDisabled") or h.get("m_bInDevelopment"):
            continue
        model = str(h.get("m_strModelName") or "")
        if not model.startswith("models/heroes") or "/gen_man/" in model:
            continue
        hero = Hero(code, names.get(code) or code.replace("_", " ").title(), model_dir=model.rsplit("/", 1)[0] + "/")
        cards = []
        for k, v in h.items():
            if not isinstance(v, str):
                continue
            if v.startswith("file://{images}/heroes/hero_names/"):
                hero.logos.add(_strip_image(v))
            elif v.startswith("file://{images}/heroes/"):
                cards.append(_strip_image(v))
            elif v.startswith("maps/ui/") and v.endswith(".vmap"):
                hero.scenes.add(v[:-5])
        if cards:
            # bull_sm, bull_mm, bull_card... -> "bull"
            hero.images.add(min(cards, key=len).split("_")[0])
        out.append(hero)
    return out


def load_names(citadel: Path | None) -> dict[str, str]:
    if citadel:
        try:
            text = (Path(citadel) / NAMES_FILE).read_text(encoding="utf-8-sig", errors="replace")
            return {k: v for k, v in _NAME_ENTRY.findall(text) if not k.endswith(("_search", "_sort"))}
        except OSError:
            pass
    return {}


def fallback_heroes() -> list[Hero]:
    return [Hero(code, name, model_dir, set(images), set(logos), set(scenes))
            for code, (name, model_dir, images, logos, scenes) in FALLBACK.items()]


def read_game_heroes(citadel: Path, cache_file: Path | None = None) -> list[Hero] | None:
    """The playable heroes, from the game's files (cached until the game updates)."""
    from sapphire import kv3
    from sapphire.resource import Resource
    from sapphire.vpk import VpkReader
    pak = Path(citadel) / "pak01_dir.vpk"
    try:
        st = pak.stat()
    except OSError:
        return None
    sig = [st.st_size, st.st_mtime_ns]
    if cache_file:
        try:
            cached = json.loads(cache_file.read_text())
            if cached.get("sig") == sig:
                return [Hero(h["codename"], h["name"], h["model_dir"], set(h["images"]), set(h["logos"]),
                             set(h["scenes"])) for h in cached["heroes"]]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    try:
        raw = VpkReader(pak).read("scripts/heroes.vdata_c")
        data = kv3.decode(Resource(raw).first("DATA")).value
    except Exception as exc:  # noqa: BLE001 - any trouble reading it: use the built-in list
        log.warning("heroes: couldn't read the game's hero list (%s)", exc)
        return None
    heroes = heroes_from_vdata(data, load_names(citadel))
    if cache_file and heroes:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps({"sig": sig, "heroes": [
                {"codename": h.codename, "name": h.name, "model_dir": h.model_dir, "images": sorted(h.images),
                 "logos": sorted(h.logos), "scenes": sorted(h.scenes)} for h in heroes]}))
        except OSError:
            pass
    return heroes


class HeroIndex:
    def __init__(self, heroes: list[Hero]):
        self.heroes = heroes
        self._dirs = sorted(((h.model_dir, h.name) for h in heroes if h.model_dir), key=lambda x: -len(x[0]))
        self._images = {p: h.name for h in heroes for p in h.images}
        self._logos = {p: h.name for h in heroes for p in h.logos}
        self._scenes = sorted(((p, h.name) for h in heroes for p in h.scenes), key=lambda x: -len(x[0]))
        self.names = sorted({h.name for h in heroes})

    @classmethod
    def for_game(cls, citadel: Path | None, cache_file: Path | None = None) -> "HeroIndex":
        heroes = read_game_heroes(citadel, cache_file) if citadel else None
        return cls(heroes or fallback_heroes())

    def classify(self, path: str) -> tuple[str, str] | None:
        """(hero name, kind) for one file in a mod, or None if it's not hero-specific."""
        p = path.lower()
        if p.startswith("models/heroes"):
            for d, name in self._dirs:
                if p.startswith(d):
                    return name, ("model" if p.endswith(".vmdl_c") else "textures")
            return None
        if p.startswith("panorama/images/heroes/"):
            rest = p[len("panorama/images/heroes/"):]
            stem = rest.rsplit(".", 1)[0]
            if rest.startswith("hero_names/"):
                name = self._logos.get(stem[len("hero_names/"):])
                return (name, "portraits") if name else None
            name = self._images.get(stem.split("_")[0])
            return (name, "portraits") if name else None
        if p.startswith("maps/ui/"):
            for s, name in self._scenes:
                if p == s + ".vpk" or p.startswith(s + "/"):
                    return name, "menu scenes"
        return None

    def changes(self, paths) -> HeroChanges:
        out = HeroChanges()
        for path in paths:
            hit = self.classify(path)
            if hit:
                out.kinds.setdefault(hit[0], set()).add(hit[1])
        return out

    def mentioned(self, *texts: str) -> set[str]:
        """Heroes named in a mod's title or category."""
        blob = " ".join(texts).lower()
        found = set()
        for name in self.names:
            words = [name.lower(), name.lower().removeprefix("the ")]
            if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", blob) for w in words):
                found.add(name)
        return found


def surprises(changes: HeroChanges, title: str, category: str, model: str, index: HeroIndex) -> list[str]:
    """Heroes a mod reskins without saying so: worth a heads-up.

    A skin that names no hero at all ("Faithful/Vanilla+") gets the benefit of
    the doubt; anything else that changes a hero it doesn't mention is flagged
    (a sound mod carrying a reskin, a "Billy" skin that really changes Celeste)."""
    extra = changes.reskinned - index.mentioned(title, category)
    if not extra:
        return []
    said = index.mentioned(title, category)
    if model == "Mod" and category.lower().startswith("skins") and not said:
        return []
    return sorted(extra)
