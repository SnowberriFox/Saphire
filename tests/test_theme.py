"""1.9.1: fonts are a setting; each theme suggests its own (Ham's request)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a
    from sapphire.ui import theme
    theme.apply(a, "Sapphire", {}, 1.0, "", "")


def test_every_bundled_font_registers_under_its_name(app):
    from PySide6.QtGui import QFontDatabase

    from sapphire.ui import theme
    theme.apply(app)
    families = set(QFontDatabase.families())
    missing = [f for f in theme.BUNDLED_FONTS if f not in families]
    assert missing == []
    for files in theme.BUNDLED_FONTS.values():
        for name in files:
            assert (theme.ASSETS / name).is_file(), name
    # and each has its licence alongside
    assert len(list(theme.ASSETS.glob("OFL-*.txt"))) == len(theme.BUNDLED_FONTS)


def test_undertale_suggests_readable_fonts_and_uses_one_by_default(app):
    from sapphire.ui import theme
    rec = theme.recommended("text", "Undertale")
    assert rec[0] == "Chakra Petch"
    assert set(rec) == {"Chakra Petch", "Pixelify Sans", "Atkinson Hyperlegible Mono", "Share Tech Mono",
                        "Space Mono", "VT323"}
    theme.apply(app, "Undertale", {}, 1.0, "", "")
    assert theme.PIXEL and theme.BODY_FAMILY == "Chakra Petch" and theme.DISPLAY_FAMILY == "Press Start 2P"
    assert app.font().family() == "Chakra Petch"


def test_picked_fonts_win_and_size_follows_the_font(app):
    from PySide6.QtGui import QFont

    from sapphire.ui import theme
    theme.apply(app, "Undertale", {}, 1.0, "VT323", "Pixelify Sans")
    assert theme.BODY_FAMILY == "VT323" and theme.DISPLAY_FAMILY == "Pixelify Sans"
    assert theme.FONT_BOOST == pytest.approx(1.4)              # VT323 reads small
    assert app.font().styleStrategy() & QFont.NoAntialias     # pixel font: crisp
    assert "font-size: 18px" in app.styleSheet()              # 13px text, scaled for VT323
    # a smooth font in a pixel theme keeps its anti-aliasing
    theme.apply(app, "Undertale", {}, 1.0, "Space Mono", "")
    assert not app.font().styleStrategy() & QFont.NoAntialias
    # choices stick across theme changes; "" goes back to the theme's own
    theme.apply(app, "Sapphire", {})
    assert theme.BODY_FAMILY == "Space Mono" and theme.DISPLAY_FAMILY == "Josefin Sans"
    theme.apply(app, "Sapphire", {}, 1.0, "", "")
    assert theme.BODY_FAMILY == "Inter"


def test_custom_colours_survive_a_plain_reapply(app):
    from sapphire.ui import theme
    theme.apply(app, "Sapphire", {"accent": "#FF00AA"})
    theme.apply(app)
    assert theme.ACCENT.lower() == "#ff00aa"
    theme.apply(app, "Sapphire", {})
