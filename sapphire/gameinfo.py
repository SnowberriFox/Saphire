"""Patching game/citadel/gameinfo.gi so Deadlock loads addon VPKs.

Instead of replacing Valve's whole SearchPaths block with a hardcoded copy
(which breaks whenever Valve changes it), Sapphire inserts one small, clearly
marked block right before the `Game citadel` line and leaves everything else
byte-for-byte untouched, including Windows line endings.

Game updates and "Verify integrity" replace gameinfo.gi, which removes the
block; `needs_patch` detects that and the manager re-applies it.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

MARK_BEGIN = "// >>> Sapphire mod folders (managed automatically, don't edit) >>>"
MARK_END = "// <<< Sapphire <<<"

# Markers other managers leave behind; used to clean up their patches.
FOREIGN_MARKERS = ("deadlock mod manager", "grimoire", "mod manager - start", "mod manager - end")


class GameInfoError(Exception):
    pass


def gameinfo_path(game_dir: Path | str) -> Path:
    return Path(game_dir) / "game" / "citadel" / "gameinfo.gi"


# ------------------------------------------------------------------ text helpers

def _strip_comment(line: str) -> str:
    in_quote = False
    for i, c in enumerate(line):
        if c == '"':
            in_quote = not in_quote
        elif c == "/" and not in_quote and line.startswith("//", i):
            return line[:i]
    return line


def _kv(line: str) -> tuple[str, str] | None:
    parts = re.findall(r'"[^"]*"|[^\s"]+', _strip_comment(line))
    if len(parts) != 2:
        return None
    key, value = (p.strip('"') for p in parts)
    return key.lower(), value.lower().replace("\\", "/")


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _find_searchpaths(lines: list[str]) -> tuple[int, int]:
    """Return (open_brace_line, close_brace_line) of the SearchPaths block."""
    for i, line in enumerate(lines):
        body = _strip_comment(line).strip().strip('"')
        if body.split("{")[0].strip().strip('"').lower() != "searchpaths":
            continue
        # Find the opening brace (same line or a following one).
        j = i
        while j < len(lines) and "{" not in _strip_comment(lines[j]):
            j += 1
        if j >= len(lines):
            break
        depth = 0
        for k in range(j, len(lines)):
            code = _strip_comment(lines[k])
            depth += code.count("{") - code.count("}")
            if depth == 0:
                return j, k
        raise GameInfoError("SearchPaths block is never closed")
    raise GameInfoError("Couldn't find the SearchPaths block in gameinfo.gi")


@dataclass
class GameInfoStatus:
    patched: bool                 # our block is present
    folders: list[str] = field(default_factory=list)  # folders listed in our block
    foreign: bool = False         # another tool (or a manual edit) added addon paths


def inspect(text: str) -> GameInfoStatus:
    lines = text.splitlines(keepends=True)
    start, end = _find_searchpaths(lines)
    status = GameInfoStatus(patched=False)
    inside = False
    for line in lines[start + 1:end]:
        stripped = line.strip()
        if stripped.startswith(MARK_BEGIN):
            status.patched = True
            inside = True
            continue
        if stripped.startswith(MARK_END):
            inside = False
            continue
        kv = _kv(line)
        if inside:
            if kv and kv[0] == "game":
                status.folders.append(kv[1])
        else:
            if kv and kv[1].startswith("citadel/addons"):
                status.foreign = True
            if stripped.startswith("//") and any(m in stripped.lower() for m in FOREIGN_MARKERS):
                status.foreign = True
    return status


def needs_patch(text: str, folders: list[str]) -> bool:
    st = inspect(text)
    return (not st.patched) or st.foreign or st.folders != [f.lower() for f in folders]


def _clean_block(block: list[str], foreign: bool) -> list[str]:
    """Remove our own block and, if present, other managers' edits."""
    out: list[str] = []
    inside = False
    seen_game: set[str] = set()
    for line in block:
        stripped = line.strip()
        if stripped.startswith(MARK_BEGIN):
            inside = True
            continue
        if stripped.startswith(MARK_END):
            inside = False
            continue
        if inside:
            continue
        if foreign:
            if stripped.startswith("//") and any(m in stripped.lower() for m in FOREIGN_MARKERS):
                continue
            kv = _kv(line)
            if kv:
                key, value = kv
                if value.startswith("citadel/addons"):
                    continue
                # Vanilla Deadlock has no Mod/Write keys; other managers add them.
                if key in ("mod", "write"):
                    continue
                if key == "game":
                    if value in seen_game:
                        continue
                    seen_game.add(value)
        out.append(line)
    return out


def patch(text: str, folders: list[str]) -> str:
    """Return gameinfo text with our block listing `folders` (e.g. ['citadel/addons'])."""
    if not folders:
        return unpatch(text)
    nl = _newline(text)
    lines = text.splitlines(keepends=True)
    start, end = _find_searchpaths(lines)
    status = inspect(text)
    inner = _clean_block(lines[start + 1:end], status.foreign)

    insert_at = None
    for idx, line in enumerate(inner):
        kv = _kv(line)
        if kv == ("game", "citadel"):
            insert_at = idx
            break
    if insert_at is None:
        for idx, line in enumerate(inner):
            kv = _kv(line)
            if kv and kv[0] == "game":
                insert_at = idx
                break
    if insert_at is None:
        raise GameInfoError("SearchPaths has no Game entries; refusing to patch")

    anchor = inner[insert_at]
    indent = anchor[: len(anchor) - len(anchor.lstrip())] or "\t\t\t"
    block = [indent + MARK_BEGIN + nl]
    block += [f"{indent}Game\t\t\t\t{f}{nl}" for f in folders]
    block += [f"{indent}Mod\t\t\t\t\tcitadel{nl}", f"{indent}Write\t\t\t\tcitadel{nl}"]
    block += [indent + MARK_END + nl]
    inner[insert_at:insert_at] = block
    result = "".join(lines[: start + 1] + inner + lines[end:])
    _validate(result)
    return result


def unpatch(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start, end = _find_searchpaths(lines)
    status = inspect(text)
    inner = _clean_block(lines[start + 1:end], status.foreign)
    result = "".join(lines[: start + 1] + inner + lines[end:])
    _validate(result)
    return result


def _validate(text: str) -> None:
    depth = 0
    for line in text.splitlines():
        code = _strip_comment(line)
        depth += code.count("{") - code.count("}")
        if depth < 0:
            raise GameInfoError("generated gameinfo.gi has unbalanced braces")
    if depth != 0:
        raise GameInfoError("generated gameinfo.gi has unbalanced braces")
    _find_searchpaths(text.splitlines(keepends=True))


# ------------------------------------------------------------------- file level

def read(game_dir: Path | str) -> str:
    path = gameinfo_path(game_dir)
    try:
        with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as fh:
            return fh.read()
    except FileNotFoundError as exc:
        raise GameInfoError(f"gameinfo.gi not found at {path}") from exc


def _write_atomic(path: Path, text: str) -> None:
    mode = None
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:
        pass
    tmp = path.with_name(path.name + ".sapphire-tmp")
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    if mode is not None:
        os.chmod(tmp, mode | stat.S_IWUSR)
    os.replace(tmp, path)


def backup(game_dir: Path | str, backup_dir: Path) -> Path | None:
    """Keep a copy of gameinfo.gi before we change it (last 5 kept)."""
    src = gameinfo_path(game_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    dst = backup_dir / f"gameinfo-{time.strftime('%Y%m%d-%H%M%S')}.gi"
    try:
        shutil.copy2(src, dst)
    except OSError as exc:
        log.warning("gameinfo backup failed: %s", exc)
        return None
    for old in sorted(backup_dir.glob("gameinfo-*.gi"))[:-5]:
        old.unlink(missing_ok=True)
    return dst


def apply(game_dir: Path | str, folders: list[str], backup_dir: Path | None = None) -> bool:
    """Make gameinfo.gi list exactly `folders`. Returns True if the file changed."""
    text = read(game_dir)
    new = patch(text, folders) if folders else unpatch(text)
    if new == text:
        return False
    if backup_dir is not None:
        backup(game_dir, backup_dir)
    _write_atomic(gameinfo_path(game_dir), new)
    log.info("gameinfo.gi updated (folders=%s)", folders)
    return True
