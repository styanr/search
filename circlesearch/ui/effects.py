import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen

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


class InkStroke:
    GLOW_WIDTH = 32
    GLOW_SIGMA = 3.0
    GLOW_STRENGTH = 0.5
    MIN_STEP = 4.0
    SMOOTHING = 0.25
    CORE_WIDTH = 6
    HIGHLIGHT_WIDTH = 2
    TIP_RADIUS = 22
    TIP_STRENGTH = 0.6
    PAD = 48
    STEP = 6.0

    def __init__(self, start):
        self.points = [start]
        self.line = [(start.x(), start.y(), 0.0)]
        self._extent = [start.x(), start.y(), start.x(), start.y()]
        self.mid = start
        self.cursor = start
        self.length = 0.0
        self.bounds = QRectF(start, start).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)

    @property
    def raw(self):
        x0, y0, x1, y1 = self._extent
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def add(self, pos):
        self.cursor = pos
        e = self._extent
        e[:] = min(e[0], pos.x()), min(e[1], pos.y()), max(e[2], pos.x()), max(e[3], pos.y())
        last = self.points[-1]
        smoothed = last + (pos - last) * self.SMOOTHING
        if (smoothed - last).manhattanLength() >= self.MIN_STEP:
            self.points.append(smoothed)
            new_mid = (last + smoothed) / 2
            self._curve(self.mid, last, new_mid)
            self.mid = new_mid
        self.bounds = self.bounds.united(QRectF(pos, pos).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD))
        return self.bounds

    def _curve(self, a, c, b):
        chord = math.hypot(b.x() - a.x(), b.y() - a.y())
        n = max(1, math.ceil(chord / self.STEP))
        x0, y0, _ = self.line[-1]
        for i in range(1, n + 1):
            t = i / n
            u = 1 - t
            x = u * u * a.x() + 2 * u * t * c.x() + t * t * b.x()
            y = u * u * a.y() + 2 * u * t * c.y() + t * t * b.y()
            self.length += math.hypot(x - x0, y - y0)
            self.line.append((x, y, self.length))
            x0, y0 = x, y

    def finish(self):
        if self.cursor != self.mid:
            x0, y0, _ = self.line[-1]
            self.length += math.hypot(self.cursor.x() - x0, self.cursor.y() - y0)
            self.line.append((self.cursor.x(), self.cursor.y(), self.length))
            self.mid = self.cursor
        return self.bounds

    def tail(self):
        x0, y0, s = self.line[-1]
        x, y = self.cursor.x(), self.cursor.y()
        if (x, y) == (x0, y0):
            return None
        return x, y, s + math.hypot(x - x0, y - y0)

    def tip_color(self, flow=0.0):
        tail = self.tail()
        return hue_at((tail[2] if tail is not None else self.length) - flow)
