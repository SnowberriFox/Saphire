"""The mod manager itself: install, update, order, apply. UI-independent."""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from sapphire import archive, conflicts, deploy, gameinfo, paths, steam
from sapphire.gamebanana import Cancelled, GameBananaClient, GameBananaError, GBFile, newest_file
from sapphire.library import InstalledMod, Library, StoredFile, StoredVpk, UpdateInfo
from sapphire.vpk import VpkSet, chunk_index, find_sets

log = logging.getLogger(__name__)

# choose(sets, mod_name) -> the sets to install, or None to cancel
Chooser = Callable[[list[VpkSet], str], "list[VpkSet] | None"]
Progress = Callable[[str, int, int], None]  # (stage, done, total)


class ManagerError(Exception):
    pass


class GameRunning(ManagerError):
    def __init__(self):
        super().__init__("Deadlock is running. Close it first, then changes will apply.")


class NoGame(ManagerError):
    def __init__(self):
        super().__init__("Deadlock wasn't found. Set its folder in Settings.")


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name).strip("._") or "file"


class Manager:
    def __init__(self, library: Library | None = None, client: GameBananaClient | None = None):
        self.lib = library or Library()
        self.gb = client or GameBananaClient()
        self.lock = threading.RLock()
        self.vpk_index = conflicts.VpkIndex()
        self._dirty = False  # changes waiting to be applied (e.g. game was running)

    # ------------------------------------------------------------------ game dir
    @property
    def game_dir(self) -> Path | None:
        if self.lib.game_dir and steam.is_valid_game_dir(self.lib.game_dir):
            return Path(self.lib.game_dir)
        found = steam.find_deadlock()
        if found:
            self.lib.game_dir = str(found)
            self.lib.save()
        return found

    def set_game_dir(self, path: Path | str) -> None:
        path = Path(path)
        # Accept the Deadlock folder, its game/ folder or game/citadel.
        for cand in (path, path.parent, path.parent.parent):
            if steam.is_valid_game_dir(cand):
                self.lib.game_dir = str(cand)
                self.lib.save()
                return
        raise ManagerError("That folder doesn't look like Deadlock (no game/citadel/gameinfo.gi).")

    def citadel(self) -> Path:
        gd = self.game_dir
        if not gd:
            raise NoGame()
        return gd / "game" / "citadel"

    @property
    def pending(self) -> bool:
        return self._dirty

    # ------------------------------------------------------------------ storage
    def _store(self, uid: str, sets: list[VpkSet]) -> list[StoredVpk]:
        lib = paths.library_dir()
        final = lib / uid
        staging = lib / f".{uid}.new"
        old = lib / f".{uid}.old"
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)
        staging.mkdir(parents=True)
        stored: list[StoredVpk] = []
        for i, s in enumerate(sets):
            files: list[StoredFile] = []
            for f in s.files:
                chunk = None if f == s.main else chunk_index(f)
                name = f"{i:02d}_{_safe_name(f.name)}"
                shutil.copy2(f, staging / name)
                files.append(StoredFile(stored=name, chunk=chunk))
            stored.append(StoredVpk(label=s.rel, files=files))
        if final.exists():
            final.rename(old)
        staging.rename(final)
        shutil.rmtree(old, ignore_errors=True)
        return stored

    def _pick_sets(self, extracted: Path, name: str, choose: Chooser | None,
                   previous: list[str] | None = None) -> list[VpkSet]:
        sets = find_sets(extracted)
        if not sets:
            raise ManagerError(
                f"No VPK files found in the download for “{name}”. It may not be a "
                "normal VPK mod; check its GameBanana page for install notes.")
        if len(sets) == 1:
            return sets
        if previous:  # updating: reuse the variant(s) picked last time if they still exist
            want = [p.lower() for p in previous]
            by_rel = {s.rel.lower(): s for s in sets}
            if all(p in by_rel for p in want):
                return [by_rel[p] for p in want]
            by_name = {Path(s.rel).parent.name.lower() + "/" + s.main.name.lower(): s for s in sets}
            keyed = [Path(p).parent.name + "/" + Path(p).name for p in want]
            if all(k in by_name for k in keyed):
                return [by_name[k] for k in keyed]
        if choose is None:
            return sets
        picked = choose(sets, name)
        if not picked:
            raise Cancelled()
        return picked

    # ------------------------------------------------------------------ install
    def install_gamebanana(self, model: str, gb_id: int, file: GBFile | None = None,
                           choose: Chooser | None = None, progress: Progress | None = None,
                           cancel: threading.Event | None = None) -> InstalledMod:
        details = self.gb.details(model, gb_id)
        sub = details.submission
        if file is None:
            file = newest_file(details.files)
        if file is None:
            raise ManagerError(f"“{sub.name}” has no downloadable files.")
        uid = sub.key
        existing = self.lib.mods.get(uid)
        work = Path(tempfile.mkdtemp(prefix="install-", dir=paths.cache_dir()))
        try:
            if progress:
                progress("Downloading", 0, file.size)
            dl = self.gb.download(file, work / "dl",
                                  progress=(lambda d, t: progress("Downloading", d, t)) if progress else None,
                                  cancel=cancel)
            if progress:
                progress("Extracting", 0, 0)
            extracted = archive.extract(dl, work / "x")
            previous = [v.label for v in existing.vpks] if existing and existing.file_id != file.id else None
            sets = self._pick_sets(extracted, sub.name, choose, previous)
            with self.lock:
                stored = self._store(uid, sets)
                now = int(time.time())
                mod = InstalledMod(
                    uid=uid, name=sub.name, source="gamebanana", model=model, gb_id=gb_id,
                    url=sub.url or f"https://gamebanana.com/{model.lower()}s/{gb_id}",
                    author=sub.author, category=sub.category_label, thumb_url=sub.thumb_url,
                    nsfw=sub.nsfw, file_id=file.id, file_name=file.filename,
                    file_date=file.date_added, vpks=stored,
                    enabled=existing.enabled if existing else True,
                    installed_at=existing.installed_at if existing else now, updated_at=now,
                )
                self.lib.add(mod, top=True)
                self.lib.mods[uid] = mod
                self.lib.save()
                self._dirty = True
            log.info("installed %s (%s) file %s", sub.name, uid, file.filename)
            return mod
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def install_local(self, path: Path | str, choose: Chooser | None = None) -> InstalledMod:
        path = Path(path)
        digest = hashlib.sha1(f"{path.name}:{path.stat().st_size}".encode()).hexdigest()[:10]
        uid = f"local-{digest}"
        name = re.sub(r"[_\-]+", " ", path.stem).strip() or path.name
        existing = self.lib.mods.get(uid)
        work = Path(tempfile.mkdtemp(prefix="import-", dir=paths.cache_dir()))
        try:
            extracted = archive.extract(path, work / "x")
            sets = self._pick_sets(extracted, name, choose)
            with self.lock:
                stored = self._store(uid, sets)
                now = int(time.time())
                mod = InstalledMod(uid=uid, name=existing.name if existing else name,
                                   source="local", file_name=path.name, vpks=stored,
                                   enabled=existing.enabled if existing else True,
                                   installed_at=now, updated_at=now)
                self.lib.add(mod, top=True)
                self.lib.mods[uid] = mod
                self.lib.save()
                self._dirty = True
            return mod
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def import_unmanaged(self) -> list[InstalledMod]:
        """Adopt VPKs someone put in addons by hand so deploying never deletes them."""
        try:
            citadel = self.citadel()
        except NoGame:
            return []
        found = deploy.unmanaged_paks(citadel, self.lib.deployed)
        added = []
        for main in found:
            stem = main.name[: -len("_dir.vpk")]
            chunks = sorted(p for p in main.parent.iterdir()
                            if p.name.lower().startswith(stem.lower() + "_")
                            and p.name.lower() != main.name.lower()
                            and chunk_index(p) is not None)
            digest = hashlib.sha1(f"{main.parent.name}/{main.name}:{main.stat().st_size}".encode()).hexdigest()[:10]
            uid = f"local-{digest}"
            vset = VpkSet(main=main, chunks=chunks, rel=f"{main.parent.name}/{main.name}")
            with self.lock:
                stored = self._store(uid, [vset])
                mod = InstalledMod(uid=uid, name=f"Manual install ({main.parent.name}/{main.name})",
                                   source="local", file_name=main.name, vpks=stored, enabled=True,
                                   installed_at=int(time.time()),
                                   note="Found in your addons folder and adopted by Sapphire.")
                self.lib.add(mod, top=False)
                # Mark the original as ours so it isn't adopted twice.
                self.lib.deployed[f"{main.parent.name}/{main.name}"] = {"src": "", "size": -1}
                added.append(mod)
        if added:
            self.lib.save()
            self._dirty = True
            log.info("adopted %d unmanaged VPKs", len(added))
        return added

    # ------------------------------------------------------------------- edits
    def remove(self, uid: str) -> None:
        with self.lock:
            mod = self.lib.remove(uid)
            if mod:
                shutil.rmtree(mod.folder, ignore_errors=True)
            self.lib.save()
            self._dirty = True

    def rename(self, uid: str, name: str) -> None:
        with self.lock:
            if uid in self.lib.mods and name.strip():
                self.lib.mods[uid].name = name.strip()
                self.lib.save()

    def set_enabled(self, uid: str, enabled: bool) -> None:
        with self.lock:
            if uid in self.lib.mods:
                self.lib.mods[uid].enabled = enabled
                self.lib.save()
                self._dirty = True

    def set_order(self, uids: list[str]) -> None:
        with self.lock:
            self.lib.set_order(uids)
            self.lib.save()
            self._dirty = True

    # ------------------------------------------------------------------- apply
    def apply(self) -> deploy.DeployResult:
        with self.lock:
            if steam.is_game_running():
                self._dirty = True
                raise GameRunning()
            citadel = self.citadel()
            self.import_unmanaged()
            placements = deploy.plan(self.lib.ordered())
            result, record = deploy.deploy(citadel, placements, self.lib.deployed)
            self.lib.deployed = record
            self.lib.save()
            folders = [f"citadel/{f}" for f in result.folders or []]
            gameinfo.apply(self.game_dir, folders, paths.data_dir() / "backups")
            self._dirty = False
            return result

    def expected_folders(self) -> list[str]:
        return [f"citadel/{f}" for f in deploy.folders_in(deploy.plan(self.lib.ordered()))]

    def gameinfo_needs_fix(self) -> bool:
        gd = self.game_dir
        if not gd:
            return False
        try:
            text = gameinfo.read(gd)
        except gameinfo.GameInfoError:
            return False
        folders = self.expected_folders()
        if not folders:
            return gameinfo.inspect(text).patched
        return gameinfo.needs_patch(text, folders)

    def ensure_gameinfo(self) -> bool:
        """Re-add our gameinfo.gi block if a game update wiped it. True if it fixed something."""
        with self.lock:
            if not self.gameinfo_needs_fix():
                return False
            return gameinfo.apply(self.game_dir, self.expected_folders(), paths.data_dir() / "backups")

    def reset_to_vanilla(self) -> None:
        """Remove every deployed mod file and our gameinfo.gi block. Library is kept."""
        with self.lock:
            if steam.is_game_running():
                raise GameRunning()
            citadel = self.citadel()
            _, record = deploy.deploy(citadel, [], self.lib.deployed)
            self.lib.deployed = record
            for mod in self.lib.mods.values():
                mod.enabled = False
            self.lib.save()
            gameinfo.apply(self.game_dir, [], paths.data_dir() / "backups")
            self._dirty = False

    def launch(self) -> None:
        if not steam.is_game_running():
            if self._dirty or self.gameinfo_needs_fix():
                self.apply()
        steam.launch_game()

    # ----------------------------------------------------------------- updates
    def check_updates(self, progress: Callable[[int, int], None] | None = None) -> list[InstalledMod]:
        mods = [m for m in self.lib.mods.values() if m.source == "gamebanana" and m.gb_id]
        found: list[InstalledMod] = []
        done = 0

        def check(mod: InstalledMod):
            files = self.gb.files(mod.model, mod.gb_id)
            return mod, newest_file(files), files

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(check, m) for m in mods]
            for fut in as_completed(futures):
                done += 1
                if progress:
                    progress(done, len(mods))
                try:
                    mod, latest, files = fut.result()
                except GameBananaError as exc:
                    log.warning("update check failed: %s", exc)
                    continue
                with self.lock:
                    if latest and latest.id != mod.file_id and latest.date_added >= mod.file_date:
                        mod.update = UpdateInfo(latest.id, latest.filename, latest.date_added)
                        found.append(mod)
                    else:
                        mod.update = None
        with self.lock:
            self.lib.save()
        return found

    def update(self, uid: str, choose: Chooser | None = None, progress: Progress | None = None,
               cancel: threading.Event | None = None) -> InstalledMod:
        mod = self.lib.mods[uid]
        files = self.gb.files(mod.model, mod.gb_id)
        target = None
        if mod.update:
            target = next((f for f in files if f.id == mod.update.file_id), None)
        target = target or newest_file(files)
        if target is None:
            raise ManagerError("No files available for this mod anymore.")
        new = self.install_gamebanana(mod.model, mod.gb_id, target, choose, progress, cancel)
        new.update = None
        with self.lock:
            self.lib.save()
        return new

    # --------------------------------------------------------------- conflicts
    def conflicts(self) -> dict[str, conflicts.ModConflicts]:
        return conflicts.compute(self.lib.ordered(), self.vpk_index)

    # ---------------------------------------------------------------- profiles
    def save_profile(self, name: str) -> None:
        with self.lock:
            self.lib.snapshot(name.strip())
            self.lib.save()

    def load_profile(self, name: str) -> list[str]:
        with self.lock:
            missing = self.lib.restore(name)
            self.lib.save()
            self._dirty = True
            return missing

    def delete_profile(self, name: str) -> None:
        with self.lock:
            self.lib.profiles.pop(name, None)
            if self.lib.active_profile == name:
                self.lib.active_profile = None
            self.lib.save()

    def rename_profile(self, old: str, new: str) -> None:
        with self.lock:
            new = new.strip()
            if not new or old not in self.lib.profiles or new in self.lib.profiles:
                raise ManagerError("Pick a different name.")
            prof = self.lib.profiles.pop(old)
            prof.name = new
            self.lib.profiles[new] = prof
            if self.lib.active_profile == old:
                self.lib.active_profile = new
            self.lib.save()
