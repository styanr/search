import math
import os
import tempfile
import threading

from PyQt6.QtCore import QObject, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QImage

from circlesearch.core import barcode, ocr, palette
from circlesearch.core.geometry import Point, Rect

OCR_SCALE = 2
OCR_MARGIN = 28
SCAN_SIDE = 320


def to_rect(r):
    return Rect(r.x(), r.y(), r.width(), r.height())


def to_qrect(r):
    return QRectF(r.x, r.y, r.w, r.h)


def to_point(p):
    return Point(p.x(), p.y())


class TextReader(QObject):
    screen_read = pyqtSignal(list)
    region_read = pyqtSignal(int, object, list)
    image_read = pyqtSignal(int, list, list)

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

    def _read(self, image, offset, pass_id, background=False):
        factor = max(1, round(OCR_SCALE / self.dpr))
        big = image if factor == 1 else image.scaled(image.size() * factor, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation)
        scale = factor * self.dpr
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
            self.screen_read.emit(self._read(shot, Point(0, 0), pass_id, background=True))

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
            words = self._read(image, offset, pass_id)
            self.region_read.emit(token, inner, [w for w in words if inner.contains(w.rect.center())])

        threading.Thread(target=work, daemon=True).start()
        return token

    def crop(self, area, bounds):
        r = area.intersected(bounds)
        d = self.dpr
        image = self.shot.copy(QRect(round(r.x() * d), round(r.y() * d), round(r.width() * d), round(r.height() * d)))
        image.setDevicePixelRatio(1.0)
        return image

    def scan(self, area, bounds):
        self._token += 1
        token = self._token
        image = self.crop(area, bounds)

        def work():
            codes = []
            if barcode.available() and not image.isNull():
                side = min(image.width(), image.height())
                k = min(4, math.ceil(SCAN_SIDE / side)) if 0 < side < SCAN_SIDE else 1
                big = image.scaled(image.size() * k, Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.FastTransformation) if k > 1 else image
                fd, path = tempfile.mkstemp(suffix=".png", dir="/dev/shm" if os.path.isdir("/dev/shm") else None)
                os.close(fd)
                try:
                    codes = barcode.scan(path) if big.save(path, "PNG") else []
                finally:
                    os.unlink(path)
            thumb = image.scaled(48, 48, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.FastTransformation).convertToFormat(QImage.Format.Format_RGB32)
            pixels = [((c >> 16) & 255, (c >> 8) & 255, c & 255)
                      for c in (thumb.pixel(x, y) for y in range(thumb.height()) for x in range(thumb.width()))]
            self.image_read.emit(token, codes, palette.dominant(pixels))

        threading.Thread(target=work, daemon=True).start()
        return token
