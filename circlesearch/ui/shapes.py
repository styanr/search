import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen

STARS = {
    "cookie4": (4, 0.82, 0.8), "cookie6": (6, 0.84, 0.8), "cookie7": (7, 0.80, 0.8),
    "cookie9": (9, 0.86, 0.8), "cookie12": (12, 0.88, 0.8),
    "sunny": (8, 0.84, 1.6), "very_sunny": (8, 0.70, 1.8),
    "soft_burst": (10, 0.78, 1.2), "clover4": (4, 0.55, 0.45), "clover8": (8, 0.70, 0.55),
    "scallop": (16, 0.92, 0.9),
}


def star_path(rect, points, inner, sharp=1.0, rotation=-90.0, samples=None):
    cx, cy = rect.center().x(), rect.center().y()
    rx, ry = rect.width() / 2, rect.height() / 2
    n = samples or max(96, points * 24)
    path = QPainterPath()
    rot = math.radians(rotation)
    for i in range(n + 1):
        th = 2 * math.pi * i / n
        t = (1 + math.cos(points * (th - rot))) / 2
        t = t ** sharp
        r = inner + (1 - inner) * t
        pt = QPointF(cx + rx * r * math.cos(th), cy + ry * r * math.sin(th))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


def squircle_path(rect, n=4.0, samples=96):
    cx, cy, a, b = rect.center().x(), rect.center().y(), rect.width() / 2, rect.height() / 2
    path = QPainterPath()
    for i in range(samples + 1):
        th = 2 * math.pi * i / samples
        c, s = math.cos(th), math.sin(th)
        x = a * math.copysign(abs(c) ** (2 / n), c)
        y = b * math.copysign(abs(s) ** (2 / n), s)
        pt = QPointF(cx + x, cy + y)
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    path.closeSubpath()
    return path


def arch_path(rect, bottom_radius=16):
    r = rect.width() / 2
    path = QPainterPath()
    path.moveTo(rect.left(), rect.top() + r)
    path.arcTo(QRectF(rect.left(), rect.top(), 2 * r, 2 * r), 180, -180)
    path.lineTo(rect.right(), rect.bottom() - bottom_radius)
    path.quadTo(rect.right(), rect.bottom(), rect.right() - bottom_radius, rect.bottom())
    path.lineTo(rect.left() + bottom_radius, rect.bottom())
    path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - bottom_radius)
    path.closeSubpath()
    return path


def shape_path(name, rect):
    if name in STARS:
        return star_path(rect, *STARS[name])
    if name == "squircle":
        return squircle_path(rect)
    if name == "arch":
        return arch_path(rect)
    if name == "pill":
        p = QPainterPath(); p.addRoundedRect(rect, min(rect.width(), rect.height()) / 2, min(rect.width(), rect.height()) / 2); return p
    if name.startswith("round"):
        r = float(name[5:] or 16)
        p = QPainterPath(); p.addRoundedRect(rect, r, r); return p
    p = QPainterPath(); p.addEllipse(rect); return p


SUN, MOON, CLOUD, CLOUD_DARK, RAIN, SNOW, BOLT = (QColor("#FBBC05"), QColor("#D3E3FD"), QColor("#E3E6EE"),
                                                  QColor("#AEB4C2"), QColor("#7BAAF7"), QColor("#FFFFFF"), QColor("#FBBC05"))


def _cloud(r, scale=1.0):
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    w, h = r.width(), r.height()
    base = QRectF(r.left(), r.top() + h * 0.45, w, h * 0.55)
    path.addRoundedRect(base, base.height() / 2, base.height() / 2)
    for cx, cy, rad in ((0.30, 0.52, 0.26), (0.56, 0.36, 0.34), (0.78, 0.56, 0.22)):
        path.addEllipse(QPointF(r.left() + w * cx, r.top() + h * cy), w * rad, w * rad)
    return path.simplified()


def weather_kind(code):
    code = code or 0
    if code <= 1: return "clear"
    if code == 2: return "partly"
    if code == 3: return "cloudy"
    if code <= 48: return "fog"
    if code <= 67 or 80 <= code <= 82: return "rain"
    if code <= 77 or 85 <= code <= 86: return "snow"
    return "storm"


def draw_weather_icon(p, code, rect, day=True):
    kind = weather_kind(code)
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    w = rect.width()

    def sun(r):
        if day:
            p.setBrush(SUN)
            p.drawPath(star_path(r, *STARS["sunny"]))
        else:
            moon = QPainterPath(); moon.addEllipse(r.adjusted(w * .06, w * .06, -w * .06, -w * .06))
            bite = QPainterPath(); bite.addEllipse(r.translated(r.width() * .32, -r.height() * .22))
            p.setBrush(MOON); p.drawPath(moon.subtracted(bite))

    if kind == "clear":
        sun(rect.adjusted(w * .08, w * .08, -w * .08, -w * .08))
    elif kind == "partly":
        sun(QRectF(rect.left() + w * .34, rect.top() + w * .02, w * .62, w * .62))
        p.setBrush(CLOUD); p.drawPath(_cloud(QRectF(rect.left(), rect.top() + w * .36, w * .78, w * .5)))
    else:
        cloud = QRectF(rect.left() + w * .04, rect.top() + w * .12, w * .92, w * .58)
        if kind == "cloudy":
            p.setBrush(CLOUD_DARK); p.drawPath(_cloud(QRectF(rect.left() + w * .30, rect.top() + w * .04, w * .66, w * .42)))
            cloud = QRectF(rect.left() + w * .02, rect.top() + w * .26, w * .84, w * .54)
        p.setBrush(CLOUD); p.drawPath(_cloud(cloud))
        y = cloud.bottom() + w * .06
        if kind == "rain":
            p.setPen(QPen(RAIN, max(1.6, w * .07), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for x in (.28, .50, .72):
                p.drawLine(QPointF(rect.left() + w * x, y), QPointF(rect.left() + w * (x - .06), y + w * .16))
        elif kind == "snow":
            p.setBrush(SNOW)
            for x, dy in ((.28, 0), (.50, .08), (.72, 0)):
                p.drawEllipse(QPointF(rect.left() + w * x, y + w * (.06 + dy)), w * .05, w * .05)
        elif kind == "fog":
            p.setPen(QPen(CLOUD_DARK, max(1.6, w * .06), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for i, (a, b) in enumerate(((.12, .70), (.30, .92))):
                yy = y + w * (.02 + i * .1)
                p.drawLine(QPointF(rect.left() + w * a, yy), QPointF(rect.left() + w * b, yy))
        elif kind == "storm":
            bolt = QPainterPath(QPointF(rect.left() + w * .55, y - w * .04))
            for x, yy in ((.40, .14), (.52, .14), (.44, .30), (.64, .08), (.52, .08), (.60, -.04)):
                bolt.lineTo(QPointF(rect.left() + w * x, y + w * yy))
            bolt.closeSubpath()
            p.setBrush(BOLT); p.drawPath(bolt)
    p.restore()


def glyph(p, name, rect, color):
    p.save()
    p.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    if name == "people":
        p.drawEllipse(QPointF(x + w * .36, y + h * .32), w * .15, w * .15)
        p.drawArc(QRectF(x + w * .10, y + h * .55, w * .52, h * .5), 0, 180 * 16)
        p.drawEllipse(QPointF(x + w * .70, y + h * .38), w * .11, w * .11)
        p.drawArc(QRectF(x + w * .55, y + h * .60, w * .36, h * .36), 0, 180 * 16)
    elif name == "area":
        p.drawRoundedRect(QRectF(x + w * .14, y + h * .14, w * .72, h * .72), 3, 3)
        p.drawLine(QPointF(x + w * .14, y + h * .5), QPointF(x + w * .5, y + h * .5))
        p.drawLine(QPointF(x + w * .5, y + h * .14), QPointF(x + w * .5, y + h * .86))
    elif name == "mountain":
        path = QPainterPath(QPointF(x + w * .06, y + h * .84))
        path.lineTo(QPointF(x + w * .38, y + h * .26)); path.lineTo(QPointF(x + w * .58, y + h * .58))
        path.lineTo(QPointF(x + w * .70, y + h * .42)); path.lineTo(QPointF(x + w * .94, y + h * .84)); path.closeSubpath()
        p.drawPath(path)
    elif name == "calendar":
        p.drawRoundedRect(QRectF(x + w * .12, y + h * .20, w * .76, h * .68), 3, 3)
        p.drawLine(QPointF(x + w * .12, y + h * .42), QPointF(x + w * .88, y + h * .42))
        for xx in (.34, .66):
            p.drawLine(QPointF(x + w * xx, y + h * .1), QPointF(x + w * xx, y + h * .28))
    elif name == "star":
        p.drawPath(star_path(QRectF(x + w * .08, y + h * .08, w * .84, h * .84), 5, 0.45, 1.0))
    elif name == "coins":
        p.drawEllipse(QRectF(x + w * .12, y + h * .30, w * .56, h * .56))
        p.drawArc(QRectF(x + w * .34, y + h * .12, w * .56, h * .56), -30 * 16, 210 * 16)
    elif name == "chat":
        p.drawRoundedRect(QRectF(x + w * .10, y + h * .16, w * .80, h * .56), 6, 6)
        p.drawLine(QPointF(x + w * .30, y + h * .72), QPointF(x + w * .24, y + h * .90))
    elif name == "code":
        for s in (1, -1):
            cx = x + w * (.5 - s * .26)
            p.drawPolyline([QPointF(cx + s * w * .12, y + h * .26), QPointF(cx, y + h * .5), QPointF(cx + s * w * .12, y + h * .74)])
    elif name == "tag":
        p.drawRoundedRect(QRectF(x + w * .14, y + h * .14, w * .72, h * .72), 4, 4)
        p.drawEllipse(QPointF(x + w * .36, y + h * .36), w * .06, w * .06)
    elif name == "phone":
        p.drawRoundedRect(QRectF(x + w * .28, y + h * .08, w * .44, h * .84), 5, 5)
        p.drawLine(QPointF(x + w * .44, y + h * .80), QPointF(x + w * .56, y + h * .80))
    elif name == "capital":
        p.drawPath(star_path(QRectF(x + w * .08, y + h * .08, w * .84, h * .84), 5, 0.45, 1.0))
    elif name == "person":
        p.drawEllipse(QPointF(x + w * .5, y + h * .32), w * .18, w * .18)
        p.drawArc(QRectF(x + w * .18, y + h * .58, w * .64, h * .6), 0, 180 * 16)
    elif name in ("sunrise", "sunset"):
        p.drawArc(QRectF(x + w * .22, y + h * .52, w * .56, h * .56), 0, 180 * 16)
        p.drawLine(QPointF(x + w * .04, y + h * .8), QPointF(x + w * .96, y + h * .8))
        up = name == "sunrise"
        tip, tail = (y + h * .04, y + h * .38) if up else (y + h * .38, y + h * .04)
        p.drawLine(QPointF(x + w * .5, tail), QPointF(x + w * .5, tip))
        d = h * .12 if up else -h * .12
        p.drawPolyline([QPointF(x + w * .36, tip + d), QPointF(x + w * .5, tip), QPointF(x + w * .64, tip + d)])
    elif name == "clock":
        p.drawEllipse(QRectF(x + w * .1, y + h * .1, w * .8, h * .8))
        p.drawPolyline([QPointF(x + w * .5, y + h * .28), QPointF(x + w * .5, y + h * .5), QPointF(x + w * .66, y + h * .6)])
    p.restore()
