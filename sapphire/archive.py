"""Extracting mod downloads (zip, 7z, rar, or a bare .vpk).

Prefers a 7-Zip binary (bundled by install.sh into the data folder, or the
system one) because it handles every format including RAR5. Falls back to
pure-Python extractors when no 7-Zip is around.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

from sapphire import paths

log = logging.getLogger(__name__)

MAGIC = {
    b"PK\x03\x04": "zip",
    b"PK\x05\x06": "zip",
    b"7z\xbc\xaf\x27\x1c": "7z",
    b"Rar!\x1a\x07": "rar",
    b"\x34\x12\xaa\x55": "vpk",
}
MAX_TOTAL_SIZE = 20 * 1024 ** 3  # refuse archives that expand past 20 GB


class ArchiveError(Exception):
    pass


def sniff(path: Path) -> str | None:
    with open(path, "rb") as fh:
        head = fh.read(8)
    for magic, kind in MAGIC.items():
        if head.startswith(magic):
            return kind
    return None


def find_7z() -> str | None:
    bundled = paths.data_dir() / "bin" / "7zz"
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    for name in ("7zz", "7z", "7za"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _check_inside(root: Path) -> None:
    """Remove anything that escaped or links outside the destination."""
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if p.is_symlink():
                p.unlink()
                continue
            try:
                p.resolve().relative_to(root)
            except ValueError as exc:
                raise ArchiveError(f"archive tried to write outside its folder: {name}") from exc


def _extract_zip(src: Path, dest: Path) -> None:
    with zipfile.ZipFile(src) as zf:
        total = sum(i.file_size for i in zf.infolist())
        if total > MAX_TOTAL_SIZE:
            raise ArchiveError("archive is too large")
        dest_resolved = dest.resolve()
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            try:
                target.relative_to(dest_resolved)
            except ValueError as exc:
                raise ArchiveError(f"unsafe path in zip: {info.filename}") from exc
        zf.extractall(dest)


def _extract_7z_py(src: Path, dest: Path) -> None:
    try:
        import py7zr
    except ImportError as exc:
        raise ArchiveError("7z archive and neither 7-Zip nor py7zr is available") from exc
    with py7zr.SevenZipFile(src, "r") as zf:
        zf.extractall(dest)


def _extract_rar_py(src: Path, dest: Path) -> None:
    try:
        import rarfile
    except ImportError as exc:
        raise ArchiveError("RAR archive and 7-Zip isn't installed") from exc
    try:
        with rarfile.RarFile(src) as rf:
            rf.extractall(dest)
    except rarfile.Error as exc:
        raise ArchiveError(
            "Couldn't extract this RAR. Re-run install.sh (it bundles 7-Zip) "
            "or install 7zip/unrar.") from exc


def _extract_with_7z(tool: str, src: Path, dest: Path) -> None:
    proc = subprocess.run(
        [tool, "x", "-y", "-bso0", "-bsp0", "-snl-", f"-o{dest}", str(src)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600,
    )
    if proc.returncode not in (0, 1):  # 1 = warnings
        msg = proc.stderr.decode(errors="replace").strip().splitlines()[-1:] or ["unknown error"]
        raise ArchiveError(f"7-Zip failed: {msg[0]}")


def extract(src: Path, dest: Path, _depth: int = 0) -> Path:
    """Extract `src` into the (new, empty) folder `dest`. Returns dest."""
    src, dest = Path(src), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    kind = sniff(src)
    if kind is None and src.suffix.lower() == ".vpk":
        kind = "vpk"
    if kind == "vpk":
        shutil.copy2(src, dest / src.name)
        return dest
    if kind is None:
        raise ArchiveError(f"{src.name} isn't a zip, 7z, rar or vpk file")

    tool = find_7z()
    if tool:
        _extract_with_7z(tool, src, dest)
    elif kind == "zip":
        _extract_zip(src, dest)
    elif kind == "7z":
        _extract_7z_py(src, dest)
    elif kind == "rar":
        _extract_rar_py(src, dest)
    _check_inside(dest)

    # Some authors zip a zip. Unpack one nested level if there are no VPKs yet.
    if _depth == 0 and not any(p.suffix.lower() == ".vpk" for p in dest.rglob("*")):
        for inner in list(dest.rglob("*")):
            if inner.is_file() and inner.suffix.lower() in (".zip", ".7z", ".rar"):
                try:
                    extract(inner, inner.with_name(inner.name + "_x"), _depth + 1)
                except ArchiveError as exc:
                    log.warning("nested archive %s failed: %s", inner.name, exc)
    return dest
