"""Colours, fonts and the Qt stylesheet."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).resolve().parent.parent / "assets"

BG = "#141A23"        # night-sky slate
PANEL = "#1B2330"
RAISED = "#252F3F"
LINE = "#344158"
ACCENT = "#5F97F0"    # sapphire
ACCENT_HI = "#86B3FF"
ACCENT_LO = "#2F5CAE"
TEXT = "#E9E0CA"      # parchment (warm against the cool slate)
MUTED = "#92A0B4"
OXBLOOD = "#B65A4E"
VERDIGRIS = "#6FAE8F"

DISPLAY_FAMILY = "Josefin Sans"
BODY_FAMILY = "Inter"


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


def display_font(size: int) -> QFont:
    f = QFont(DISPLAY_FAMILY)
    f.setPixelSize(size)
    f.setWeight(QFont.DemiBold)
    return f


STYLESHEET = f"""
* {{ outline: none; }}
QWidget {{ background: {BG}; color: {TEXT}; font-family: "{BODY_FAMILY}"; font-size: 13px; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px 6px; }}

#Header {{ background: {PANEL}; border-bottom: 1px solid {LINE}; }}
#Wordmark {{ background: transparent; color: {ACCENT}; font-family: "{DISPLAY_FAMILY}"; font-size: 24px; font-weight: 600; padding-top: 4px; }}
#NavButton {{ background: transparent; color: {MUTED}; border: none; padding: 8px 12px;
              font-size: 14px; border-bottom: 2px solid transparent; }}
#NavButton:hover {{ color: {TEXT}; }}
#NavButton:checked {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}

#LaunchButton {{ background: {ACCENT}; color: #0B1426; border: none; border-radius: 6px;
                 padding: 9px 20px; font-size: 14px; font-weight: 600; }}
#LaunchButton:hover {{ background: {ACCENT_HI}; }}
#LaunchButton:pressed {{ background: {ACCENT_LO}; }}
#LaunchButton:disabled {{ background: {RAISED}; color: {MUTED}; }}

#StatusPill {{ background: transparent; color: {MUTED}; padding: 4px 10px; border: 1px solid {LINE};
               border-radius: 11px; font-size: 12px; }}
#StatusPill[state="ok"] {{ color: {VERDIGRIS}; border-color: #3B5A52; }}
#StatusPill[state="warn"] {{ color: {ACCENT_HI}; border-color: {ACCENT_LO}; }}
#StatusPill[state="bad"] {{ color: #E08A7E; border-color: {OXBLOOD}; }}

#PageTitle {{ background: transparent; font-family: "{DISPLAY_FAMILY}"; font-size: 22px; font-weight: 600; color: {TEXT}; padding-top: 3px; }}
#SideTitle {{ background: transparent; color: {MUTED}; font-size: 12px; font-weight: 600; padding-top: 6px; }}
#Muted {{ background: transparent; color: {MUTED}; }}
#Panel, #FilterPanel, #DetailPanel {{ background: {PANEL}; }}
#DetailTitle {{ background: transparent; font-family: "{DISPLAY_FAMILY}"; font-size: 20px; font-weight: 600; color: {TEXT}; padding-top: 3px; }}
#Banner {{ background: #1E2A44; color: {ACCENT_HI}; border: 1px solid {ACCENT_LO}; border-radius: 6px; padding: 8px 12px; }}
#BannerBad {{ background: #3A2228; color: #E8A598; border: 1px solid {OXBLOOD}; border-radius: 6px; padding: 8px 12px; }}

QLineEdit, QComboBox, QSpinBox {{ background: {RAISED}; border: 1px solid {LINE}; border-radius: 5px;
                       padding: 6px 8px; selection-background-color: {ACCENT_LO}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {RAISED}; border: 1px solid {LINE}; selection-background-color: {ACCENT_LO}; }}

QPushButton {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; border-radius: 5px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT_LO}; }}
QPushButton:pressed {{ background: {LINE}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #65718A; border-color: #2C3648; }}
QPushButton[kind="primary"] {{ background: {ACCENT}; color: #0B1426; border: none; font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {ACCENT_HI}; }}
QPushButton[kind="primary"]:disabled {{ background: {RAISED}; color: {MUTED}; }}
QPushButton[kind="danger"] {{ color: #E8A598; }}
QPushButton[kind="danger"]:hover {{ border-color: {OXBLOOD}; }}

QCheckBox {{ background: transparent; spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {LINE}; background: {RAISED}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url(@CHECK@); }}
QCheckBox::indicator:focus {{ border-color: {ACCENT}; }}

QListView, QTreeWidget, QListWidget, QTextBrowser {{ background: {BG}; border: none; }}
QTreeWidget#CategoryTree {{ background: {PANEL}; }}
QTreeView::item {{ padding: 4px 2px; }}
QTreeView::item:selected, QListWidget::item:selected {{ background: {RAISED}; color: {ACCENT_HI}; }}
QTreeView::item:hover {{ background: #222B3A; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #46546E; }}
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


def apply(app: QApplication) -> None:
    global DISPLAY_FAMILY, BODY_FAMILY
    DISPLAY_FAMILY, BODY_FAMILY = load_fonts()
    app.setStyle("Fusion")
    body = QFont(BODY_FAMILY)
    body.setPixelSize(13)
    app.setFont(body)
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.Base, RAISED), (QPalette.AlternateBase, PANEL),
        (QPalette.Text, TEXT), (QPalette.WindowText, TEXT), (QPalette.Button, RAISED),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT_LO), (QPalette.HighlightedText, TEXT),
        (QPalette.ToolTipBase, RAISED), (QPalette.ToolTipText, TEXT), (QPalette.Link, ACCENT_HI),
        (QPalette.PlaceholderText, "#6B788E"),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    sheet = STYLESHEET.replace('"Josefin Sans"', f'"{DISPLAY_FAMILY}"').replace('"Inter"', f'"{BODY_FAMILY}"')
    sheet = sheet.replace("@CHECK@", (ASSETS / "check.svg").as_posix())
    app.setStyleSheet(sheet)
