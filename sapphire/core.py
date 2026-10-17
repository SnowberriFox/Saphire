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

from sapphire import archive, conflicts, deploy, gameinfo, identify, importers, paths, steam
from sapphire.gamebanana import Cancelled, GameBananaClient, GameBananaError, GBFile, newest_file
from sapphire.library import InstalledMod, Library, Profile, StoredFile, StoredVpk, UpdateInfo
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
        self.identifier = identify.Identifier(self.gb.session)
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
        """Adopt VPKs someone put in addons by hand (or another manager) so deploying
        never deletes them. Files another manager knows about keep their names."""
        try:
            citadel = self.citadel()
        except NoGame:
            return []
        found = deploy.unmanaged_paks(citadel, self.lib.deployed)
        if not found:
            return []
        try:
            owners = importers.live_owners(citadel)
        except Exception as exc:  # noqa: BLE001
            log.warning("couldn't read other managers' records: %s", exc)
            owners = {}
        added: list[InstalledMod] = []
        taken: set[Path] = set()
        found_set = {p.resolve() for p in found}
        # 1. Files another manager has metadata for, grouped the way it grouped them.
        for rel in list(owners):
            m = owners[rel]
            mains = [v.main.resolve() for v in m.vpks]
            if not mains or any(p not in found_set for p in mains) or any(p in taken for p in mains):
                continue
            for v in m.vpks:
                v.chunks = self._chunks_beside(v.main)
            try:
                uid = self._adopt_import(m)
            except Exception as exc:  # noqa: BLE001
                log.warning("adopting %s failed: %s", m.name, exc)
                continue
            mod = self.lib.mods[uid]
            mod.note = "Found in your addons folder; details came from the manager that installed it."
            added.append(mod)
            for v in m.vpks:
                taken.add(v.main.resolve())
                for f in (v.main, *v.chunks):
                    self.lib.deployed[f.resolve().relative_to(citadel.resolve()).as_posix()] = {"src": "", "size": -1}
        # 2. Everything else becomes a plain manual install.
        for main in found:
            if main.resolve() in taken:
                continue
            chunks = self._chunks_beside(main)
            digest = hashlib.sha1(f"{main.parent.name}/{main.name}:{main.stat().st_size}".encode()).hexdigest()[:10]
            uid = f"local-{digest}"
            vset = VpkSet(main=main, chunks=chunks, rel=f"{main.parent.name}/{main.name}")
            with self.lock:
                stored = self._store(uid, [vset])
                mod = InstalledMod(uid=uid, name=f"Manual install ({main.parent.name}/{main.name})",
                                   source="local", file_name=main.name, vpks=stored, enabled=True,
                                   installed_at=int(time.time()),
                                   note="Found in your addons folder and adopted by Sapphire. "
                                        "Use Identify to find its GameBanana page.")
                self.lib.add(mod, top=False)
                # Mark the original as ours so it isn't adopted twice.
                self.lib.deployed[f"{main.parent.name}/{main.name}"] = {"src": "", "size": -1}
                added.append(mod)
        if added:
            self.lib.save()
            self._dirty = True
            log.info("adopted %d unmanaged VPKs", len(added))
        return added

    @staticmethod
    def _chunks_beside(main: Path) -> list[Path]:
        stem = main.name[: -len("_dir.vpk")] if main.name.lower().endswith("_dir.vpk") else main.stem
        return sorted(p for p in main.parent.iterdir()
                      if p.is_file() and p.name.lower().startswith(stem.lower() + "_")
                      and p.name.lower() != main.name.lower() and chunk_index(p) is not None)

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
    def apply(self, force: bool = False) -> deploy.DeployResult:
        """Make the game match the library. `force` rewrites every file even if it looks right."""
        with self.lock:
            if steam.is_game_running():
                self._dirty = True
                raise GameRunning()
            citadel = self.citadel()
            self.import_unmanaged()
            placements = deploy.plan(self.lib.ordered())
            result, record = deploy.deploy(citadel, placements, self.lib.deployed, force=force)
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
                    if latest and mod.file_id and latest.id != mod.file_id and latest.date_added >= mod.file_date:
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


    # ------------------------------------------------------------- identify
    def identify(self, uids: list[str] | None = None,
                 progress: Callable[[int, int], None] | None = None) -> list[tuple[str, identify.Match | None]]:
        """Match local (unknown) mods to GameBanana. Re-keys the ones it recognises."""
        targets = [m for m in self.lib.ordered() if m.source == "local" and m.vpks
                   and (uids is None or m.uid in uids)]
        results: list[tuple[str, identify.Match | None]] = []
        for i, mod in enumerate(targets):
            if progress:
                progress(i, len(targets))
            match = self.identifier.lookup(mod.file_path(mod.vpks[0].main))
            if match:
                self._adopt_match(mod, match)
            results.append((mod.uid, match))
        if progress:
            progress(len(targets), len(targets))
        return results

    def _adopt_match(self, mod: InstalledMod, match: identify.Match) -> None:
        new_uid = f"gb-{match.model}-{match.gb_id}"
        name, author, category, thumb, url = match.name, match.author, "", "", ""
        file_name, file_date = "", 0
        try:
            d = self.gb.details(match.model, match.gb_id)
            name = d.submission.name or name
            author = d.submission.author or author
            category, thumb, url = d.submission.category_label, d.submission.thumb_url, d.submission.url
            if match.file_id:
                f = next((f for f in d.files if f.id == match.file_id), None)
                if f:
                    file_name, file_date = f.filename, f.date_added
        except GameBananaError as exc:
            log.warning("identified %s as %s but couldn't fetch details: %s", mod.uid, new_uid, exc)
        with self.lock:
            if new_uid in self.lib.mods and new_uid != mod.uid:
                existing = self.lib.mods[new_uid]
                sizes = {existing.file_path(v.main).stat().st_size for v in existing.vpks
                         if existing.file_path(v.main).exists()}
                mine = mod.file_path(mod.vpks[0].main)
                if mine.exists() and mine.stat().st_size in sizes:
                    # Same file already in the library under its real name: drop the duplicate.
                    log.info("%s is a duplicate of %s, removing it", mod.uid, new_uid)
                    self.lib.remove(mod.uid)
                    shutil.rmtree(mod.folder, ignore_errors=True)
                    for prof in self.lib.profiles.values():
                        prof.entries = [(u, e) for u, e in prof.entries if u != mod.uid]
                else:
                    mod.note = f"Looks like a variant of “{name}”, which you already have installed."
                self.lib.save()
                self._dirty = True
                return
            old_uid, old_folder = mod.uid, mod.folder
            self.lib.remove(old_uid)
            mod.uid = new_uid
            mod.source, mod.model, mod.gb_id = "gamebanana", match.model, match.gb_id
            mod.name = name or mod.name
            mod.author, mod.category, mod.thumb_url = author, category, thumb
            mod.url = url or f"https://gamebanana.com/{match.model.lower()}s/{match.gb_id}"
            mod.file_id, mod.file_name, mod.file_date = match.file_id or 0, file_name, file_date
            mod.note = "" if match.file_id else "Identified, but the exact version is unknown; update it to be sure."
            if old_folder.exists():
                shutil.rmtree(mod.folder, ignore_errors=True)
                old_folder.rename(mod.folder)
            # keep its place in the load order
            self.lib.mods[new_uid] = mod
            self.lib.order.append(new_uid)
            for prof in self.lib.profiles.values():
                prof.entries = [(new_uid if u == old_uid else u, e) for u, e in prof.entries]
            self.lib.save()
            self._dirty = True   # library paths changed, so files get re-linked

    # --------------------------------------------------------------- import
    def detect_other_managers(self) -> dict[str, Path | None]:
        return {"dmm": importers.find_dmm(), "grimoire": importers.find_grimoire()}

    def plan_import(self, which: str) -> importers.ImportPlan:
        if which == "dmm":
            return importers.read_dmm()
        gd = self.game_dir
        if not gd:
            raise NoGame()
        return importers.read_grimoire(gd, exclude=set(self.lib.deployed))

    def run_import(self, plan: importers.ImportPlan, choose: Chooser | None = None,
                   progress: Progress | None = None, cancel: threading.Event | None = None,
                   profiles_only: bool = False) -> dict:
        """Adopt a plan's mods and profiles. Returns counts for the summary.

        profiles_only: don't touch mods; just (re)create the plan's profiles using
        mods already in the library (matched by GameBanana id, then by file name)."""
        imported: dict[str, str] = {}   # plan key -> uid
        downloaded = failed = 0
        if profiles_only:
            by_file = {}
            for mod in self.lib.mods.values():
                for v in mod.vpks:
                    by_file.setdefault(Path(v.label).name.lower(), mod.uid)
                by_file.setdefault(mod.file_name.lower(), mod.uid)
            for m in plan.mods:
                if m.gb_id and m.uid in self.lib.mods:
                    imported[m.key] = m.uid
                else:
                    for v in m.vpks:
                        hit = by_file.get(v.main.name.lower()) or by_file.get(Path(v.label).name.lower())
                        if hit:
                            imported[m.key] = hit
                            break
            with self.lock:
                n = self._import_profiles(plan, imported)
                self.lib.save()
            return {"imported": 0, "downloaded": 0, "failed": 0, "profiles": n,
                    "unmatched": sum(1 for m in plan.mods if m.key not in imported)}
        for i, m in enumerate(plan.mods):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            if progress:
                progress(f"Importing {m.name}", i, len(plan.mods))
            try:
                if m.vpks:
                    uid = self._adopt_import(m)
                elif m.can_download:
                    file = GBFile(id=m.file_id, filename=m.file_name or f"{m.file_id}.zip",
                                  download_url=f"https://gamebanana.com/dl/{m.file_id}")
                    wanted = {w.lower() for w in m.wanted_names}

                    def pick(sets, name, _w=wanted, _c=choose):
                        if _w:
                            hit = [s for s in sets if s.main.name.lower() in _w]
                            if hit:
                                return hit
                        return _c(sets, name) if _c else sets

                    mod = self.install_gamebanana(m.model, m.gb_id, file, choose=pick,
                                                  progress=progress, cancel=cancel)
                    mod.enabled = m.enabled
                    uid = mod.uid
                    downloaded += 1
                else:
                    continue
            except Cancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - keep going, report at the end
                log.error("import of %s failed: %s", m.name, exc)
                plan.warnings.append(f"“{m.name}”: {exc}")
                failed += 1
                continue
            imported[m.key] = uid
        with self.lock:
            # Files that came straight out of the game's addons folders are now ours:
            # record them so the next apply replaces them instead of adopting them again.
            try:
                citadel = self.citadel().resolve()
            except NoGame:
                citadel = None
            for m in plan.mods:
                if m.key not in imported or citadel is None:
                    continue
                for v in m.vpks:
                    for f in (v.main, *v.chunks):
                        try:
                            rel = f.resolve().relative_to(citadel).as_posix()
                        except ValueError:
                            continue
                        if rel.count("/") == 1 and rel.lower().startswith("addons"):
                            self.lib.deployed[rel] = {"src": "", "size": -1}
            # Imported mods take the plan's order, on top of anything already here.
            ordered = [imported[m.key] for m in plan.mods if m.key in imported]
            self.lib.set_order(ordered + [u for u in self.lib.order if u not in ordered])
            n_prof = self._import_profiles(plan, imported)
            self.lib.save()
            self._dirty = True
        return {"imported": len(imported), "downloaded": downloaded, "failed": failed, "profiles": n_prof}

    def _import_profiles(self, plan: importers.ImportPlan, imported: dict[str, str]) -> int:
        """Create the plan's profiles. A profile imported earlier from the same manager
        with the same name is refreshed; one you made yourself is left alone."""
        n = 0
        for prof in plan.profiles:
            entries: list[tuple[str, bool]] = []
            seen: set[str] = set()
            for k, on in prof.entries:
                uid = imported.get(k)
                if uid and uid not in seen:
                    seen.add(uid)
                    entries.append((uid, on))
            if not entries:
                continue
            name = prof.name
            existing = self.lib.profiles.get(name)
            if existing and existing.origin != plan.source:
                name = f"{name} ({plan.source})"
            self.lib.profiles[name] = Profile(name=name, entries=entries, saved_at=int(time.time()),
                                              origin=plan.source)
            n += 1
        return n

    def _adopt_import(self, m: importers.ImportMod) -> str:
        sets = [VpkSet(main=v.main, chunks=list(v.chunks), rel=v.label) for v in m.vpks]
        uid = m.uid
        with self.lock:
            existing = self.lib.mods.get(uid)
            stored = self._store(uid, sets)
            now = int(time.time())
            mod = InstalledMod(
                uid=uid, name=m.name, source="gamebanana" if m.gb_id else "local", model=m.model,
                gb_id=m.gb_id, url=f"https://gamebanana.com/{m.model.lower()}s/{m.gb_id}" if m.gb_id else "",
                author=m.author, category=m.category, thumb_url=m.thumb_url,
                file_id=m.file_id, file_name=m.file_name, vpks=stored, enabled=m.enabled,
                installed_at=existing.installed_at if existing else now, updated_at=now,
            )
            self.lib.add(mod, top=False)
            self.lib.mods[uid] = mod
            self.lib.save()
        return uid
