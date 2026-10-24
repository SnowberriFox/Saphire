"""Patch notes shown when Sapphire opens (Settings → Sapphire → Patch notes).

The notes are CHANGELOG.md, shipped inside the package (sapphire/assets has a
link to the repo's copy, which the build turns into a real file).
"""

from __future__ import annotations

import re
from pathlib import Path

from sapphire import __version__
from sapphire.updater import parse_version

MODES = {"update": "After an update", "always": "Every time Sapphire opens", "never": "Never"}
_HEADING = re.compile(r"^## +(\d+\.\d+(?:\.\d+)?)\b.*$", re.M)


def changelog_text() -> str:
    here = Path(__file__).resolve().parent
    for p in (here / "assets" / "CHANGELOG.md", here.parent / "CHANGELOG.md"):
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def sections(text: str) -> list[tuple[str, str, str]]:
    """(version, heading line, body) for every '## x.y.z' section, newest first as written."""
    out = []
    marks = list(_HEADING.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1), m.group(0)[3:].strip(), text[m.end():end].strip()))
    return out


def notes_between(text: str, seen: str, current: str = __version__, limit: int = 4) -> list[tuple[str, str]]:
    """(heading, body) for the versions after `seen` up to `current`, newest
    first, at most `limit`. Just `current` when `seen` is unknown or not older."""
    cur = parse_version(current)
    secs = sections(text)
    if not seen or parse_version(seen) >= cur:
        return [(h, b) for v, h, b in secs if parse_version(v) == cur][:1]
    old = parse_version(seen)
    return [(h, b) for v, h, b in secs if old < parse_version(v) <= cur][:limit]


def should_show(mode: str, seen: str, fresh_install: bool = False, current: str = __version__) -> bool:
    """Whether to open the patch notes now. `seen` is the version they were last
    shown for ('' = never: an install from before patch notes, unless it's a
    brand-new install, which gets the setup wizard instead)."""
    if mode == "never" or fresh_install:
        return False
    if mode == "always":
        return True
    return not seen or parse_version(seen) < parse_version(current)
