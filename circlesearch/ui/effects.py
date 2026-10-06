import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QConicalGradient, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from circlesearch.ui.motion import mix, with_alpha
from circlesearch.ui.theme import GOOGLE


def draw_spinner(p, center, t, color, radius=8, width=2.6):
    span = 30 + 230 * (0.5 - 0.5 * math.cos(t * 4.4))
    start = -(t * 320 + 0.5 * span) % 360
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
              int(start * 16), int(span * 16))


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


def google_gradient(center, angle, alpha=1.0):
    g = QConicalGradient(center, angle)
    for i, hue in enumerate(GOOGLE + GOOGLE[:1]):
        g.setColorAt(i / len(GOOGLE), with_alpha(hue, alpha))
    return g


def aurora_image(width, height, t, strength, anchor=0.95, seed=0.0, feather=False):
    w, h = max(8, int(width / 10)), max(6, int(height / 10))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    n = len(GOOGLE)
    for i, hue in enumerate(GOOGLE):
        k = i * 1.7 + seed
        cx = w * ((i + 0.5) / n + 0.07 * math.sin(t * 0.31 + k))
        cy = h * (anchor + 0.08 * math.sin(t * 0.47 + k * 1.3))
        rx = w * (0.32 + 0.06 * math.sin(t * 0.39 + k * 0.7))
        ry = h * (0.80 + 0.12 * math.sin(t * 0.57 + k * 2.1))
        g = QRadialGradient(QPointF(0, 0), 1.0)
        g.setColorAt(0.0, with_alpha(hue, 0.85 * strength))
        g.setColorAt(0.45, with_alpha(hue, 0.35 * strength))
        g.setColorAt(1.0, with_alpha(hue, 0.0))
        p.save()
        p.translate(cx, cy)
        p.scale(rx, ry)
        p.fillRect(QRectF(-1, -1, 2, 2), g)
        p.restore()
    if feather:
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        mask = QLinearGradient(0, 0, 0, h)
        for stop, a in ((0.0, 0), (0.3, 255), (0.7, 255), (1.0, 0)):
            mask.setColorAt(stop, QColor(0, 0, 0, a))
        p.fillRect(QRectF(0, 0, w, h), QBrush(mask))
    p.end()
    return img


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


class InkStroke:
    GLOW_SCALE = 8
    MIN_STEP = 4.0
    SMOOTHING = 0.25
    CORE_WIDTH, GLOW_WIDTH = 6, 20
    GLOW_SPREAD = 5
    TAPER = 60
    TIP_RADIUS = 22
    PAD = 36

    def __init__(self, size, dpr, start):
        self.core = QImage(size * dpr, QImage.Format.Format_ARGB32_Premultiplied)
        self.core.setDevicePixelRatio(dpr)
        self.core.fill(0)
        self.glow = QImage(size.width() // self.GLOW_SCALE + 2, size.height() // self.GLOW_SCALE + 2,
                           QImage.Format.Format_ARGB32_Premultiplied)
        self.glow.fill(0)
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
        p = QPainter(self.core)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.strokePath(path, core)
        if self._last_highlight is not None:
            p.strokePath(*self._last_highlight)
        p.strokePath(path, highlight)
        self._last_highlight = (path, highlight)
        p.end()
        p = QPainter(self.glow)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(1 / self.GLOW_SCALE, 1 / self.GLOW_SCALE)
        p.strokePath(path, QPen(color, self.GLOW_WIDTH * taper, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.end()

    def paint(self, p, clip, alpha=1.0, tip=True, fading=False):
        area = QRectF(clip).intersected(self.bounds)
        if alpha <= 0.01 or area.isEmpty():
            return
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        s, k = self.GLOW_SCALE, self.GLOW_SPREAD
        offsets = ((0, 0),) if fading else ((0, 0), (-k, -k), (k, -k), (-k, k), (k, k))
        p.setOpacity(min(1.0, (0.6 if fading else 0.22) * alpha))
        for dx, dy in offsets:
            src = area.translated(dx, dy)
            p.drawImage(area, self.glow, QRectF(src.x() / s, src.y() / s, src.width() / s, src.height() / s))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setOpacity(alpha)
        d = self.core.devicePixelRatio()
        p.drawImage(area, self.core, QRectF(area.x() * d, area.y() * d, area.width() * d, area.height() * d))
        color = hue_at(self.length)
        if self.cursor != self.mid:
            tail = QPainterPath(self.mid)
            tail.lineTo(self.cursor)
            for pen in self._pens(color, self._taper(self.length)):
                p.setPen(pen)
                p.drawPath(tail)
        if tip:
            g = QRadialGradient(self.cursor, self.TIP_RADIUS)
            g.setColorAt(0.0, with_alpha(mix(color, QColor("white"), 0.35), 0.5 * alpha))
            g.setColorAt(0.4, with_alpha(color, 0.22 * alpha))
            g.setColorAt(1.0, with_alpha(color, 0.0))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(self.cursor, self.TIP_RADIUS, self.TIP_RADIUS)
        p.restore()
