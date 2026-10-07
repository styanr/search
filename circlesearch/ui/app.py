import argparse
import os
import sys
import tempfile

from PyQt6.QtCore import QCoreApplication, QLockFile, QObject, QRect, Qt, QTimer
from PyQt6.QtGui import QCursor, QSurfaceFormat
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
  Ctrl+P              pin the selection to the screen
  type                search typed text; Down shows recent searches
  right-click         clear the selection
  Esc                 close

Short selections can show info cards (definitions, translations, places, money,
times, colours). Set CIRCLE_SEARCH_CARDS=0 to turn them off.
CIRCLE_SEARCH_DEBUG=1 saves each screenshot and OCR result to ~/.cache/circle-search/debug/.
"""


def layouts(image, screens, primary):
    virtual = QRect()
    for s in screens:
        virtual = virtual.united(s.geometry())
    fx, fy = image.width() / virtual.width(), image.height() / virtual.height()
    if len(screens) > 1 and abs(fx - fy) < 0.02 * fx:
        out = []
        for s in screens:
            g = s.geometry().translated(-virtual.topLeft())
            crop = image.copy(QRect(round(g.x() * fx), round(g.y() * fx), round(g.width() * fx), round(g.height() * fx)))
            out.append((s, crop, fx))
        return out
    return [(primary, image, None)]


class Session(QObject):
    def __init__(self, app, overlays, lock):
        super().__init__()
        self.app, self.overlays, self.lock = app, overlays, lock
        self.open = set(overlays)
        cursor = QCursor.pos()
        self.queue = sorted(overlays, key=lambda o: not o.geometry().contains(cursor))
        for o in overlays:
            o.finished.connect(self.finish)
            o.selecting.connect(self.focus)
            o.closed.connect(lambda o=o: self.closed(o))
            if len(overlays) > 1:
                o.ocr_gate = self.next_ocr
        from circlesearch.ui import pin
        pin.Pin.on_close = self.maybe_quit

    def start(self):
        if len(self.overlays) > 1:
            QTimer.singleShot(30, lambda: self.next_ocr(None))

    def next_ocr(self, done):
        if self.queue:
            o = self.queue.pop(0)
            QTimer.singleShot(0, o._start_ocr)

    def finish(self, source):
        for o in self.overlays:
            if o is not source and o.exit is None:
                o.dismiss()

    def focus(self, source):
        for o in self.overlays:
            if o is not source and (o.selection is not None or o.typed):
                o._clear_selection()

    def closed(self, overlay):
        self.open.discard(overlay)
        if not self.open:
            self.lock.unlock()
            self.maybe_quit()

    def maybe_quit(self):
        from circlesearch.ui import pin
        if not self.open and not pin.open_pins():
            self.app.quit()


def main():
    parser = argparse.ArgumentParser(description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instant", action="store_true", help="search immediately when you finish circling")
    args = parser.parse_args()

    lock = QLockFile(os.path.join(tempfile.gettempdir(), f"circle-search-{os.getuid()}.lock"))
    if not lock.tryLock(0):
        return 0

    capture = Capture()
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    surface = QSurfaceFormat.defaultFormat()
    surface.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    surface.setDepthBufferSize(0)
    surface.setStencilBufferSize(0)
    QSurfaceFormat.setDefaultFormat(surface)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("circle-search")
    app.setDesktopFileName("circle-search")
    locale.install(QtLocale.detect())

    from circlesearch.ui import backdrop
    error = backdrop.prepare()
    if error:
        print(error, file=sys.stderr)
        return 1
    from circlesearch.ui.overlay import Overlay
    from circlesearch.ui.theme import load_fonts
    load_fonts()
    image = capture.finish()
    if image is None:
        print("Could not take a screenshot (need kwin-grab, spectacle, grim or gnome-screenshot).", file=sys.stderr)
        return 1

    overlays = []
    for screen, shot, scale in layouts(image, app.screens(), app.primaryScreen()):
        overlay = Overlay(shot, screen, instant=args.instant, scale=scale)
        overlay.place(screen)
        overlays.append(overlay)
    session = Session(app, overlays, lock)
    cursor = QCursor.pos()
    for overlay in sorted(overlays, key=lambda o: o.geometry().contains(cursor)):
        overlay.present()
    next((o for o in overlays if o.geometry().contains(cursor)), overlays[0]).activateWindow()
    session.start()
    code = app.exec()
    lock.unlock()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
