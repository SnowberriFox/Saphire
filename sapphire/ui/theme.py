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

from PySide6.QtCore import Qt
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
    # Fan themes: black boxes, thick white borders, pixel type, a red soul.
    "Undertale": {"bg": "#000000", "panel": "#000000", "raised": "#0E0E0E", "line": "#FFFFFF",
                  "accent": "#FFFF00", "text": "#FFFFFF", "muted": "#A8A8A8"},
    "Deltarune": {"bg": "#0B0618", "panel": "#100A22", "raised": "#1C1336", "line": "#FFFFFF",
                  "accent": "#FFFF00", "text": "#FFFFFF", "muted": "#ABA0D6"},
}
DEFAULT_PRESET = "Sapphire"

# Presets that change more than colours. "pixel": square corners, white box
# borders, pixel fonts, buttons in `button` that turn the accent colour when
# you point at them, progress bars like an HP bar, and a `soul` heart marking
# what's selected.
STYLES: dict[str, dict[str, str]] = {
    "Undertale": {"style": "pixel", "button": "#FF7F27", "soul": "#FF0000", "bar_bg": "#C00000"},
    "Deltarune": {"style": "pixel", "button": "#FFA040", "soul": "#FF0000", "bar_bg": "#3B2466"},
}

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
OVERRIDES: dict[str, str] = {}

# Current style (filled by set_theme)
PIXEL = False          # the boxy pixel look
BUTTON = SOUL = BAR_BG = ""
ROUND = 1.0            # corner radius multiplier (0 = square)
FONT_BOOST = 1.0       # pixel fonts read small: body text sizes are multiplied by this
DISPLAY_BOOST = 1.0    # ...and the wide title font the other way

DISPLAY_FAMILY = "Josefin Sans"
BODY_FAMILY = "Inter"
TEXT_FONT = TITLE_FONT = ""      # the person's choice in Settings ("" = the theme's)

# Fonts that ship with Sapphire (all SIL Open Font License, texts in assets/).
BUNDLED_FONTS: dict[str, list[str]] = {
    "Inter": ["Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Bold.ttf"],
    "Josefin Sans": ["JosefinSans-SemiBold.ttf"],
    "Chakra Petch": ["ChakraPetch-Regular.ttf", "ChakraPetch-SemiBold.ttf"],
    "Atkinson Hyperlegible Mono": ["AtkinsonHyperlegibleMono.ttf"],
    "Share Tech Mono": ["ShareTechMono-Regular.ttf"],
    "Space Mono": ["SpaceMono-Regular.ttf", "SpaceMono-Bold.ttf"],
    "Pixelify Sans": ["PixelifySans.ttf"],
    "VT323": ["VT323-Regular.ttf"],
    "Press Start 2P": ["PressStart2P-Regular.ttf"],
}
PIXEL_FAMILIES = {"Press Start 2P", "Pixelify Sans", "VT323"}   # drawn without anti-aliasing
# Fonts that look small or large at the same pixel size get nudged so text
# lines up whatever's picked.
SIZE_ADJUST = {"Pixelify Sans": 1.18, "VT323": 1.4, "Press Start 2P": 0.7, "Space Mono": 0.94,
               "Atkinson Hyperlegible Mono": 0.94, "Share Tech Mono": 1.06, "Chakra Petch": 1.04}

# Each look's own fonts (first = what it uses unless you pick something else)
# and the ones that suit it, offered first in Settings.
RECOMMENDED: dict[str, dict[str, list[str]]] = {
    "smooth": {"text": ["Inter", "Atkinson Hyperlegible Mono", "Chakra Petch"],
               "titles": ["Josefin Sans", "Inter", "Chakra Petch"]},
    "pixel": {"text": ["Chakra Petch", "Pixelify Sans", "Atkinson Hyperlegible Mono", "Share Tech Mono",
                       "Space Mono", "VT323"],
              "titles": ["Press Start 2P", "Pixelify Sans", "VT323", "Chakra Petch"]},
}


def look(preset: str | None = None) -> str:
    return "pixel" if STYLES.get(preset or PRESET, {}).get("style") == "pixel" else "smooth"


def recommended(kind: str, preset: str | None = None) -> list[str]:
    """Fonts that suit a theme, for "text" or "titles"; the first is its default."""
    return list(RECOMMENDED[look(preset)][kind])


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


def set_theme(preset: str | None = None, overrides: dict[str, str] | None = None,
              text_font: str | None = None, title_font: str | None = None) -> None:
    global BG, PANEL, RAISED, LINE, ACCENT, ACCENT_HI, ACCENT_LO, TEXT, MUTED, ON_ACCENT, HOVER, BANNER_BG, PRESET
    global PIXEL, BUTTON, SOUL, BAR_BG, ROUND, FONT_BOOST, DISPLAY_BOOST, DISPLAY_FAMILY, BODY_FAMILY, OVERRIDES
    global TEXT_FONT, TITLE_FONT
    PRESET = preset if preset in PRESETS else DEFAULT_PRESET
    OVERRIDES = dict(overrides or {})
    base = dict(PRESETS[PRESET])
    base.update(overrides or {})
    r = resolve(base)
    BG, PANEL, RAISED, LINE = r["bg"], r["panel"], r["raised"], r["line"]
    ACCENT, ACCENT_HI, ACCENT_LO = r["accent"], r["accent_hi"], r["accent_lo"]
    TEXT, MUTED, ON_ACCENT, HOVER, BANNER_BG = r["text"], r["muted"], r["on_accent"], r["hover"], r["banner_bg"]
    style = STYLES.get(PRESET, {})
    PIXEL = style.get("style") == "pixel"
    BUTTON = style.get("button", ACCENT)
    SOUL = style.get("soul", ACCENT)
    BAR_BG = style.get("bar_bg", RAISED)
    ROUND = 0.0 if PIXEL else 1.0
    if PIXEL:
        # the accent is the "selected" yellow; selections and highlights use it directly
        ACCENT_HI = ACCENT_LO = ACCENT
        ON_ACCENT = "#000000"
    if text_font is not None:
        TEXT_FONT = text_font
    if title_font is not None:
        TITLE_FONT = title_font
    BODY_FAMILY = TEXT_FONT or recommended("text")[0]
    DISPLAY_FAMILY = TITLE_FONT or recommended("titles")[0]
    FONT_BOOST = SIZE_ADJUST.get(BODY_FAMILY, 1.0)
    DISPLAY_BOOST = SIZE_ADJUST.get(DISPLAY_FAMILY, 1.0)


def current_tokens() -> dict[str, str]:
    return {"bg": BG, "panel": PANEL, "raised": RAISED, "line": LINE, "accent": ACCENT, "text": TEXT, "muted": MUTED}


set_theme(DEFAULT_PRESET)


# ---------------------------------------------------------------------- fonts

def load_fonts() -> None:
    """Register the bundled fonts with Qt."""
    for family, files in BUNDLED_FONTS.items():
        for name in files:
            fid = QFontDatabase.addApplicationFont(str(ASSETS / name))
            if fid < 0:
                continue
            got = QFontDatabase.applicationFontFamilies(fid)
            if got and got[0] != family:
                # a font that names itself differently: remember its real name
                log_name_mismatch(family, got[0])


def log_name_mismatch(expected: str, actual: str) -> None:
    import logging
    logging.getLogger(__name__).warning("font %s registered as %r", expected, actual)




def px(n: float) -> int:
    """Scale a design pixel size by the UI size setting."""
    return max(1, round(n * SCALE))


def fpx(n: float) -> int:
    """A body text size: scaled, and bigger for pixel fonts."""
    return px(n * FONT_BOOST)


def rad(n: float) -> float:
    """A corner radius: 0 in the boxy themes."""
    return n * ROUND


def display_font(size: int) -> QFont:
    f = QFont(DISPLAY_FAMILY)
    f.setPixelSize(px(size * DISPLAY_BOOST))
    f.setWeight(QFont.Normal if DISPLAY_FAMILY in PIXEL_FAMILIES else QFont.DemiBold)
    if DISPLAY_FAMILY in PIXEL_FAMILIES:
        f.setStyleStrategy(QFont.NoAntialias)
    return f


def soul_space(selected: bool) -> int:
    """Room to leave before a selected item's name for the soul (0 when not drawn)."""
    return px(16) if PIXEL and selected else 0


def soul_at(p, x: float, center_y: float) -> None:
    """Draw the soul just left of a name starting at x (call with soul_space room)."""
    from PySide6.QtCore import QRectF
    s = px(11)
    draw_soul(p, QRectF(x, center_y - s / 2, s * 9 / 8, s))


def soul_icon():
    """A QIcon showing the soul only when its button is checked (nav tabs), or
    an empty icon outside the pixel themes."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    icon = QIcon()
    if not PIXEL:
        return icon
    w, h = px(18) * 2, px(16) * 2          # drawn at 2x so it stays crisp on HiDPI
    on = QPixmap(w, h)
    on.fill(Qt.transparent)
    painter = QPainter(on)
    draw_soul(painter, QRectF(0, 0, w, h))
    painter.end()
    off = QPixmap(w, h)
    off.fill(Qt.transparent)              # same size, so labels don't shift
    icon.addPixmap(on, QIcon.Normal, QIcon.On)
    icon.addPixmap(off, QIcon.Normal, QIcon.Off)
    icon.addPixmap(on, QIcon.Active, QIcon.On)
    icon.addPixmap(off, QIcon.Active, QIcon.Off)
    return icon


def pixel_frame(p, rect, selected: bool, hovered: bool) -> None:
    """The box border around cards and rows in the pixel themes: dim, white
    when pointed at, yellow when selected. Does nothing in the other themes."""
    if not PIXEL:
        return
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter, QPen
    p.save()
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setOpacity(1.0)
    color = ACCENT if selected else (LINE if hovered else mix(LINE, BG, 0.62))
    pen = QPen(QColor(color), 2)
    pen.setJoinStyle(Qt.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(rect).adjusted(1, 1, -1, -1))
    p.restore()


def draw_soul(p, rect) -> None:
    """The red pixel heart that marks what's selected in the pixel themes."""
    from PySide6.QtCore import QRectF
    p.save()
    r = QRectF(rect)
    cell = min(r.width() / 9, r.height() / 8)
    ox, oy = r.left() + (r.width() - 9 * cell) / 2, r.top() + (r.height() - 8 * cell) / 2
    rows = ("011000110", "111101111", "111111111", "111111111", "011111110", "001111100", "000111000", "000010000")
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(SOUL))
    for y, row in enumerate(rows):
        for x, on in enumerate(row):
            if on == "1":
                p.drawRect(QRectF(ox + x * cell, oy + y * cell, cell + 0.01, cell + 0.01))
    p.restore()


# ----------------------------------------------------------------- stylesheet

def _dsz(n: int) -> int:
    """A title font size, adjusted for the title font."""
    return round(n * DISPLAY_BOOST)


def build_stylesheet() -> str:
    sheet = f"""
* {{ outline: none; }}
QWidget {{ background: {BG}; color: {TEXT}; font-family: "{BODY_FAMILY}"; font-size: 13px; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px 6px; }}

#Header {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
#Wordmark {{ background: transparent; color: {ACCENT}; font-family: "{DISPLAY_FAMILY}"; font-size:{_dsz(24)}px; font-weight: 600; padding-top: 4px; }}
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

#PageTitle {{ background: transparent; font-family: "{DISPLAY_FAMILY}"; font-size:{_dsz(22)}px; font-weight: 600; color: {TEXT}; padding-top: 3px; }}
#SideTitle {{ background: transparent; color: {MUTED}; font-size: 12px; font-weight: 600; padding-top: 6px; }}
#Muted {{ background: transparent; color: {MUTED}; }}
#Panel, #FilterPanel, #DetailPanel {{ background: {PANEL}; }}
#DetailTitle {{ background: transparent; font-family: "{DISPLAY_FAMILY}"; font-size:{_dsz(20)}px; font-weight: 600; color: {TEXT}; padding-top: 3px; }}
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
    # Text sizes follow the text font ("font-size: 13px"); title sizes were
    # already worked out for the title font ("font-size:24px", no space).
    if FONT_BOOST != 1.0:
        sheet = re.sub(r"font-size: (\d+)px", lambda m: f"font-size: {round(int(m.group(1)) * FONT_BOOST)}px", sheet)
    if PIXEL:
        sheet = re.sub(r"border-radius: \d+px", "border-radius: 0px", sheet)
        sheet += _pixel_sheet()
    if SCALE != 1.0:
        sheet = re.sub(r"(\d+)px", lambda m: f"{px(int(m.group(1)))}px", sheet)
    return sheet


def _pixel_sheet() -> str:
    """The boxy look, layered over the normal stylesheet: white box borders,
    orange buttons that turn yellow, an HP-bar progress bar."""
    weight = "normal" if DISPLAY_FAMILY in PIXEL_FAMILIES else "600"
    return f"""
#Header {{ border-bottom: 3px solid {LINE}; }}
#Wordmark {{ color: {TEXT}; font-weight: {weight}; padding-top: 6px; }}
#PageTitle {{ font-weight: {weight}; padding-top: 6px; }}
#DetailTitle {{ font-family: "{BODY_FAMILY}"; font-size:{round(20 * FONT_BOOST)}px; font-weight: 600; }}
#NavButton {{ color: {TEXT}; border-bottom: none; padding: 8px 10px; }}
#NavButton:hover {{ color: {ACCENT}; }}
#NavButton:checked {{ color: {ACCENT}; border-bottom: none; }}
#FilterPanel {{ border-right: 3px solid {LINE}; }}
#DetailPanel {{ border-left: 3px solid {LINE}; }}
#Panel {{ border: 2px solid {LINE}; }}
#LaunchButton {{ background: {BG}; color: {BUTTON}; border: 2px solid {BUTTON}; }}
#LaunchButton:hover {{ background: {BG}; color: {ACCENT}; border-color: {ACCENT}; }}
#LaunchButton:pressed {{ background: {ACCENT}; color: #000000; }}
#StatusPill {{ border: 2px solid {LINE}; }}
#Banner, #BannerBad {{ border-width: 2px; }}
QPushButton {{ background: {BG}; color: {BUTTON}; border: 2px solid {BUTTON}; padding: 6px 12px; }}
QPushButton:hover, QPushButton:focus {{ color: {ACCENT}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT}; color: #000000; }}
QPushButton:disabled {{ color: {mix(BUTTON, BG, 0.55)}; border-color: {mix(BUTTON, BG, 0.55)}; }}
QPushButton[kind="primary"] {{ background: {BUTTON}; color: #000000; border: 2px solid {BUTTON}; }}
QPushButton[kind="primary"]:hover {{ background: {ACCENT}; border-color: {ACCENT}; }}
QPushButton[kind="primary"]:disabled {{ background: {BG}; color: {MUTED}; border-color: {MUTED}; }}
QPushButton[kind="danger"] {{ color: {DANGER_TEXT}; border-color: {DANGER_TEXT}; }}
QPushButton[kind="toggle"]:checked {{ background: {ACCENT}; color: #000000; border-color: {ACCENT}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {BG}; border: 2px solid {LINE}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {BG}; border: 2px solid {LINE}; selection-background-color: {BG}; selection-color: {ACCENT}; }}
QCheckBox::indicator {{ border: 2px solid {LINE}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QTreeView::item:selected, QListWidget::item:selected {{ background: {BG}; color: {ACCENT}; }}
QScrollBar:vertical {{ width: 12px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 0px; }}
QProgressBar {{ background: {BAR_BG}; height: 10px; }}
QProgressBar::chunk {{ background: {ACCENT}; }}
QStatusBar {{ border-top: 3px solid {LINE}; }}
QMenu {{ background: {BG}; border: 2px solid {LINE}; }}
QMenu::item:selected {{ background: {BG}; color: {ACCENT}; }}
QToolTip {{ background: {BG}; border: 2px solid {LINE}; }}
QDialog, QMessageBox {{ background: {BG}; }}
QTextBrowser {{ border: 2px solid {LINE}; }}
"""


_fonts_loaded = False


def apply(app: QApplication, preset: str | None = None, overrides: dict[str, str] | None = None,
          scale: float | None = None, text_font: str | None = None, title_font: str | None = None) -> None:
    """(Re)apply the theme. Safe to call again at runtime."""
    global SCALE, _fonts_loaded
    if not _fonts_loaded:
        load_fonts()
        app.setStyle("Fusion")
        _fonts_loaded = True
    if scale is not None:
        SCALE = scale
    set_theme(preset or PRESET, OVERRIDES if overrides is None else overrides, text_font, title_font)
    body = QFont(BODY_FAMILY)
    body.setPixelSize(fpx(13))
    if BODY_FAMILY in PIXEL_FAMILIES:
        body.setStyleStrategy(QFont.NoAntialias)   # crisp pixel edges
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
