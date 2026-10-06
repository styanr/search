import os
import tempfile
import threading

from PyQt6.QtCore import QObject, QRect, QRectF, Qt, pyqtSignal

from circlesearch.core import ocr
from circlesearch.core.geometry import Point, Rect

OCR_SCALE = 2
OCR_MARGIN = 28


def to_rect(r):
    return Rect(r.x(), r.y(), r.width(), r.height())


def to_qrect(r):
    return QRectF(r.x, r.y, r.w, r.h)


def to_point(p):
    return Point(p.x(), p.y())


class TextReader(QObject):
    screen_read = pyqtSignal(list)
    region_read = pyqtSignal(int, object, list)

    def __init__(self, shot, dpr, debug_dir=None, parent=None):
        super().__init__(parent)
        self.shot, self.dpr, self.debug_dir = shot, dpr, debug_dir
        self._pass_id = 0
        self._token = 0

    @staticmethod
    def available():
        return ocr.available()

    def _next_pass(self):
        self._pass_id += 1
        return self._pass_id

    def _read(self, image, scale, offset, pass_id, background=False):
        big = image.scaled(image.size() * OCR_SCALE, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        fd, path = tempfile.mkstemp(suffix=".bmp", dir="/dev/shm" if os.path.isdir("/dev/shm") else None)
        os.close(fd)
        try:
            words = ocr.read(path, scale, offset, pass_id, background, self.debug_dir) if big.save(path, "BMP") else []
        finally:
            os.unlink(path)
        if self.debug_dir:
            image.save(os.path.join(self.debug_dir, f"ocr-{pass_id:02d}.png"))
        return words

    def read_screen(self):
        shot, pass_id = self.shot.copy(), self._next_pass()

        def work():
            if self.debug_dir:
                shot.save(os.path.join(self.debug_dir, "screenshot.png"))
            self.screen_read.emit(self._read(shot, OCR_SCALE * self.dpr, Point(0, 0), pass_id, background=True))

        threading.Thread(target=work, daemon=True).start()

    def read_region(self, area, bounds):
        self._token += 1
        token, pass_id = self._token, self._next_pass()
        crop = area.adjusted(-OCR_MARGIN, -OCR_MARGIN, OCR_MARGIN, OCR_MARGIN).intersected(bounds)
        inner = to_rect(area.intersected(bounds))
        d = self.dpr
        image = self.shot.copy(QRect(round(crop.x() * d), round(crop.y() * d),
                                     round(crop.width() * d), round(crop.height() * d)))
        image.setDevicePixelRatio(1.0)
        offset = to_point(crop.topLeft())

        def work():
            words = self._read(image, OCR_SCALE * d, offset, pass_id)
            self.region_read.emit(token, inner, [w for w in words if inner.contains(w.rect.center())])

        threading.Thread(target=work, daemon=True).start()
        return token
