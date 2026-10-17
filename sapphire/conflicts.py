"""Which enabled mods overwrite the same game files, and who wins."""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from sapphire import paths
from sapphire.library import InstalledMod
from sapphire.vpk import VpkError, list_entries

log = logging.getLogger(__name__)

# Files nearly every mod ships that don't indicate a real clash.
IGNORED = ("addoninfo.txt", "readme", "license", "credits")


@dataclass
class Clash:
    other_uid: str
    files: list[str]
    wins: bool  # True if *this* mod wins against other_uid


@dataclass
class ModConflicts:
    uid: str
    clashes: list[Clash] = field(default_factory=list)

    @property
    def losing(self) -> int:
        return sum(len(c.files) for c in self.clashes if not c.wins)

    @property
    def winning(self) -> int:
        return sum(len(c.files) for c in self.clashes if c.wins)


class VpkIndex:
    """Caches VPK file listings by (path, size, mtime) on disk."""

    def __init__(self, cache_file: Path | None = None):
        self.cache_file = cache_file or paths.cache_dir() / "vpk-index.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        try:
            self._data = json.loads(self.cache_file.read_text())
        except (OSError, ValueError):
            self._data = {}
        self._dirty = False

    def entries(self, path: Path) -> list[str]:
        try:
            st = path.stat()
        except OSError:
            return []
        key = str(path)
        sig = [st.st_size, st.st_mtime_ns]
        with self._lock:
            hit = self._data.get(key)
            if hit and hit.get("sig") == sig:
                return hit["entries"]
        try:
            entries = [e for e in list_entries(path) if not e.startswith(IGNORED)]
        except (VpkError, OSError) as exc:
            log.warning("can't read %s: %s", path, exc)
            entries = []
        with self._lock:
            self._data[key] = {"sig": sig, "entries": entries}
            self._dirty = True
        return entries

    def save(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            live = {k: v for k, v in self._data.items() if Path(k).exists()}
            try:
                self.cache_file.write_text(json.dumps(live))
                self._dirty = False
            except OSError as exc:
                log.warning("couldn't save vpk index: %s", exc)


def compute(mods_in_order: list[InstalledMod], index: VpkIndex) -> dict[str, ModConflicts]:
    """Conflicts among enabled mods. First in the list has the highest priority."""
    owners: dict[str, list[str]] = defaultdict(list)
    for mod in mods_in_order:
        if not mod.enabled:
            continue
        seen: set[str] = set()
        for vpk in mod.active_vpks:
            for entry in index.entries(mod.file_path(vpk.main)):
                if entry not in seen:
                    seen.add(entry)
                    owners[entry].append(mod.uid)
    index.save()

    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry, uids in owners.items():
        if len(uids) < 2:
            continue
        for i, a in enumerate(uids):
            for b in uids[i + 1:]:
                pairs[(a, b)].append(entry)  # a is higher priority -> a wins

    result: dict[str, ModConflicts] = {}
    for (winner, loser), files in pairs.items():
        files.sort()
        result.setdefault(winner, ModConflicts(winner)).clashes.append(Clash(loser, files, True))
        result.setdefault(loser, ModConflicts(loser)).clashes.append(Clash(winner, files, False))
    return result
