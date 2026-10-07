import math

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

from circlesearch.ui.motion import mix, with_alpha
from circlesearch.ui.shapes import STARS
from circlesearch.ui.theme import GOOGLE


LOADER_SEQ = ["cookie9", "soft_burst", "cookie4", "clover4", "sunny"]


def loader_path(t, rect, settle=0.0):
    seq = LOADER_SEQ
    i = int(t / 0.65) % len(seq)
    a, b = STARS[seq[i]], STARS[seq[(i + 1) % len(seq)]]
    k = min(1.0, (t / 0.65) % 1.0 / 0.6)
    k = 1 - (1 - k) ** 3
    cookie = STARS["cookie9"]
    spin = t * 2.2
    step = 2 * math.pi / cookie[0]
    spin += (round(spin / step) * step - spin) * settle
    cx, cy = rect.center().x(), rect.center().y()
    R = rect.width() / 2 * (26 / 28 + (1 - 26 / 28) * settle)

    def radius(shape, th):
        n, inner, sharp = shape
        return inner + (1 - inner) * ((1 + math.cos(n * (th - spin + math.pi / 2))) / 2) ** sharp

    path = QPainterPath()
    for j in range(181):
        th = 2 * math.pi * j / 180
        moving = radius(a, th) * (1 - k) + radius(b, th) * k
        r = R * (moving * (1 - settle) + radius(cookie, th) * settle)
        pt = QPointF(cx + r * math.cos(th), cy + r * math.sin(th))
        path.moveTo(pt) if j == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


def draw_loader(p, center, t, color, radius=8):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawPath(loader_path(t, QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)))
    p.restore()


def draw_glyph(p, center, radius=8, width=2.8, alpha=1.0):
    box = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
    for i, hue in enumerate(GOOGLE):
        p.setPen(QPen(with_alpha(hue, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(box, int((90 - i * 90 - 14) * 16), int(-62 * 16))


def draw_check(p, center, progress, color, size=7.0):
    a = QPointF(center.x() - size * 0.75, center.y())
    b = QPointF(center.x() - size * 0.2, center.y() + size * 0.55)
    c = QPointF(center.x() + size * 0.85, center.y() - size * 0.6)
    first = math.hypot(b.x() - a.x(), b.y() - a.y())
    second = math.hypot(c.x() - b.x(), c.y() - b.y())
    done = progress * (first + second)
    path = QPainterPath(a)
    if done <= first:
        path.lineTo(a + (b - a) * (done / first))
    else:
        path.lineTo(b)
        path.lineTo(b + (c - b) * ((done - first) / second))
    p.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def lightness_at(image, points):
    d = image.devicePixelRatio()
    w, h = image.width() - 1, image.height() - 1
    vals = sorted(QColor(image.pixel(int(min(max(x * d, 0), w)), int(min(max(y * d, 0), h)))).lightnessF()
                  for x, y in points)
    return vals[len(vals) // 2] if vals else 0.0


def hue_at(distance):
    x = (distance / 220.0) % len(GOOGLE)
    i = int(x)
    return mix(GOOGLE[i], GOOGLE[(i + 1) % len(GOOGLE)], x - i)


def gaussian(sigma):
    reach = math.ceil(3 * sigma)
    weights = [math.exp(-x * x / (2 * sigma * sigma)) for x in range(-reach, reach + 1)]
    total = sum(weights)
    return reach, [w / total for w in weights]


def blur_region(sharp, out, dirty, kernel):
    reach, weights = kernel
    bounds = sharp.rect()
    inner = dirty.adjusted(-reach, -reach, reach, reach).intersected(bounds)
    outer = inner.adjusted(-reach, -reach, reach, reach).intersected(bounds)
    if inner.isEmpty():
        return
    fmt = QImage.Format.Format_RGBA64_Premultiplied
    src = sharp.copy(outer).convertToFormat(fmt)
    rows = QImage(inner.width(), outer.height(), fmt)
    rows.fill(0)
    p = QPainter(rows)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    for i, w in enumerate(weights):
        p.setOpacity(w)
        p.drawImage(QPoint(outer.left() - inner.left() - (i - reach), 0), src)
    p.end()
    done = QImage(inner.width(), inner.height(), fmt)
    done.fill(0)
    p = QPainter(done)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    for i, w in enumerate(weights):
        p.setOpacity(w)
        p.drawImage(QPoint(0, outer.top() - inner.top() - (i - reach)), rows)
    p.end()
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.drawImage(inner.topLeft(), done)
    p.end()


class InkStroke:
    GLOW_SCALE = 2
    GLOW_WIDTH = 26
    GLOW_SIGMA = 3.0
    GLOW_STRENGTH = 1.0
    MIN_STEP = 4.0
    SMOOTHING = 0.25
    CORE_WIDTH = 6
    TAPER = 60
    TIP_RADIUS = 22
    PAD = 36

    def __init__(self, size, dpr, start):
        self.core = QImage(size * dpr, QImage.Format.Format_ARGB32_Premultiplied)
        self.core.setDevicePixelRatio(dpr)
        self.core.fill(0)
        glow_size = QSize(size.width() // self.GLOW_SCALE + 1, size.height() // self.GLOW_SCALE + 1)
        self.glow = QImage(glow_size, QImage.Format.Format_ARGB32_Premultiplied)
        self.glow.fill(0)
        self.halo = QImage(glow_size, QImage.Format.Format_ARGB32_Premultiplied)
        self.halo.fill(0)
        self._kernel = gaussian(self.GLOW_SIGMA)
        self._dirty = QRect()
        self._halo_dirty = QRect()
        self._core_dirty = QRect()
        self._transient = []
        self.points = [start]
        self._extent = [start.x(), start.y(), start.x(), start.y()]
        self.mid = start
        self.cursor = start
        self.length = 0.0
        self._last_highlight = None
        self.bounds = QRectF(start, start).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)

    @property
    def raw(self):
        x0, y0, x1, y1 = self._extent
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def _tail_rect(self):
        return QRectF(self.mid, self.cursor).normalized().adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)

    def add(self, pos):
        dirty = self._tail_rect()
        self.cursor = pos
        e = self._extent
        e[:] = min(e[0], pos.x()), min(e[1], pos.y()), max(e[2], pos.x()), max(e[3], pos.y())
        last = self.points[-1]
        smoothed = last + (pos - last) * self.SMOOTHING
        if (smoothed - last).manhattanLength() >= self.MIN_STEP:
            self.points.append(smoothed)
            new_mid = (last + smoothed) / 2
            path = QPainterPath(self.mid)
            path.quadTo(last, new_mid)
            self._commit(path)
            dirty = dirty.united(path.boundingRect().adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD))
            self.mid = new_mid
        dirty = dirty.united(self._tail_rect())
        self.bounds = self.bounds.united(dirty)
        return dirty

    def finish(self):
        path = QPainterPath(self.mid)
        path.lineTo(self.cursor if self.cursor != self.mid else self.mid + QPointF(0.1, 0))
        self._commit(path)
        self.mid = self.cursor
        return self.bounds

    def _taper(self, distance):
        return min(1.0, 0.45 + 0.55 * distance / self.TAPER)

    def _pens(self, color, taper=1.0):
        cap, join = Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
        return (QPen(color, self.CORE_WIDTH * taper, Qt.PenStyle.SolidLine, cap, join),
                QPen(mix(color, QColor("white"), 0.8), 2 * taper, Qt.PenStyle.SolidLine, cap, join))

    def _commit(self, path):
        seg = path.length()
        color = hue_at(self.length + seg / 2)
        taper = self._taper(self.length + seg / 2)
        self.length += seg
        core, highlight = self._pens(color, taper)
        self._core_dirty = self._core_dirty.united(self._device_rect(path))
        p = QPainter(self.core)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.strokePath(path, core)
        if self._last_highlight is not None:
            p.strokePath(*self._last_highlight)
        p.strokePath(path, highlight)
        self._last_highlight = (path, highlight)
        p.end()
        s = self.GLOW_SCALE
        p = QPainter(self.glow)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(1 / s, 1 / s)
        p.strokePath(path, QPen(color, self.GLOW_WIDTH * taper, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.end()
        r = path.boundingRect().adjusted(-self.GLOW_WIDTH, -self.GLOW_WIDTH, self.GLOW_WIDTH, self.GLOW_WIDTH)
        self._dirty = self._dirty.united(QRect(math.floor(r.left() / s), math.floor(r.top() / s),
                                               math.ceil(r.width() / s) + 2, math.ceil(r.height() / s) + 2))

    def _device_rect(self, path):
        d = self.core.devicePixelRatio()
        r = path.boundingRect()
        if self._last_highlight is not None:
            r = r.united(self._last_highlight[0].boundingRect())
        r = r.adjusted(-self.CORE_WIDTH - 2, -self.CORE_WIDTH - 2, self.CORE_WIDTH + 2, self.CORE_WIDTH + 2)
        return QRect(math.floor(r.left() * d), math.floor(r.top() * d), math.ceil(r.width() * d) + 2,
                     math.ceil(r.height() * d) + 2).intersected(self.core.rect())

    def _halo(self):
        if not self._dirty.isEmpty():
            reach = self._kernel[0]
            self._halo_dirty = self._halo_dirty.united(self._dirty.adjusted(-reach, -reach, reach, reach))
            blur_region(self.glow, self.halo, self._dirty, self._kernel)
            self._dirty = QRect()
        return self.halo

    def _tail(self):
        if self.cursor == self.mid:
            return None
        path = QPainterPath(self.mid)
        path.lineTo(self.cursor)
        at = self.length + path.length() / 2
        return path, hue_at(at), self._taper(at)

    def _tail_halo(self, path, color, taper):
        s, reach = self.GLOW_SCALE, self._kernel[0]
        r = path.boundingRect().adjusted(-self.GLOW_WIDTH, -self.GLOW_WIDTH, self.GLOW_WIDTH, self.GLOW_WIDTH)
        band = QRect(math.floor(r.left() / s), math.floor(r.top() / s), math.ceil(r.width() / s) + 2,
                     math.ceil(r.height() / s) + 2)
        region = band.adjusted(-2 * reach, -2 * reach, 2 * reach, 2 * reach).intersected(self.glow.rect())
        sharp = self.glow.copy(region)
        q = QPainter(sharp)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.scale(1 / s, 1 / s)
        q.translate(-region.left() * s, -region.top() * s)
        q.strokePath(path, QPen(color, self.GLOW_WIDTH * taper, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        q.end()
        patch = self._halo().copy(region)
        blur_region(sharp, patch, band.translated(-region.topLeft()), self._kernel)
        return region, patch

    def tip_color(self):
        tail = self._tail()
        return tail[1] if tail is not None else hue_at(self.length)

    def uploads(self):
        halo = self._halo()
        dirty = {"halo": self._halo_dirty, "core": self._core_dirty}
        for layer, rect in self._transient:
            dirty[layer] = dirty[layer].united(rect)
        self._halo_dirty, self._core_dirty, self._transient = QRect(), QRect(), []
        out = []
        for layer, image in (("halo", halo), ("core", self.core)):
            rect = dirty[layer].intersected(image.rect())
            if not rect.isEmpty():
                out.append((layer, rect.x(), rect.y(), image.copy(rect)))
        tail = self._tail()
        if tail is None:
            return out
        region, patch = self._tail_halo(*tail)
        out.append(("halo", region.x(), region.y(), patch))
        self._transient.append(("halo", region))
        path, color, taper = tail
        rect = self._device_rect(path)
        if rect.isEmpty():
            return out
        patch = self.core.copy(rect)
        d = self.core.devicePixelRatio()
        core, highlight = self._pens(color, taper)
        p = QPainter(patch)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-rect.x() / d, -rect.y() / d)
        p.strokePath(path, core)
        if self._last_highlight is not None:
            p.strokePath(*self._last_highlight)
        p.strokePath(path, highlight)
        p.end()
        out.append(("core", rect.x(), rect.y(), patch))
        self._transient.append(("core", rect))
        return out
