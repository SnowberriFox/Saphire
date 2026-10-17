"""Turning the load order into files in game/citadel/addons*.

The rules Deadlock follows:
  * only files named pakNN_dir.vpk (NN = 01..99) in a mounted folder load
  * a lower NN wins when two VPKs contain the same file
  * at most 99 per folder, so extra mods spill into addons2, addons3...
    which are mounted after addons (earlier mounts win)

Sapphire computes the exact set of files that *should* exist, then makes the
folder match: unchanged files are skipped, changed ones are written to a temp
name and atomically renamed into place, and leftovers are removed. Only files
matching pakNN_*.vpk are ever touched; anything else in the folder is left
alone. Mods are hard-linked from the library when possible (instant, no extra
disk space) and copied otherwise (e.g. game on a different drive).
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from sapphire.library import InstalledMod
from sapphire.vpk import PAK_NAME_RE

log = logging.getLogger(__name__)

PER_FOLDER = 99
MAX_FOLDERS = 9


class DeployError(Exception):
    pass


@dataclass
class Placement:
    uid: str
    vpk_label: str
    folder: str      # "addons", "addons2", ...
    slot: int        # 1..99
    src: Path
    dst_name: str    # pak01_dir.vpk / pak01_000.vpk

    @property
    def rel(self) -> str:
        return f"{self.folder}/{self.dst_name}"


def folder_name(index: int) -> str:
    return "addons" if index == 0 else f"addons{index + 1}"


def plan(mods: list[InstalledMod]) -> list[Placement]:
    """Placements for the enabled mods, given in priority order (first wins)."""
    out: list[Placement] = []
    n = 0
    for mod in mods:
        if not mod.enabled:
            continue
        for vpk in mod.vpks:
            folder_idx, slot = divmod(n, PER_FOLDER)
            if folder_idx >= MAX_FOLDERS:
                raise DeployError(f"Too many enabled VPKs (limit {PER_FOLDER * MAX_FOLDERS}).")
            slot += 1
            folder = folder_name(folder_idx)
            for f in vpk.files:
                suffix = "dir" if f.chunk is None else f.chunk
                out.append(Placement(uid=mod.uid, vpk_label=vpk.label, folder=folder, slot=slot,
                                     src=mod.file_path(f), dst_name=f"pak{slot:02d}_{suffix}.vpk"))
            n += 1
    return out


def folders_in(placements: list[Placement]) -> list[str]:
    seen: list[str] = []
    for p in placements:
        if p.folder not in seen:
            seen.append(p.folder)
    return seen


def _same(dst: Path, src: Path, record: dict | None) -> bool:
    try:
        if os.path.samefile(src, dst):
            return True
        if record and record.get("src") == str(src):
            st_dst, st_src = dst.stat(), src.stat()
            return (st_dst.st_size == st_src.st_size == record.get("size")
                    and st_dst.st_mtime_ns == record.get("mtime_ns")
                    and st_src.st_mtime_ns == record.get("src_mtime_ns"))
    except OSError:
        return False
    return False


def _place(src: Path, dst: Path) -> None:
    tmp = dst.with_name(f".{dst.name}.sapphire-tmp")
    tmp.unlink(missing_ok=True)
    try:
        os.link(src, tmp)
    except OSError:
        shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


@dataclass
class DeployResult:
    written: int = 0
    kept: int = 0
    removed: int = 0
    folders: list[str] | None = None


def deploy(citadel: Path, placements: list[Placement], previous: dict[str, dict],
           force: bool = False) -> tuple[DeployResult, dict]:
    """Make citadel/addons* match `placements`. Returns (result, new deployed record).
    `force` rewrites every file even when it already matches."""
    citadel = Path(citadel)
    if not citadel.is_dir():
        raise DeployError(f"{citadel} doesn't exist")
    result = DeployResult(folders=folders_in(placements))
    wanted = {p.rel: p for p in placements}
    record: dict[str, dict] = {}

    for p in placements:
        if not p.src.is_file():
            raise DeployError(f"Library file missing for {p.uid}: {p.src.name}. Reinstall that mod.")

    # Folders we may need to clean: base addons, any we deployed to before, any wanted.
    managed = {"addons"} | {k.split("/", 1)[0] for k in previous} | set(result.folders)
    for folder in sorted(managed):
        path = citadel / folder
        if folder in result.folders:
            path.mkdir(parents=True, exist_ok=True)
        if not path.is_dir():
            continue
        for entry in path.iterdir():
            if entry.is_file() and PAK_NAME_RE.match(entry.name):
                rel = f"{folder}/{entry.name}"
                if rel not in wanted:
                    entry.unlink()
                    result.removed += 1
                elif entry.name != wanted[rel].dst_name:  # same slot, different case
                    entry.unlink()
            elif entry.name.endswith(".sapphire-tmp"):
                entry.unlink(missing_ok=True)

    for rel, p in wanted.items():
        dst = citadel / rel
        if not force and dst.exists() and _same(dst, p.src, previous.get(rel)):
            result.kept += 1
        else:
            _place(p.src, dst)
            result.written += 1
        st, ss = dst.stat(), p.src.stat()
        if st.st_size != ss.st_size:
            raise DeployError(f"Writing {rel} failed (size mismatch). Is the disk full?")
        record[rel] = {"src": str(p.src), "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                       "src_mtime_ns": ss.st_mtime_ns}

    # Remove overflow folders we created that are now empty.
    for folder in managed - set(result.folders) - {"addons"}:
        path = citadel / folder
        try:
            path.rmdir()
        except OSError:
            pass
    log.info("deploy: %s written, %s kept, %s removed, folders=%s",
             result.written, result.kept, result.removed, result.folders)
    return result, record


def unmanaged_paks(citadel: Path, previous: dict[str, dict]) -> list[Path]:
    """pakNN files in addons* that Sapphire didn't put there (manual installs, other managers)."""
    found: list[Path] = []
    citadel = Path(citadel)
    if not citadel.is_dir():
        return found
    for path in sorted(citadel.iterdir()):
        if not (path.is_dir() and path.name.lower().startswith("addons")):
            continue
        if path.name != "addons" and not path.name[6:].isdigit():
            continue
        for entry in sorted(path.iterdir()):
            if entry.is_file() and PAK_NAME_RE.match(entry.name) and entry.name.lower().endswith("_dir.vpk"):
                rel = f"{path.name}/{entry.name}"
                if rel not in previous:
                    found.append(entry)
    return found
