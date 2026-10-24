"""Crosshair and autoexec.cfg editing.

Deadlock keeps your crosshair in game/citadel/cfg/citadel_hero_settings.lst
(KV3 text), under `base`, as quoted strings: crosshair_pip_width = "2". Steam
Cloud keeps a copy in userdata/<account>/1422450/remote/cfg/; both are updated
so the cloud copy doesn't put the old crosshair back. Only crosshair_* keys in
`base` are ever touched, in place, keeping the file's layout and line endings
(the parser is a port of Deadlock Mod Manager's, which does the same).

Before the first change Sapphire records what each key was, so "Restore" puts
your own crosshair back exactly (a key you've changed in game since is left
alone). Crosshairs can be copied as console commands
(`citadel_crosshair_pip_width 2; ...`), the format Deadlock Mod Manager's share
codes and the console use, and pasted back.

autoexec.cfg is plain text the game runs at start when the Steam launch options
include `+exec autoexec`. An empty autoexec.cfg can crash the game with that
option set, so Sapphire never saves an empty one.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sapphire import paths, steam

log = logging.getLogger(__name__)

SETTINGS_FILE = "citadel_hero_settings.lst"
APP_ID = "1422450"
EMPTY_SETTINGS = ('<!-- kv3 encoding:text:version{e21c7f3c-8a33-41c5-9977-a76d3a32aa0d} '
                  'format:generic:version{7412167c-06e9-4698-aff2-e63eb59037e7} -->\n'
                  '{\n\tbase = \n\t{\n\t}\n\theroes = \n\t{\n\t}\n}\n')
AUTOEXEC_PLACEHOLDER = ("// autoexec.cfg: runs when Deadlock starts if its Steam launch options include +exec autoexec\n"
                        "// (kept non-empty on purpose: an empty file can crash the game with that option set)\n")


class CrosshairError(ValueError):
    pass


# ---------------------------------------------------------------------- the settings

@dataclass(frozen=True)
class Setting:
    key: str          # name in citadel_hero_settings.lst (console name is citadel_<key>)
    label: str
    kind: str         # "bool", "int", "float"
    default: float
    lo: float = 0
    hi: float = 1
    step: float = 1
    group: str = "Lines"


SETTINGS: list[Setting] = [
    Setting("crosshair_color_r", "Red", "int", 255, 0, 255, 1, "Colour"),
    Setting("crosshair_color_g", "Green", "int", 255, 0, 255, 1, "Colour"),
    Setting("crosshair_color_b", "Blue", "int", 255, 0, 255, 1, "Colour"),
    Setting("crosshair_pip_width", "Line thickness", "float", 2, 0, 20, 0.5),
    Setting("crosshair_pip_height", "Line length", "float", 16, 0, 60, 0.5),
    Setting("crosshair_pip_gap", "Gap", "int", 4, -20, 50, 1),
    Setting("crosshair_pip_opacity", "Line opacity", "float", 0.5, 0, 1, 0.05),
    Setting("crosshair_pip_gap_static", "Fixed gap (doesn't grow with spread)", "bool", 0),
    Setting("crosshair_pip_gap_collapse", "Collapse gap when aiming", "bool", 0),
    Setting("crosshair_pip_outline_border", "Line outline", "int", 1, 0, 6, 1, "Outline"),
    Setting("crosshair_pip_outline_gap", "Line outline gap", "int", 0, 0, 6, 1, "Outline"),
    Setting("crosshair_pip_outline_opacity", "Line outline opacity", "float", 0.7, 0, 1, 0.05, "Outline"),
    Setting("crosshair_dot_size", "Dot size", "float", 4, 0, 20, 0.5, "Dot"),
    Setting("crosshair_dot_opacity", "Dot opacity", "float", 0.7, 0, 1, 0.05, "Dot"),
    Setting("crosshair_dot_outline_border", "Dot outline", "int", 2, 0, 6, 1, "Dot"),
    Setting("crosshair_dot_outline_gap", "Dot outline gap", "int", 0, 0, 6, 1, "Dot"),
    Setting("crosshair_dot_outline_opacity", "Dot outline opacity", "float", 0.7, 0, 1, 0.05, "Dot"),
    Setting("crosshair_outline_color_r", "Outline red", "int", 0, 0, 255, 1, "Outline"),
    Setting("crosshair_outline_color_g", "Outline green", "int", 0, 0, 255, 1, "Outline"),
    Setting("crosshair_outline_color_b", "Outline blue", "int", 0, 0, 255, 1, "Outline"),
]
BY_KEY = {s.key: s for s in SETTINGS}
THEMED = "crosshair_themed"   # "true" = the hero's own crosshair; we set "false" to use ours


def defaults() -> dict[str, float]:
    return {s.key: s.default for s in SETTINGS}


def clamp(key: str, value) -> float:
    s = BY_KEY[key]
    if s.kind == "bool":
        if isinstance(value, str):
            return 1.0 if value.strip().strip('"').lower() in ("1", "true", "yes", "on") else 0.0
        return 1.0 if value else 0.0
    v = float(value)
    if v != v:   # NaN
        raise CrosshairError(f"{s.label} isn't a number")
    v = min(max(v, s.lo), s.hi)
    return float(round(v)) if s.kind == "int" else round(v, 3)


def wire(key: str, value: float) -> str:
    """The quoted string the settings file stores."""
    s = BY_KEY.get(key)
    if s is not None and s.kind == "bool":
        return '"true"' if value else '"false"'
    if float(value).is_integer():
        return f'"{int(value)}"'
    return f'"{float(value):g}"'


def unwire(key: str, raw: str | None):
    if raw is None:
        return None
    text = raw.strip().strip('"')
    s = BY_KEY.get(key)
    try:
        return clamp(key, text) if s else text
    except (ValueError, CrosshairError):
        return None


# ---------------------------------------------------------------------- the file format

_PUNCT = "{}[]=,"


class _Field:
    __slots__ = ("name", "start", "value_start", "value_end", "children")

    def __init__(self, name, start, value_start, value_end, children):
        self.name, self.start, self.value_start, self.value_end, self.children = \
            name, start, value_start, value_end, children


class _Parser:
    def __init__(self, src: str, pos: int):
        self.src, self.pos = src, pos

    def token(self) -> tuple[int, int]:
        src = self.src
        while True:
            while self.pos < len(src) and src[self.pos].isspace():
                self.pos += 1
            if src.startswith("//", self.pos):
                nl = src.find("\n", self.pos)
                self.pos = len(src) if nl < 0 else nl
            elif src.startswith("/*", self.pos):
                end = src.find("*/", self.pos)
                if end < 0:
                    raise CrosshairError("unterminated comment")
                self.pos = end + 2
            else:
                break
        if self.pos >= len(src):
            raise CrosshairError("unexpected end of file")
        start = self.pos
        ch = src[start]
        self.pos += 1
        if ch == '"':
            while True:
                if self.pos >= len(src):
                    raise CrosshairError("unterminated string")
                c = src[self.pos]
                if c == "\\" and self.pos + 1 < len(src):
                    self.pos += 2
                    continue
                self.pos += 1
                if c == '"':
                    break
        elif ch not in _PUNCT:
            while self.pos < len(src) and not src[self.pos].isspace() and src[self.pos] not in _PUNCT + '"/':
                self.pos += 1
        return start, self.pos

    def expect(self, text: str):
        a, b = self.token()
        if self.src[a:b] != text:
            raise CrosshairError(f"expected {text!r}")

    def obj(self, depth: int = 0) -> list[_Field]:
        if depth > 32:
            raise CrosshairError("nested too deep")
        fields: list[_Field] = []
        while True:
            a, b = self.token()
            raw = self.src[a:b]
            if raw == "}":
                return fields
            if raw.startswith('"'):
                name = json.loads(raw)
            elif re.fullmatch(r"[A-Za-z0-9_]+", raw):
                name = raw
            else:
                raise CrosshairError(f"unexpected {raw!r}")
            if any(f.name == name for f in fields):
                raise CrosshairError(f"duplicate key {name}")
            self.expect("=")
            va, vb = self.token()
            val = self.src[va:vb]
            children = None
            if val == "{":
                children = self.obj(depth + 1)
                vb = self.pos
            elif val in ("}", "=", "[", "]", ","):
                raise CrosshairError(f"unexpected {val!r}")
            fields.append(_Field(name, a, va, vb, children))


class HeroSettings:
    """citadel_hero_settings.lst, editable without disturbing anything but crosshair keys."""

    def __init__(self, source: str):
        head = source.lstrip("﻿").lstrip()
        if not head.startswith("<!-- kv3 encoding:text:"):
            raise CrosshairError("not a KV3 text settings file")
        end = source.find("-->")
        if end < 0:
            raise CrosshairError("missing KV3 header")
        p = _Parser(source, end + 3)
        p.expect("{")
        top = p.obj()
        if source[p.pos:].strip():
            raise CrosshairError("trailing data after the settings")
        base = next((f for f in top if f.name == "base"), None)
        if base is None or base.children is None:
            raise CrosshairError("no `base` block")
        self.source = source
        self.fields = base.children
        self.base_end = base.value_end - 1      # the position of base's closing brace

    def get(self, key: str) -> str | None:
        f = next((f for f in self.fields if f.name == key), None)
        if f is None:
            return None
        if f.children is not None:
            raise CrosshairError(f"{key} isn't a plain value")
        return self.source[f.value_start:f.value_end]

    def values(self) -> dict[str, str]:
        return {f.name: self.source[f.value_start:f.value_end] for f in self.fields if f.children is None}

    def update(self, changes: dict[str, str | None]) -> str:
        nl = "\r\n" if "\r\n" in self.source else "\n"
        edits: list[tuple[int, int, str]] = []
        additions = ""
        for key, value in sorted(changes.items()):
            if not re.fullmatch(r"crosshair_[a-z0-9_]+", key):
                raise CrosshairError(f"refusing to change {key}")
            if value is not None:
                p = _Parser(value, 0)
                a, b = p.token()
                if (a, b) != (0, len(value)) or value in ("{", "}", "[", "]", "=", ","):
                    raise CrosshairError(f"bad value for {key}")
            f = next((f for f in self.fields if f.name == key), None)
            if f is not None and f.children is not None:
                raise CrosshairError(f"{key} isn't a plain value")
            if f is not None and value is not None:
                edits.append((f.value_start, f.value_end, value))
            elif f is not None:
                # remove the line the key sits on
                line_start = self.source.rfind("\n", 0, f.start) + 1
                line_end = self.source.find("\n", f.value_end)
                line_end = len(self.source) if line_end < 0 else line_end + 1
                edits.append((line_start, line_end, ""))
            elif value is not None:
                additions += f"\t\t{key} = {value}{nl}"
        if additions:
            # just before base's closing brace, at the start of its line
            line_start = self.source.rfind("\n", 0, self.base_end) + 1
            edits.append((line_start, line_start, additions))
        out = self.source
        for a, b, text in sorted(edits, key=lambda e: e[0], reverse=True):
            out = out[:a] + text + out[b:]
        HeroSettings(out)   # must still parse
        return out


# ---------------------------------------------------------------------- where the files are

def settings_paths(game_dir: Path | str | None) -> list[Path]:
    """The game's copy plus every Steam Cloud copy that exists."""
    out: list[Path] = []
    if game_dir:
        out.append(Path(game_dir) / "game" / "citadel" / "cfg" / SETTINGS_FILE)
    for root in steam.steam_roots():
        ud = root / "userdata"
        try:
            accounts = [p for p in ud.iterdir() if p.is_dir() and p.name.isdigit()]
        except OSError:
            continue
        for acc in accounts:
            p = acc / APP_ID / "remote" / "cfg" / SETTINGS_FILE
            if p.is_file():
                out.append(p)
    return out


def autoexec_path(game_dir: Path | str) -> Path:
    return Path(game_dir) / "game" / "citadel" / "cfg" / "autoexec.cfg"


def _backup_file() -> Path:
    return paths.data_dir() / "crosshair-backup.json"


def _presets_file() -> Path:
    return paths.data_dir() / "crosshairs.json"


def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".sapphire-tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    tmp.replace(path)


def _read(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


# ---------------------------------------------------------------------- reading / applying

def current(game_dir) -> tuple[dict[str, float], bool]:
    """(crosshair values, themed) as the game has them now; defaults for missing keys."""
    vals = defaults()
    themed = False
    for p in settings_paths(game_dir)[:1]:
        text = _read(p)
        if text is None:
            continue
        hs = HeroSettings(text)
        for key in BY_KEY:
            v = unwire(key, hs.get(key))
            if v is not None:
                vals[key] = v
        themed = (hs.get(THEMED) or "").strip('"').lower() == "true"
    return vals, themed


def _guard_running():
    if steam.is_game_running():
        raise CrosshairError("Close Deadlock first: it rewrites these files when it quits.")


def apply(game_dir, values: dict[str, float]) -> list[Path]:
    """Write a crosshair into every settings copy. Returns the files changed."""
    _guard_running()
    wanted = {k: wire(k, clamp(k, v)) for k, v in values.items() if k in BY_KEY}
    wanted[THEMED] = '"false"'
    backup = _load_backup()
    changed: list[Path] = []
    for path in settings_paths(game_dir):
        text = _read(path)
        if text is None:
            text = EMPTY_SETTINGS
        hs = HeroSettings(text)
        rec = backup.setdefault(str(path), {})
        for key, val in wanted.items():
            cur = hs.get(key)
            saved = rec.get(key)
            # remember the user's own value the first time (or if they changed it since)
            if saved is None or not _same(cur, saved.get("applied")):
                rec[key] = {"original": cur, "applied": val}
            else:
                saved["applied"] = val
        new = hs.update(wanted)
        if new != text:
            _save_backup(backup)          # restore info first, then the change
            _write(path, new)
            changed.append(path)
    _update_machine_convars(game_dir, wanted)
    log.info("crosshair applied to %d file(s)", len(changed))
    return changed


def has_backup() -> bool:
    return bool(_load_backup())


def restore(game_dir) -> list[Path]:
    """Put back the crosshair you had before Sapphire changed it."""
    _guard_running()
    backup = _load_backup()
    changed: list[Path] = []
    for path_s, rec in list(backup.items()):
        path = Path(path_s)
        text = _read(path)
        if text is None:
            backup.pop(path_s, None)
            continue
        hs = HeroSettings(text)
        changes = {k: r.get("original") for k, r in rec.items()
                   if _same(hs.get(k), r.get("applied"))}   # untouched since: put back
        new = hs.update(changes) if changes else text
        if new != text:
            _write(path, new)
            changed.append(path)
        backup.pop(path_s, None)
    _save_backup(backup)
    return changed


def _same(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return a is b
    a, b = a.strip().strip('"'), b.strip().strip('"')
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def _load_backup() -> dict:
    try:
        data = json.loads(_backup_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_backup(data: dict):
    if data:
        _write(_backup_file(), json.dumps(data, indent=1))
    else:
        _backup_file().unlink(missing_ok=True)


def _update_machine_convars(game_dir, wanted: dict[str, str]):
    """If machine_convars.vcfg keeps citadel_crosshair_* values, bring them in line too."""
    if not game_dir:
        return
    path = Path(game_dir) / "game" / "citadel" / "cfg" / "machine_convars.vcfg"
    text = _read(path)
    if not text or "citadel_crosshair_" not in text:
        return
    new = text
    for key, val in wanted.items():
        new = re.sub(rf'("citadel_{re.escape(key)}"\s+)"[^"\r\n]*"', lambda m: m.group(1) + val, new)
    if new != text:
        _write(path, new)


# ---------------------------------------------------------------------- sharing

def to_commands(values: dict[str, float]) -> str:
    """Console form, e.g. for pasting into Deadlock's console or another manager."""
    parts = []
    for s in SETTINGS:
        v = clamp(s.key, values.get(s.key, s.default))
        text = ("1" if v else "0") if s.kind == "bool" else wire(s.key, v).strip('"')
        parts.append(f"citadel_{s.key} {text}")
    return "; ".join(parts)


def from_commands(text: str) -> dict[str, float]:
    """Parse console commands or settings-file lines. Unknown keys are ignored."""
    out: dict[str, float] = {}
    for chunk in re.split(r"[;\n\r]+", text or ""):
        m = re.match(r'\s*"?(?:citadel_)?(crosshair_[a-z0-9_]+)"?\s*(?:=\s*)?"?([^"\s;]+)"?', chunk)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key == "crosshair_pip_border":        # Deadlock Mod Manager's older name
            key = "crosshair_pip_outline_border"
            val = "1" if val.lower() in ("1", "true") else "0"
        if key in BY_KEY:
            try:
                out[key] = clamp(key, val)
            except (ValueError, CrosshairError):
                continue
    return out


def presets() -> dict[str, dict[str, float]]:
    try:
        data = json.loads(_presets_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: {kk: float(vv) for kk, vv in v.items() if kk in BY_KEY}
            for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def save_preset(name: str, values: dict[str, float]):
    data = presets()
    data[name] = {k: clamp(k, v) for k, v in values.items() if k in BY_KEY}
    _write(_presets_file(), json.dumps(data, indent=1))


def delete_preset(name: str):
    data = presets()
    if data.pop(name, None) is not None:
        _write(_presets_file(), json.dumps(data, indent=1))


# ---------------------------------------------------------------------- autoexec

def read_autoexec(game_dir) -> str:
    return _read(autoexec_path(game_dir)) or ""


def write_autoexec(game_dir, text: str) -> str:
    """Save autoexec.cfg; an empty (or whitespace-only) file becomes a comment. Returns what was saved."""
    if not text.strip():
        text = AUTOEXEC_PLACEHOLDER
    if not text.endswith("\n"):
        text += "\n"
    _write(autoexec_path(game_dir), text)
    return text


def gap_px(values: dict[str, float]) -> float:
    """How far the lines sit from the centre in the preview (Deadlock Mod Manager's model)."""
    gap = values.get("crosshair_pip_gap", 4)
    if values.get("crosshair_pip_gap_static"):
        return 4 + gap
    return 11 + gap * (1 if gap <= 0 else 2)
