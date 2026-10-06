import argparse
import os
import sys
import tempfile

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication

from circlesearch.core import locale
from circlesearch.ui.capture import Capture
from circlesearch.ui.qtlocale import QtLocale

HELP = """Circle to Search for the desktop.

Freezes the screen, lets you circle (or tap) anything, then searches the
selected text on Google or the selected pixels on Google Lens.

  circle / scribble   select a region
  tap                 select the word under the cursor
  Enter               run the suggested search
  Ctrl+Enter          force an image (Lens) search
  Ctrl+C              copy the recognised text
  right-click         clear the selection
  Esc                 close

Short selections can show info cards (definitions, translations, places, money,
times, colours). Set CIRCLE_SEARCH_CARDS=0 to turn them off.
CIRCLE_SEARCH_DEBUG=1 saves each screenshot and OCR result to ~/.cache/circle-search/debug/.
"""


def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instant", action="store_true", help="search immediately when you finish circling")
    args = parser.parse_args()

    lock = QLockFile(os.path.join(tempfile.gettempdir(), f"circle-search-{os.getuid()}.lock"))
    if not lock.tryLock(0):
        return 0

    capture = Capture()
    app = QApplication(sys.argv)
    app.setApplicationName("circle-search")
    app.setDesktopFileName("circle-search")
    locale.install(QtLocale.detect())

    from circlesearch.ui.overlay import Overlay
    from circlesearch.ui.theme import load_fonts
    load_fonts()
    image = capture.finish()
    if image is None:
        print("Could not take a screenshot (need kwin-grab, spectacle, grim or gnome-screenshot).", file=sys.stderr)
        return 1

    overlay = Overlay(image, app.primaryScreen(), instant=args.instant)
    overlay.showFullScreen()
    overlay.activateWindow()
    code = app.exec()
    lock.unlock()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
