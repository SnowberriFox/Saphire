"""Reading other mod managers' data so people can switch to Sapphire.

Both readers produce the same neutral ImportPlan; core.Manager.run_import
turns a plan into library entries and profiles. Nothing here writes to the
other manager's files.

Deadlock Mod Manager (DMM)
    <data>/state.json       Tauri store; key "local-config" holds the app state:
                            localMods[], profiles{id: {name, enabledMods, mods}}
    <data>/mods/<id>/files  every downloaded VPK, under its original name
    data = ~/.local/share/dev.stormix.deadlock-mod-manager (or ~/.config, or
    the Flatpak equivalents under ~/.var/app)

Grimoire
    <userData>/mod-metadata.json   per-VPK metadata keyed by file name
    <userData>/profiles.json       saved profiles
    <userData>/settings.json       deadlockPath
    userData = ~/.config/Grimoire (Flatpak: ~/.var/app/com.grimoiremods.Grimoire/config/Grimoire)
    The VPKs themselves live in the game: citadel/addons (pakNN = enabled),
    citadel/addons/.disabled (off), citadel/addons1.. (overflow) and
    citadel/grimoire (its "global" priority folder; pak01-04 are its own).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from sapphire.vpk import PAK_NAME_RE, chunk_index, is_vpk

log = logging.getLogger(__name__)

DMM_ID = "dev.stormix.deadlock-mod-manager"
GRIMOIRE_FLATPAK = "com.grimoiremods.Grimoire"


@dataclass
class ImportVpk:
    label: str              # shown in Sapphire ("Blue/pak01_dir.vpk")
    main: Path
    chunks: list[Path] = field(default_factory=list)


@dataclass
class ImportMod:
    key: str                # unique within the plan
    name: str
    model: str = "Mod"
    gb_id: int = 0
    file_id: int = 0
    file_name: str = ""
    author: str = ""
    category: str = ""
    thumb_url: str = ""
    vpks: list[ImportVpk] = field(default_factory=list)   # files available locally
    wanted_names: list[str] = field(default_factory=list)  # VPK names to pick if re-downloading
    enabled: bool = True
    order: int = 0          # lower = higher priority

    @property
    def can_download(self) -> bool:
        return bool(self.gb_id and self.file_id)

    @property
    def uid(self) -> str:
        return f"gb-{self.model}-{self.gb_id}" if self.gb_id else f"local-import-{self.key}"


@dataclass
class ImportProfile:
    name: str
    entries: list[tuple[str, bool]]   # (mod key, enabled) in priority order


@dataclass
class ImportPlan:
    source: str                        # "Deadlock Mod Manager" / "Grimoire"
    location: Path | None
    mods: list[ImportMod] = field(default_factory=list)
    profiles: list[ImportProfile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def downloadable(self) -> list[ImportMod]:
        return [m for m in self.mods if not m.vpks and m.can_download]

    @property
    def skipped(self) -> list[ImportMod]:
        return [m for m in self.mods if not m.vpks and not m.can_download]


def _xdg(var: str, fallback: str, home: Path) -> Path:
    v = os.environ.get(var, "").strip()
    return Path(v) if v else home / fallback


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.debug("can't read %s: %s", path, exc)
        return None


def _vpks_under(root: Path) -> list[ImportVpk]:
    """Group the VPKs under a folder into main+chunks, like vpk.find_sets."""
    if not root.is_dir():
        return []
    files = sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".vpk")
    chunks: dict[Path, list[Path]] = {}
    mains: list[Path] = []
    for p in files:
        idx = chunk_index(p)
        if idx is not None:
            stem = p.name[: -len(f"_{idx}.vpk")]
            owner = next((q for q in p.parent.iterdir() if q.name.lower() == f"{stem.lower()}_dir.vpk"), None)
            if owner:
                chunks.setdefault(owner, []).append(p)
                continue
        mains.append(p)
    return [ImportVpk(label=p.relative_to(root).as_posix(), main=p, chunks=sorted(chunks.get(p, [])))
            for p in mains if is_vpk(p)]


# ============================================================ Deadlock Mod Manager

def dmm_data_dirs(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    flat = home / ".var" / "app" / DMM_ID
    return [
        _xdg("XDG_DATA_HOME", ".local/share", home) / DMM_ID,
        _xdg("XDG_CONFIG_HOME", ".config", home) / DMM_ID,
        flat / "data" / DMM_ID,
        flat / "config" / DMM_ID,
    ]


def find_dmm(home: Path | None = None) -> Path | None:
    for d in dmm_data_dirs(home):
        if (d / "state.json").is_file():
            return d
    return None


def _dmm_state(path: Path) -> dict:
    outer = _read_json(path)
    if not isinstance(outer, dict):
        raise ValueError("state.json isn't a JSON object")
    inner = outer.get("local-config", outer)
    if isinstance(inner, str):
        inner = json.loads(inner)
    if not isinstance(inner, dict):
        raise ValueError("state.json has no local-config")
    state = inner.get("state", inner)
    return state if isinstance(state, dict) else {}


_FILE_ID_RE = re.compile(r"^gamebanana-file://[^/]+/(\d+)$|gamebanana\.com/dl/(\d+)", re.I)


def _dmm_file_id(url) -> int:
    if not isinstance(url, str):
        return 0
    m = _FILE_ID_RE.search(url)
    if not m:
        return 0
    return int(m.group(1) or m.group(2))


def _dmm_mod(raw: dict, cache_dirs: list[Path]) -> ImportMod | None:
    rid = raw.get("remoteId")
    if not isinstance(rid, str) or not rid:
        return None
    model, gb_id = "Mod", 0
    if re.fullmatch(r"[1-9]\d*", rid):
        gb_id = int(rid)
    elif re.fullmatch(r"snd-[1-9]\d*", rid):
        model, gb_id = "Sound", int(rid[4:])
    downloads = raw.get("selectedDownloads")
    if not isinstance(downloads, list):
        downloads = [raw["selectedDownload"]] if isinstance(raw.get("selectedDownload"), dict) else []
    file_id, file_name = 0, ""
    for d in downloads:
        if isinstance(d, dict):
            fid = _dmm_file_id(d.get("url"))
            if fid and not file_id:
                file_id, file_name = fid, str(d.get("name") or "")
    if not file_name and downloads and isinstance(downloads[0], dict):
        file_name = str(downloads[0].get("name") or "")
    tree = raw.get("installedFileTree")
    wanted = []
    if isinstance(tree, dict) and isinstance(tree.get("files"), list):
        wanted = [f["name"] for f in tree["files"]
                  if isinstance(f, dict) and f.get("is_selected") is not False and isinstance(f.get("name"), str)]
    images = raw.get("images") if isinstance(raw.get("images"), list) else []
    thumb = next((i for i in images if isinstance(i, str) and i.startswith("http")), "")
    vpks: list[ImportVpk] = []
    for c in cache_dirs:
        vpks = _vpks_under(c / rid / "files")
        if vpks:
            break
    if vpks and wanted:
        picked = [v for v in vpks if v.main.name.lower() in {w.lower() for w in wanted}]
        if picked:
            vpks = picked
    order = raw.get("installOrder")
    return ImportMod(
        key=rid, name=str(raw.get("name") or f"DMM mod {rid}"), model=model, gb_id=gb_id,
        file_id=file_id, file_name=file_name, author=str(raw.get("author") or ""),
        category=str(raw.get("category") or ""), thumb_url=thumb, vpks=vpks, wanted_names=wanted,
        order=int(order) if isinstance(order, (int, float)) else 10**6,
    )


def read_dmm(data_dir: Path | None = None, home: Path | None = None) -> ImportPlan:
    data_dir = data_dir or find_dmm(home)
    plan = ImportPlan(source="Deadlock Mod Manager", location=data_dir)
    if not data_dir:
        plan.warnings.append("Deadlock Mod Manager data not found.")
        return plan
    try:
        state = _dmm_state(data_dir / "state.json")
    except (ValueError, OSError) as exc:
        plan.warnings.append(f"Couldn't read state.json: {exc}")
        return plan
    cache_dirs = [data_dir / "mods"] + [d / "mods" for d in dmm_data_dirs(home) if d != data_dir]
    mods: dict[str, ImportMod] = {}

    def add(raw):
        m = _dmm_mod(raw, cache_dirs) if isinstance(raw, dict) else None
        if m and (m.key not in mods or (not mods[m.key].vpks and m.vpks)):
            mods[m.key] = m

    for raw in state.get("localMods") or []:
        add(raw)
    profiles = state.get("profiles") if isinstance(state.get("profiles"), dict) else {}
    active = state.get("activeProfileId")
    for pid, prof in profiles.items():
        if not isinstance(prof, dict):
            continue
        for raw in prof.get("mods") or []:
            add(raw)
        flags = {}
        for rid, entry in (prof.get("enabledMods") or {}).items():
            if isinstance(entry, dict) and isinstance(entry.get("enabled"), bool):
                flags[rid] = entry["enabled"]
            elif isinstance(entry, bool):
                flags[rid] = entry
        listed = [r.get("remoteId") for r in prof.get("mods") or [] if isinstance(r, dict)]
        keys = [k for k in listed if isinstance(k, str)] or list(flags)
        keys = sorted(dict.fromkeys(keys), key=lambda k: mods[k].order if k in mods else 10**6)
        name = str(prof.get("name") or pid)
        plan.profiles.append(ImportProfile(name=name, entries=[(k, bool(flags.get(k, False))) for k in keys]))
        if pid == active or (active is None and prof.get("isDefault")):
            for k, on in plan.profiles[-1].entries:
                if k in mods:
                    mods[k].enabled = on
    if not profiles:
        for m in mods.values():
            m.enabled = True
    plan.mods = sorted(mods.values(), key=lambda m: m.order)
    for m in plan.skipped:
        plan.warnings.append(f"“{m.name}”: no files in DMM's cache and no GameBanana file id, skipped.")
    return plan


# ======================================================================== Grimoire

def grimoire_data_dirs(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    cfg = _xdg("XDG_CONFIG_HOME", ".config", home)
    return [cfg / "Grimoire", cfg / "grimoire",
            home / ".var" / "app" / GRIMOIRE_FLATPAK / "config" / "Grimoire"]


def find_grimoire(home: Path | None = None) -> Path | None:
    for d in grimoire_data_dirs(home):
        if (d / "mod-metadata.json").is_file() or (d / "profiles.json").is_file():
            return d
    return None


_OVERFLOW_RE = re.compile(r"^addons(\d+)$", re.I)


def _grimoire_meta_key(path: Path) -> str:
    parent = path.parent.name
    if parent.lower() == "grimoire":
        return f"grimoire/{path.name}"
    if _OVERFLOW_RE.match(parent):
        return f"{parent}/{path.name}"
    return path.name


def read_grimoire(game_dir: Path, data_dir: Path | None = None, home: Path | None = None,
                  exclude: set[str] | None = None) -> ImportPlan:
    """`exclude` = citadel-relative paths Sapphire itself put in the addons folders."""
    data_dir = data_dir or find_grimoire(home)
    plan = ImportPlan(source="Grimoire", location=data_dir)
    if not data_dir:
        plan.warnings.append("Grimoire data not found.")
        return plan
    meta = _read_json(data_dir / "mod-metadata.json")
    meta = meta if isinstance(meta, dict) else {}
    settings = _read_json(data_dir / "settings.json")
    if isinstance(settings, dict) and settings.get("deadlockPath"):
        gp = Path(settings["deadlockPath"])
        if (gp / "game" / "citadel").is_dir():
            game_dir = gp
    citadel = Path(game_dir) / "game" / "citadel"
    if not citadel.is_dir():
        plan.warnings.append("Deadlock folder not found, so Grimoire's installed files can't be read.")
        return plan

    # Collect every VPK Grimoire manages, in its load order.
    found: list[tuple[int, Path, bool]] = []   # (sort key, main vpk, enabled)
    folders: list[tuple[int, Path]] = []
    addons = citadel / "addons"
    if addons.is_dir():
        folders.append((0, addons))
    for p in citadel.iterdir():
        m = _OVERFLOW_RE.match(p.name)
        if m and p.is_dir():
            folders.append((int(m.group(1)), p))
    grim = citadel / "grimoire"
    for fi, folder in sorted(folders):
        for p in sorted(folder.iterdir()):
            if p.is_file() and PAK_NAME_RE.match(p.name) and p.name.lower().endswith("_dir.vpk"):
                found.append((fi * 1000 + int(p.name[3:5]), p, True))
    if grim.is_dir():
        for p in sorted(grim.iterdir()):
            m = PAK_NAME_RE.match(p.name)
            if p.is_file() and m and p.name.lower().endswith("_dir.vpk") and int(m.group(1)) >= 5:
                found.append((-1000 + int(m.group(1)), p, True))   # priority folder loads first
    disabled = addons / ".disabled"
    if disabled.is_dir():
        for i, p in enumerate(sorted(disabled.iterdir())):
            if p.is_file() and p.suffix.lower() == ".vpk" and chunk_index(p) is None:
                found.append((10**6 + i, p, False))
    if exclude:
        found = [t for t in found if t[1].relative_to(citadel).as_posix() not in exclude]
    found.sort(key=lambda t: t[0])

    def chunks_of(main: Path) -> list[Path]:
        stem = main.name[: -len("_dir.vpk")] if main.name.lower().endswith("_dir.vpk") else main.stem
        return sorted(q for q in main.parent.iterdir()
                      if q.is_file() and q.name.lower().startswith(stem.lower() + "_") and chunk_index(q) is not None)

    groups: dict[str, ImportMod] = {}
    key_of_file: dict[str, str] = {}   # metaKey -> plan key
    for order, (_, main, enabled) in enumerate(found):
        if not is_vpk(main):
            continue
        mk = _grimoire_meta_key(main)
        info = meta.get(mk) if isinstance(meta.get(mk), dict) else {}
        if any(info.get(k) for k in ("lockerCosmetics", "lockerSounds", "lockerColors", "lockerTrippySkins")):
            continue   # Grimoire's own generated VPKs, not user mods
        gb_id = int(info.get("gameBananaId") or 0)
        file_id = int(info.get("gameBananaFileId") or 0)
        model = "Sound" if str(info.get("sourceSection") or "").lower() == "sound" else "Mod"
        if gb_id and file_id:
            key = f"{model}-{gb_id}-{file_id}"
        elif gb_id:
            key = f"{model}-{gb_id}"
        else:
            key = f"file-{mk}"
        label = str(info.get("archiveVpkPath") or main.name)
        vpk = ImportVpk(label=label, main=main, chunks=chunks_of(main))
        key_of_file[mk] = key
        if key in groups:
            g = groups[key]
            g.vpks.append(vpk)
            g.enabled = g.enabled or enabled
            g.order = min(g.order, order)
            continue
        name = str(info.get("modName") or info.get("variantLabel") or main.stem)
        if info.get("variantLabel") and info.get("modName"):
            name = f"{info['modName']} ({info['variantLabel']})"
        groups[key] = ImportMod(
            key=key, name=name, model=model, gb_id=gb_id, file_id=file_id,
            file_name=str(info.get("sourceFileName") or ""), author=str(info.get("author") or ""),
            category=str(info.get("categoryName") or ""), thumb_url=str(info.get("thumbnailUrl") or ""),
            vpks=[vpk], enabled=enabled, order=order,
        )
    for g in groups.values():
        g.vpks.sort(key=lambda v: v.main.name.lower())
    plan.mods = sorted(groups.values(), key=lambda m: m.order)

    profiles = _read_json(data_dir / "profiles.json")
    for prof in profiles if isinstance(profiles, list) else []:
        if not isinstance(prof, dict):
            continue
        entries: list[tuple[str, bool]] = []
        seen: set[str] = set()
        pmods = sorted((m for m in prof.get("mods") or [] if isinstance(m, dict)),
                       key=lambda m: (m.get("priority") if isinstance(m.get("priority"), (int, float)) else 10**6))
        for pm in pmods:
            gb_id = int(pm.get("gameBananaId") or 0)
            file_id = int(pm.get("gameBananaFileId") or 0)
            key = None
            for cand in (f"Mod-{gb_id}-{file_id}", f"Sound-{gb_id}-{file_id}", f"Mod-{gb_id}", f"Sound-{gb_id}"):
                if gb_id and cand in groups:
                    key = cand
                    break
            if key is None and isinstance(pm.get("fileName"), str):
                key = key_of_file.get(pm["fileName"]) or key_of_file.get(Path(pm["fileName"]).name)
            if key and key not in seen:
                seen.add(key)
                entries.append((key, bool(pm.get("enabled"))))
        if entries:
            plan.profiles.append(ImportProfile(name=str(prof.get("name") or "Grimoire profile"), entries=entries))
    if not plan.mods:
        plan.warnings.append("No Grimoire-managed VPKs found in the game folder.")
    return plan


# ====================================================== live files in the game

def live_owners(citadel: Path, home: Path | None = None) -> dict[str, ImportMod]:
    """Map citadel-relative paths of pakNN files in addons* to the mod another
    manager says they belong to (name, GameBanana ids). Used when Sapphire adopts
    files it finds lying in the game folder, so they get real names instead of
    "Manual install". Covers Grimoire's metadata sidecar and DMM's .dmm.json."""
    owners: dict[str, ImportMod] = {}
    citadel = Path(citadel)
    gd = citadel.parent.parent
    # Grimoire
    if find_grimoire(home):
        try:
            for m in read_grimoire(gd, home=home).mods:
                for v in m.vpks:
                    try:
                        owners[v.main.resolve().relative_to(citadel.resolve()).as_posix()] = m
                    except ValueError:
                        pass
        except Exception as exc:  # noqa: BLE001
            log.warning("grimoire metadata unreadable: %s", exc)
    # DMM: .dmm.json in addons (root profile) + names from state.json
    manifest = _read_json(citadel / "addons" / ".dmm.json")
    if isinstance(manifest, dict) and isinstance(manifest.get("mods"), dict):
        try:
            state_mods = {m.key: m for m in read_dmm(home=home).mods}
        except Exception:  # noqa: BLE001
            state_mods = {}
        for rid, entry in manifest["mods"].items():
            if not isinstance(entry, dict) or not isinstance(rid, str):
                continue
            shard = entry.get("shard") if isinstance(entry.get("shard"), int) else 1
            folder = "addons" if shard <= 1 else f"addons{shard}"
            info = state_mods.get(rid)
            if info is None:
                model, gb_id = ("Sound", int(rid[4:])) if re.fullmatch(r"snd-\d+", rid) else \
                               ("Mod", int(rid)) if rid.isdigit() else ("Mod", 0)
                info = ImportMod(key=rid, name=f"DMM mod {rid}", model=model, gb_id=gb_id)
            for name in entry.get("currentVpks") or []:
                if isinstance(name, str) and PAK_NAME_RE.match(name):
                    rel = f"{folder}/{name}"
                    if rel not in owners:
                        owners[rel] = ImportMod(key=info.key, name=info.name, model=info.model, gb_id=info.gb_id,
                                                file_id=info.file_id, file_name=info.file_name, author=info.author,
                                                category=info.category, thumb_url=info.thumb_url,
                                                vpks=[ImportVpk(label=name, main=citadel / rel)],
                                                enabled=bool(entry.get("enabled", True)))
    return owners
