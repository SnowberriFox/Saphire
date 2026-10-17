"""Colours, fonts, sizing and the Qt stylesheet.

Everything visual comes from a small set of tokens (`TOKENS`). A preset fills
them in; the user can override any token with a colour picker. `apply()`
rebuilds the stylesheet from the current values, so a theme change takes
effect live. Other modules read colours as `theme.BG`, `theme.ACCENT` etc. at
paint time, which is why those are module globals that `set_theme` rewrites.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# token -> (label shown in Settings, what it colours)
TOKENS: dict[str, tuple[str, str]] = {
    "bg": ("Background", "the main window background"),
    "panel": ("Panels", "sidebars, header, cards"),
    "raised": ("Controls", "buttons, inputs, selected rows"),
    "line": ("Lines", "borders and dividers"),
    "accent": ("Accent", "buttons, highlights, the wordmark"),
    "text": ("Text", "main text"),
    "muted": ("Muted text", "secondary text and labels"),
}

PRESETS: dict[str, dict[str, str]] = {
    "Sapphire": {"bg": "#141A23", "panel": "#1B2330", "raised": "#252F3F", "line": "#344158",
                 "accent": "#5F97F0", "text": "#E9E0CA", "muted": "#92A0B4"},
    "Amber Hand": {"bg": "#1C1713", "panel": "#241E18", "raised": "#322A22", "line": "#4A3E33",
                   "accent": "#E0A24A", "text": "#F0E6D2", "muted": "#A89C8A"},
    "Patina": {"bg": "#18211F", "panel": "#212C29", "raised": "#2B3834", "line": "#3A4A45",
               "accent": "#C9A15A", "text": "#E9E0CA", "muted": "#93A39B"},
    "Midnight": {"bg": "#0F1012", "panel": "#161719", "raised": "#222326", "line": "#333539",
                 "accent": "#D7D7DE", "text": "#EDEDEF", "muted": "#8E9097"},
    "Oxblood": {"bg": "#1A1416", "panel": "#231A1D", "raised": "#30252A", "line": "#4A3A41",
                "accent": "#D4705F", "text": "#F1E6E3", "muted": "#A8949A"},
    "Parchment": {"bg": "#F3EEE3", "panel": "#EAE3D4", "raised": "#DFD6C3", "line": "#C9BEA8",
                  "accent": "#2F5CAE", "text": "#2A2621", "muted": "#6E675D"},
}
DEFAULT_PRESET = "Sapphire"

SCALES: dict[str, float] = {"Small": 0.88, "Normal": 1.0, "Large": 1.15, "Huge": 1.3}
SCALE = 1.0

# Fixed semantic colours (success / danger), tuned per light or dark background.
OXBLOOD = "#B65A4E"
VERDIGRIS = "#6FAE8F"
DANGER_TEXT = "#E8A598"
DANGER_BG = "#3A2228"
OK_BG = "#1E3A2F"

# Current token values (filled by set_theme)
BG = PANEL = RAISED = LINE = ACCENT = ACCENT_HI = ACCENT_LO = TEXT = MUTED = ON_ACCENT = ""
HOVER = BANNER_BG = ""
PRESET = DEFAULT_PRESET

DISPLAY_FAMILY = "Josefin Sans"
BODY_FAMILY = "Inter"


# ---------------------------------------------------------------- colour maths

def _shift(hex_color: str, lightness: float, sat: float = 1.0) -> str:
    c = QColor(hex_color)
    h, s, l, a = c.getHslF()
    l = max(0.0, min(1.0, l + lightness))
    s = max(0.0, min(1.0, s * sat))
    out = QColor.fromHslF(h if h >= 0 else 0, s, l, a)
    return out.name()


def is_light(hex_color: str) -> bool:
    return QColor(hex_color).lightnessF() > 0.55


def mix(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(int(ca.red() + (cb.red() - ca.red()) * t), int(ca.green() + (cb.green() - ca.green()) * t),
                  int(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def resolve(tokens: dict[str, str]) -> dict[str, str]:
    """Full colour set (including derived ones) for a token dict."""
    t = dict(PRESETS[DEFAULT_PRESET])
    t.update({k: v for k, v in tokens.items() if k in TOKENS and QColor(v).isValid()})
    accent = t["accent"]
    light_bg = is_light(t["bg"])
    return {
        **t,
        "accent_hi": _shift(accent, -0.10 if light_bg else 0.12),
        "accent_lo": _shift(accent, 0.12 if light_bg else -0.18),
        "on_accent": "#1A1A1A" if is_light(accent) else "#FFFFFF",
        "hover": mix(t["bg"], t["raised"], 0.5),
        "banner_bg": mix(t["panel"], accent, 0.18),
    }


def set_theme(preset: str | None = None, overrides: dict[str, str] | None = None) -> None:
    global BG, PANEL, RAISED, LINE, ACCENT, ACCENT_HI, ACCENT_LO, TEXT, MUTED, ON_ACCENT, HOVER, BANNER_BG, PRESET
    PRESET = preset if preset in PRESETS else DEFAULT_PRESET
    base = dict(PRESETS[PRESET])
    base.update(overrides or {})
    r = resolve(base)
    BG, PANEL, RAISED, LINE = r["bg"], r["panel"], r["raised"], r["line"]
    ACCENT, ACCENT_HI, ACCENT_LO = r["accent"], r["accent_hi"], r["accent_lo"]
    TEXT, MUTED, ON_ACCENT, HOVER, BANNER_BG = r["text"], r["muted"], r["on_accent"], r["hover"], r["banner_bg"]


def current_tokens() -> dict[str, str]:
    return {"bg": BG, "panel": PANEL, "raised": RAISED, "line": LINE, "accent": ACCENT, "text": TEXT, "muted": MUTED}


set_theme(DEFAULT_PRESET)


# ---------------------------------------------------------------------- fonts

def load_fonts() -> tuple[str, str]:
    """Register the bundled fonts. Returns (display family, body family)."""
    def add(names: list[str], fallback: str) -> str:
        family = ""
        for name in names:
            fid = QFontDatabase.addApplicationFont(str(ASSETS / name))
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            family = family or (fams[0] if fams else "")
        return family or fallback
    display = add(["JosefinSans-SemiBold.ttf"], "sans-serif")
    body = add(["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"], "sans-serif")
    return display, body


def px(n: float) -> int:
    """Scale a design pixel size by the UI size setting."""
    return max(1, round(n * SCALE))


def display_font(size: int) -> QFont:
    f = QFont(DISPLAY_FAMILY)
    f.setPixelSize(px(size))
    f.setWeight(QFont.DemiBold)
    return f


# ----------------------------------------------------------------- stylesheet

def build_stylesheet() -> str:
    sheet = f"""
* {{ outline: none; }}
QWidget {{ background: {BG}; color: {TEXT}; font-family: "{BODY_FAMILY}"; font-size: 13px; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px 6px; }}

#Header {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
#Wordmark {{ background: transparent; color: {ACCENT}; font-family: "{DISPLAY_FAMILY}"; font-size: 24px; font-weight: 600; padding-top: 4px; }}
#NavButton {{ background: transparent; color: {MUTED}; border: none; padding: 8px 12px;
              font-size: 14px; border-bottom: 2px solid transparent; }}
#NavButton:hover {{ color: {TEXT}; }}
#NavButton:checked {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}

#LaunchButton {{ background: {ACCENT}; color: {ON_ACCENT}; border: none; border-radius: 6px;
                 padding: 9px 20px; font-size: 14px; font-weight: 600; }}
#LaunchButton:hover {{ background: {ACCENT_HI}; }}
#LaunchButton:pressed {{ background: {ACCENT_LO}; }}
#LaunchButton:disabled {{ background: {RAISED}; color: {MUTED}; }}

#StatusPill {{ background: transparent; color: {MUTED}; padding: 4px 10px; border: 1px solid {LINE};
               border-radius: 11px; font-size: 12px; }}
#StatusPill[state="ok"] {{ color: {VERDIGRIS}; border-color: {mix(LINE, VERDIGRIS, 0.4)}; }}
#StatusPill[state="warn"] {{ color: {ACCENT_HI}; border-color: {ACCENT_LO}; }}
#StatusPill[state="bad"] {{ color: {DANGER_TEXT}; border-color: {OXBLOOD}; }}

#PageTitle {{ background: transparent; font-family: "{DISPLAY_FAMILY}"; font-size: 22px; font-weight: 600; color: {TEXT}; padding-top: 3px; }}
#SideTitle {{ background: transparent; color: {MUTED}; font-size: 12px; font-weight: 600; padding-top: 6px; }}
#Muted {{ background: transparent; color: {MUTED}; }}
#Panel, #FilterPanel, #DetailPanel {{ background: {PANEL}; }}
#DetailTitle {{ background: transparent; font-family: "{DISPLAY_FAMILY}"; font-size: 20px; font-weight: 600; color: {TEXT}; padding-top: 3px; }}
#Banner {{ background: {BANNER_BG}; color: {ACCENT_HI if not is_light(BG) else ACCENT_LO}; border: 1px solid {ACCENT_LO}; border-radius: 6px; padding: 8px 12px; }}
#BannerBad {{ background: {mix(PANEL, OXBLOOD, 0.25)}; color: {DANGER_TEXT if not is_light(BG) else "#7A2E24"}; border: 1px solid {OXBLOOD}; border-radius: 6px; padding: 8px 12px; }}
#Swatch {{ border: 1px solid {LINE}; border-radius: 5px; min-width: 44px; min-height: 24px; }}
#Swatch:hover {{ border-color: {ACCENT}; }}

QLineEdit, QComboBox, QSpinBox {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 5px;
                       padding: 6px 8px; selection-background-color: {ACCENT_LO}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {RAISED}; border: 1px solid {LINE}; selection-background-color: {ACCENT_LO}; }}

QPushButton {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 5px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT_LO}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {mix(MUTED, BG, 0.4)}; border-color: {mix(LINE, BG, 0.4)}; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; color: {ON_ACCENT}; border: none; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {ACCENT_HI}; }}
QPushButton[kind="primary"]:disabled {{ background: {RAISED}; color: {MUTED}; }}
QPushButton[kind="danger"] {{ color: {DANGER_TEXT if not is_light(BG) else "#9A3A2E"}; }}
QPushButton[kind="danger"]:hover {{ border-color: {OXBLOOD}; }}
QPushButton[kind="toggle"] {{ border-radius: 0; }}
QPushButton[kind="toggle"]:checked {{ background: {ACCENT_LO}; color: {TEXT}; border-color: {ACCENT_LO}; }}

QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {LINE}; background: {RAISED}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url(@CHECK@); }}
QCheckBox::indicator:focus {{ border-color: {ACCENT}; }}

QListView, QTreeWidget, QListWidget, QTextBrowser {{ background: {BG}; border: none; }}
QTreeWidget#CategoryTree {{ background: {PANEL}; }}
QTreeView::item {{ padding: 4px 2px; }}
QTreeView::item:selected, QListWidget::item:selected {{ background: {RAISED}; color: {ACCENT_HI if not is_light(BG) else ACCENT_LO}; }}
QTreeView::item:hover {{ background: {HOVER}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {mix(LINE, TEXT, 0.15)}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ height: 0; }}

QProgressBar {{ background: {RAISED}; border: none; border-radius: 3px; height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}

QStatusBar {{ background: {PANEL}; color: {MUTED}; border-top: 1px solid {LINE}; }}
QStatusBar QLabel {{ background: transparent; color: {MUTED}; padding: 0 10px; }}
QSplitter::handle {{ background: {LINE}; }}
QMenu {{ background: {RAISED}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_LO}; }}
QDialog {{ background: {PANEL}; }}
QMessageBox {{ background: {PANEL}; }}
"""
    sheet = sheet.replace('"Josefin Sans"', f'"{DISPLAY_FAMILY}"').replace('"Inter"', f'"{BODY_FAMILY}"')
    sheet = sheet.replace("@CHECK@", (ASSETS / "check.svg").as_posix())
    if SCALE != 1.0:
        sheet = re.sub(r"(\d+)px", lambda m: f"{px(int(m.group(1)))}px", sheet)
    return sheet


_fonts_loaded = False


def apply(app: QApplication, preset: str | None = None, overrides: dict[str, str] | None = None,
          scale: float | None = None) -> None:
    """(Re)apply the theme. Safe to call again at runtime."""
    global DISPLAY_FAMILY, BODY_FAMILY, SCALE, _fonts_loaded
    if not _fonts_loaded:
        DISPLAY_FAMILY, BODY_FAMILY = load_fonts()
        app.setStyle("Fusion")
        _fonts_loaded = True
    if scale is not None:
        SCALE = scale
    if preset is not None or overrides is not None:
        set_theme(preset or PRESET, overrides)
    body = QFont(BODY_FAMILY)
    body.setPixelSize(px(13))
    app.setFont(body)
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.Base, RAISED), (QPalette.AlternateBase, PANEL),
        (QPalette.Text, TEXT), (QPalette.WindowText, TEXT), (QPalette.Button, RAISED),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT_LO), (QPalette.HighlightedText, TEXT),
        (QPalette.ToolTipBase, RAISED), (QPalette.ToolTipText, TEXT), (QPalette.Link, ACCENT_HI),
        (QPalette.PlaceholderText, mix(MUTED, BG, 0.3)),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet())
