import os

from PyQt6.QtGui import QColor, QFont, QFontDatabase

from circlesearch.ui import tokens as T

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "fonts")
FONT_FILES = [os.path.join(FONT_DIR, "GoogleSansFlex.ttf"), os.path.join(FONT_DIR, "GoogleSans.ttf")]
FONT_FAMILIES = ["Google Sans Flex", "Google Sans"]


def C(h, a=255):
    return QColor(*T.hx(h), a)


SURFACE = C(T.SURFACE)
SURFACE_HIGH = C(T.SURFACE_HIGH)
ON_SURFACE = C(T.ON_SURFACE)
ON_SURFACE_VARIANT = C(T.ON_VAR)
PRIMARY = C(T.PRIMARY)
ON_PRIMARY = C(T.ON_PRIMARY)
SCRIM = C(T.SCRIM)
GOOGLE = [C(h) for h in T.GOOGLE]
HIGHLIGHT_LIGHT = C(T.HIGHLIGHT_LIGHT)
HIGHLIGHT_DARK = C(T.HIGHLIGHT_DARK)
PALETTE = dict(surface=SURFACE, surface_high=SURFACE_HIGH, on_surface=ON_SURFACE,
               on_surface_variant=ON_SURFACE_VARIANT, primary=PRIMARY, on_primary=ON_PRIMARY)


def load_fonts():
    for path in FONT_FILES:
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)


def font(px, weight=450, rond=100, wdth=100, opsz=None):
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(round(px))
    f.setWeight(QFont.Weight(min(900, max(100, round(weight / 100) * 100))))
    f.setVariableAxis(QFont.Tag.fromString("wght"), weight)
    f.setVariableAxis(QFont.Tag.fromString("ROND"), rond)
    f.setVariableAxis(QFont.Tag.fromString("wdth"), wdth)
    f.setVariableAxis(QFont.Tag.fromString("opsz"), opsz or min(144, max(6, px)))
    return f


def type_font(style, weight=None, wdth=100):
    px, default = T.TYPE[style]
    return font(px, weight or default, wdth=wdth)
