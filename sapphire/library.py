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

    @property
    def folder(self) -> Path:
        return paths.library_dir() / self.uid

    def file_path(self, f: StoredFile) -> Path:
        return self.folder / f.stored

    @classmethod
    def from_dict(cls, d: dict) -> "InstalledMod":
        d = dict(d)
        vpks = [StoredVpk(label=v.get("label", ""),
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


@dataclass
class Settings:
    hide_nsfw: bool = True
    hide_installed: bool = False
    hide_obsolete: bool = True
    auto_apply: bool = True
    per_page: int = 30
    onboarded: bool = False


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
                                          entries=[(u, bool(e)) for u, e in raw.get("entries", [])])
        self.active_profile = data.get("active_profile")
        self.deployed = data.get("deployed") or {}

    def save(self) -> None:
        data = {
            "schema": SCHEMA,
            "game_dir": self.game_dir,
            "settings": asdict(self.settings),
            "mods": {uid: asdict(m) for uid, m in self.mods.items()},
            "order": self.order,
            "profiles": {n: {"entries": [list(e) for e in p.entries], "saved_at": p.saved_at}
                         for n, p in self.profiles.items()},
            "active_profile": self.active_profile,
            "deployed": self.deployed,
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
        return self.mods.get(f"gb-{model}-{gb_id}")

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
