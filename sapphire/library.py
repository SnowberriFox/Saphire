"""Sapphire's own record of installed mods, load order and profiles.

Everything lives in one JSON file written atomically, so a crash or power cut
mid-save can never leave you with a half-written state.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sapphire import paths

log = logging.getLogger(__name__)

SCHEMA = 1


@dataclass
class StoredFile:
    stored: str              # filename inside library/<uid>/
    chunk: str | None = None  # None for the main/_dir file, "000", "001"... for data chunks


@dataclass
class StoredVpk:
    label: str                       # path inside the original archive, e.g. "Blue/pak01_dir.vpk"
    files: list[StoredFile] = field(default_factory=list)
    active: bool = True              # variants you haven't picked stay in the library, switched off

    @property
    def main(self) -> StoredFile:
        return next(f for f in self.files if f.chunk is None)


@dataclass
class UpdateInfo:
    file_id: int
    file_name: str
    date: int


@dataclass
class InstalledMod:
    uid: str
    name: str
    source: str = "gamebanana"       # "gamebanana" or "local"
    model: str = "Mod"
    gb_id: int = 0
    url: str = ""
    author: str = ""
    category: str = ""
    thumb_url: str = ""
    nsfw: bool = False
    file_id: int = 0
    file_name: str = ""
    file_date: int = 0
    vpks: list[StoredVpk] = field(default_factory=list)
    enabled: bool = True
    installed_at: int = 0
    updated_at: int = 0
    update: UpdateInfo | None = None
    note: str = ""
    audio_url: str = ""               # GameBanana's preview clip, for sound mods
    previous: dict | None = None      # the version before the last update, for roll back
    skip_file_id: int = 0             # rolled back from this file: auto-update leaves it alone

    @property
    def folder(self) -> Path:
        return paths.library_dir() / self.uid

    def file_path(self, f: StoredFile) -> Path:
        return self.folder / f.stored

    @property
    def active_vpks(self) -> list[StoredVpk]:
        return [v for v in self.vpks if v.active]

    @classmethod
    def from_dict(cls, d: dict) -> "InstalledMod":
        d = dict(d)
        vpks = [StoredVpk(label=v.get("label", ""), active=bool(v.get("active", True)),
                          files=[StoredFile(**f) for f in v.get("files", [])])
                for v in d.pop("vpks", [])]
        upd = d.pop("update", None)
        known = set(cls.__dataclass_fields__)
        mod = cls(**{k: v for k, v in d.items() if k in known}, vpks=vpks)
        mod.update = UpdateInfo(**upd) if isinstance(upd, dict) else None
        return mod


@dataclass
class Profile:
    name: str
    entries: list[tuple[str, bool]] = field(default_factory=list)  # (uid, enabled) in load order
    saved_at: int = 0
    origin: str = ""   # "" = made here; otherwise the manager it was imported from


@dataclass
class Settings:
    hide_nsfw: bool = True
    hide_installed: bool = False
    hide_obsolete: bool = True
    auto_apply: bool = True
    per_page: int = 30
    onboarded: bool = False
    view_mode: str = "grid"          # Browse: "grid" or "list"
    ui_scale: str = "Normal"         # see theme.SCALES
    theme_preset: str = "Sapphire"   # see theme.PRESETS
    theme_colors: dict = field(default_factory=dict)   # token -> hex overrides
    installed_view: str = "grid"     # Installed page: "grid" or "list"
    discord_presence: bool = False
    discord_app_id: str = ""
    fix_camera: bool = True          # repair the first-person camera on skins made before the camera update
    auto_update: bool = False        # install mod updates as soon as a check finds them
    one_skin_per_hero: bool = False  # turning a skin on turns the hero's other skins off
    helper: bool = False             # background helper that keeps gameinfo.gi patched
    favourites_only: bool = False    # Browse filter


class Library:
    def __init__(self, state_path: Path | None = None):
        self.path = state_path or paths.state_file()
        self.game_dir: str | None = None
        self.settings = Settings()
        self.mods: dict[str, InstalledMod] = {}
        self.order: list[str] = []  # index 0 = highest priority (wins conflicts)
        self.profiles: dict[str, Profile] = {}
        self.active_profile: str | None = None
        self.deployed: dict[str, dict] = {}  # "addons/pak01_dir.vpk" -> {src,size,mtime_ns}
        self.favourites: dict[str, dict] = {}  # "Mod:123" -> the submission as last seen
        self.load()

    # ------------------------------------------------------------- persistence
    def load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            # Keep the broken file for inspection instead of silently losing it.
            bad = self.path.with_name(f"state.broken-{int(time.time())}.json")
            log.error("state.json unreadable (%s); moved to %s", exc, bad)
            try:
                self.path.rename(bad)
            except OSError:
                pass
            return
        self.game_dir = data.get("game_dir")
        s = data.get("settings") or {}
        self.settings = Settings(**{k: v for k, v in s.items() if k in Settings.__dataclass_fields__})
        if not isinstance(self.settings.theme_colors, dict):
            self.settings.theme_colors = {}
        for uid, raw in (data.get("mods") or {}).items():
            try:
                self.mods[uid] = InstalledMod.from_dict(raw)
            except (TypeError, StopIteration) as exc:
                log.error("skipping corrupt mod entry %s: %s", uid, exc)
        self.order = [u for u in data.get("order") or [] if u in self.mods]
        for uid in self.mods:  # anything missing from order goes to the bottom
            if uid not in self.order:
                self.order.append(uid)
        for name, raw in (data.get("profiles") or {}).items():
            self.profiles[name] = Profile(name=name, saved_at=raw.get("saved_at", 0),
                                          origin=str(raw.get("origin") or ""),
                                          entries=[(u, bool(e)) for u, e in raw.get("entries", [])])
        self.active_profile = data.get("active_profile")
        self.deployed = data.get("deployed") or {}
        fav = data.get("favourites") or {}
        self.favourites = {k: v for k, v in fav.items() if isinstance(v, dict)} if isinstance(fav, dict) else {}

    def save(self) -> None:
        data = {
            "schema": SCHEMA,
            "game_dir": self.game_dir,
            "settings": asdict(self.settings),
            "mods": {uid: asdict(m) for uid, m in self.mods.items()},
            "order": self.order,
            "profiles": {n: {"entries": [list(e) for e in p.entries], "saved_at": p.saved_at, "origin": p.origin}
                         for n, p in self.profiles.items()},
            "active_profile": self.active_profile,
            "deployed": self.deployed,
            "favourites": self.favourites,
        }
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ helpers
    def ordered(self) -> list[InstalledMod]:
        return [self.mods[u] for u in self.order if u in self.mods]

    def enabled_in_order(self) -> list[InstalledMod]:
        return [m for m in self.ordered() if m.enabled]

    def by_gb(self, model: str, gb_id: int) -> InstalledMod | None:
        """The main entry for a GameBanana mod, or any extra file of it if the main one is gone."""
        main = self.mods.get(f"gb-{model}-{gb_id}")
        if main is not None:
            return main
        return next(iter(self.by_gb_all(model, gb_id)), None)

    def by_gb_all(self, model: str, gb_id: int) -> list[InstalledMod]:
        """Every entry of a GameBanana mod: its main file plus any extra files added alongside."""
        key = f"gb-{model}-{gb_id}"
        found = [m for m in self.ordered()
                 if m.source == "gamebanana" and m.model == model and m.gb_id == gb_id]
        return sorted(found, key=lambda m: m.uid != key)  # main entry first, then load order

    def by_gb_file(self, model: str, gb_id: int, file_id: int) -> InstalledMod | None:
        return next((m for m in self.by_gb_all(model, gb_id) if m.file_id == file_id), None)

    # --------------------------------------------------------------- favourites
    def is_favourite(self, model: str, gb_id: int) -> bool:
        return f"{model}:{gb_id}" in self.favourites

    def toggle_favourite(self, sub) -> bool:
        """Star or unstar a GameBanana submission. Returns True if it's now a favourite."""
        key = f"{sub.model}:{sub.id}"
        if key in self.favourites:
            del self.favourites[key]
            return False
        data = asdict(sub)
        data["starred_at"] = int(time.time())
        self.favourites[key] = data
        return True

    def favourite_submissions(self) -> list:
        from sapphire.gamebanana import Submission
        known = set(Submission.__dataclass_fields__)
        out = []
        for data in sorted(self.favourites.values(), key=lambda d: -int(d.get("starred_at") or 0)):
            try:
                out.append(Submission(**{k: v for k, v in data.items() if k in known}))
            except TypeError:
                continue
        return out

    def add(self, mod: InstalledMod, top: bool = True) -> None:
        self.mods[mod.uid] = mod
        if mod.uid in self.order:
            return
        if top:
            self.order.insert(0, mod.uid)
        else:
            self.order.append(mod.uid)

    def remove(self, uid: str) -> InstalledMod | None:
        mod = self.mods.pop(uid, None)
        if uid in self.order:
            self.order.remove(uid)
        return mod

    def set_order(self, uids: list[str]) -> None:
        seen = [u for u in uids if u in self.mods]
        rest = [u for u in self.order if u not in seen]
        self.order = seen + rest

    # ----------------------------------------------------------------- profiles
    def snapshot(self, name: str) -> Profile:
        prof = Profile(name=name, saved_at=int(time.time()),
                       entries=[(m.uid, m.enabled) for m in self.ordered()])
        self.profiles[name] = prof
        self.active_profile = name
        return prof

    def restore(self, name: str) -> list[str]:
        """Apply a profile's order and enabled flags. Returns uids it lists that are gone."""
        prof = self.profiles[name]
        missing = [u for u, _ in prof.entries if u not in self.mods]
        listed = [u for u, _ in prof.entries if u in self.mods]
        flags = dict(prof.entries)
        for uid, mod in self.mods.items():
            mod.enabled = bool(flags.get(uid, False))  # mods not in the profile are off
        self.set_order(listed)
        self.active_profile = name
        return missing
