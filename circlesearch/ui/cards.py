import importlib
import math
import time
from functools import cache

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from circlesearch.core import plugins
from circlesearch.core.registry import Registry
from circlesearch.ui import tokens as T
from circlesearch.ui.motion import SpringCurve, ramp
from circlesearch.ui.shapes import STARS, glyph, shape_path
from circlesearch.ui.theme import C, card_font

TRANSITION = 0.55
TRANSITION_SPRING = SpringCurve(duration=TRANSITION)

views = Registry("card view")


def view(card_class):
    def register(view_class):
        views.add(card_class, view_class)
        return view_class
    return register


@cache
def load_views():
    importlib.import_module("circlesearch.ui.views")
    plugins.load("view")


def view_for(card):
    load_views()
    for cls in type(card).__mro__:
        found = views.get(cls)
        if found is not None:
            return found
    raise LookupError(f"no view for {type(card).__name__}")


def decode(data):
    if not data:
        return None
    img = QImage()
    img.loadFromData(data)
    return None if img.isNull() else img


def wrap(fm, text, width, max_lines):
    if max_lines <= 1:
        return [fm.elidedText(" ".join(text.split()), Qt.TextElideMode.ElideRight, int(width))]
    words, lines, line = text.split(), [], ""
    for i, w in enumerate(words):
        trial = f"{line} {w}".strip()
        if fm.horizontalAdvance(trial) <= width or not line:
            line = trial
            continue
        lines.append(line)
        line = w
        if len(lines) == max_lines - 1:
            line = " ".join(words[i:])
            break
    if line:
        lines.append(line)
    if lines:
        lines[-1] = fm.elidedText(lines[-1], Qt.TextElideMode.ElideRight, int(width))
    return lines


def rrect(rect, tl, tr, br, bl):
    p = QPainterPath()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    p.moveTo(x + tl, y)
    p.lineTo(x + w - tr, y); p.quadTo(x + w, y, x + w, y + tr)
    p.lineTo(x + w, y + h - br); p.quadTo(x + w, y + h, x + w - br, y + h)
    p.lineTo(x + bl, y + h); p.quadTo(x, y + h, x, y + h - bl)
    p.lineTo(x, y + tl); p.quadTo(x, y, x + tl, y)
    p.closeSubpath()
    return p


class CardView:
    PAD = 20
    MARK = QColor("#4285F4")
    loader_grows = False

    def __init__(self, widget, card, assets):
        self.w, self.card, self.assets = widget, card, assets
        self._shaped = {}

    @staticmethod
    def prepare(card):
        return {}

    def layout(self, p, targets):
        raise NotImplementedError

    @property
    def c(self):
        return self.w.palette_

    @property
    def width(self):
        return self.w.WIDTH

    @property
    def inner(self):
        return self.width - 2 * self.PAD

    @property
    def hover(self):
        return self.w.hover

    @property
    def mouse(self):
        return self.w.mouse

    def copy(self, payload):
        self.w.copyRequested.emit(payload)

    def open(self, url):
        self.w.openRequested.emit(url)

    def tint(self):
        return T.TINT.get(self.card.accent, T.SURFACE)

    def tile(self):
        return T.mixh(self.tint(), "#FFFFFF", 0.065)

    def text(self, p, s, px, w, color, x, y, width=None, lines=1, rond=100, wdth=100, align="left", fit=False):
        width = width or self.inner
        f = card_font(px, w, rond, wdth)
        fm = QFontMetrics(f)
        if fit and lines == 1:
            while fm.horizontalAdvance(s) > width and wdth > 80:
                wdth -= 5; f = card_font(px, w, rond, wdth); fm = QFontMetrics(f)
        ls = [fm.elidedText(s, Qt.TextElideMode.ElideRight, int(width))] if lines == 1 else wrap(fm, s, width, lines)
        if p:
            p.setFont(f); p.setPen(color)
            for i, line in enumerate(ls):
                lx = x
                if align == "right":
                    lx = x + width - fm.horizontalAdvance(line)
                elif align == "center":
                    lx = x + (width - fm.horizontalAdvance(line)) / 2
                p.drawText(QPointF(lx, y + fm.ascent() + i * fm.lineSpacing()), line)
        return len(ls) * fm.lineSpacing(), (max(fm.horizontalAdvance(l) for l in ls) if ls else 0)

    def pill(self, p, label, x, y, bg, fg, h=30, icon=None, px=13, weight=560, dot=None, name=None, targets=None,
             payload=None):
        f = card_font(px, weight); fm = QFontMetrics(f)
        lead = (22 if icon or dot else 0)
        w = fm.horizontalAdvance(label) + 24 + lead
        r = QRectF(x, y, w, h)
        if targets is not None and name:
            targets[name] = (r, (lambda: self.copy(payload)) if payload else None)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(bg) if isinstance(bg, str) else bg)
            p.drawRoundedRect(r, 8 if h <= 32 else h / 2, 8 if h <= 32 else h / 2)
            if name and self.hover == name:
                p.setBrush(QColor(255, 255, 255, 18)); p.drawRoundedRect(r, 8, 8)
            if dot:
                p.setBrush(C(dot)); p.drawEllipse(QPointF(x + 16, y + h / 2), 5, 5)
            if icon:
                glyph(p, icon, QRectF(x + 9, y + (h - 15) / 2, 15, 15), fg)
            p.setFont(f); p.setPen(fg)
            p.drawText(QRectF(x + 12 + lead, y, w - 24 - lead, h), Qt.AlignmentFlag.AlignVCenter, label)
        return w

    def buttons(self, p, actions, x, y, targets):
        if not actions:
            return y
        f = card_font(13, 600); fm = QFontMetrics(f)
        widths = [fm.horizontalAdvance(a.label) + 32 for a in actions]
        h, gap = 40, 2
        cx = x
        for i, (a, w) in enumerate(zip(actions, widths)):
            r = QRectF(cx, y, w, h)
            first, last = i == 0, i == len(actions) - 1
            name = f"action{i}"
            targets[name] = (r, self.action_handler(a))
            if p:
                hover = self.hover == name
                big, small = h / 2, (h / 2 if hover else 8)
                path = rrect(r, big if first else small, big if last else small, big if last else small, big if first else small)
                bg = self.c["primary"] if first else C(self.tile())
                fg = self.c["on_primary"] if first else self.c["on_surface"]
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg); p.drawPath(path)
                p.setFont(f); p.setPen(fg); p.drawText(r, Qt.AlignmentFlag.AlignCenter, a.label)
            cx += w + gap
        return y + h

    def action_handler(self, action):
        if action.kind == "open":
            return lambda: self.open(action.payload)
        return lambda: self.copy(action.payload)

    def source(self, p, y, targets, text=None):
        card = self.card
        label = text or card.source
        if not label:
            return y - 6
        f = card_font(11.5, 520); fm = QFontMetrics(f)
        r = QRectF(self.PAD, y, fm.horizontalAdvance(label) + 2, fm.lineSpacing())
        if card.url:
            targets["source"] = (r.adjusted(-6, -4, 6, 4), lambda: self.open(card.url))
        if p:
            p.setFont(f); p.setPen(self.c["on_surface"] if self.hover == "source" else self.c["on_surface_variant"])
            p.drawText(QPointF(r.left(), r.top() + fm.ascent()), label)
        return y + fm.lineSpacing()

    def shaped(self, img, shape, size, cover=True):
        key = (id(img), shape, size)
        if key not in self._shaped:
            out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied); out.fill(0)
            q = QPainter(out); q.setRenderHint(QPainter.RenderHint.Antialiasing); q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            q.setClipPath(shape_path(shape, QRectF(0, 0, size, size)))
            if cover:
                side = min(img.width(), img.height())
                src = QRectF((img.width() - side) / 2, (img.height() - side) / 2 * 0.6, side, side)
                q.drawImage(QRectF(0, 0, size, size), img, src)
            else:
                q.fillRect(QRectF(0, 0, size, size), QColor("#F1F3F4"))
                s = size * 0.68
                sc = min(s / img.width(), s / img.height())
                w, h = img.width() * sc, img.height() * sc
                q.drawImage(QRectF((size - w) / 2, (size - h) / 2, w, h), img)
            q.end()
            self._shaped[key] = out
        return self._shaped[key]

    def copy_icon(self, p, r, hover):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22 if hover else 0))
        p.drawEllipse(r)
        c = r.center()
        p.setPen(QPen(self.c["on_surface_variant"] if not hover else self.c["on_surface"], 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(c.x() - 5, c.y() - 3, 9, 10), 2.5, 2.5)
        p.drawRoundedRect(QRectF(c.x() - 2, c.y() - 7, 9, 10), 2.5, 2.5)

    def line_plot(self, p, points, plot, floor):
        vs = [v for _, v in points]
        lo, hi = min(vs), max(vs)
        pv = (hi - lo) * 0.1 or floor
        lo, hi = lo - pv, hi + pv

        def pos(i, v):
            return QPointF(plot.left() + plot.width() * i / (len(points) - 1),
                           plot.bottom() - (v - lo) / (hi - lo) * plot.height())

        line = QPainterPath(pos(0, points[0][1]))
        for i, (_, v) in enumerate(points[1:], 1):
            line.lineTo(pos(i, v))
        wash = QPainterPath(line); wash.lineTo(plot.bottomRight()); wash.lineTo(plot.bottomLeft()); wash.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(66, 133, 244, 26)); p.drawPath(wash)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(self.MARK, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(line)
        p.setPen(QPen(C(self.tint()), 2)); p.setBrush(self.MARK); p.drawEllipse(pos(len(points) - 1, points[-1][1]), 5, 5)
        p.setFont(card_font(11, 520)); p.setPen(self.c["on_surface_variant"])
        axis = QRectF(plot.left(), plot.bottom() + 4, plot.width(), 14)
        p.drawText(axis, Qt.AlignmentFlag.AlignLeft, str(points[0][0]))
        p.drawText(axis, Qt.AlignmentFlag.AlignRight, str(points[-1][0]))


class CardWidget(QWidget):
    copyRequested = pyqtSignal(str)
    openRequested = pyqtSignal(str)

    LOADER_SEQ = ["cookie9", "soft_burst", "cookie4", "clover4", "sunny"]

    def __init__(self, parent, palette, ambient=True, width=404, role="secondary"):
        super().__init__(parent)
        self.palette_, self.ambient, self.role = palette, ambient, role
        self.WIDTH = width
        self.card = None
        self.view = None
        self.loading = False
        self.loading_label = "Looking it up…"
        self.hover = None
        self.mouse = QPointF()
        self._targets = {}
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=16, timeout=self.update)
        self._cache = self._cache_key = None
        self._trans_t0 = None
        screen = QGuiApplication.primaryScreen()
        rate = (screen.refreshRate() if screen else 60.0) or 60.0
        self._trans_timer = QTimer(self, interval=max(4, round(1000 / rate)), timeout=self._trans_step)
        self.setMouseTracking(True)
        self.resize(width, 120)

    def radius(self):
        return 32 if self.role == "hero" else 24

    def sizeHint(self):
        return QSize(self.WIDTH, self.height())

    def set_loading(self, label="Looking it up…"):
        self.card, self.view, self.loading = None, None, True
        self.loading_label = label
        self._t0 = time.monotonic()
        if self.ambient:
            self._timer.start()
        self.resize(self.WIDTH, 124)
        self.update()

    def set_card(self, card, assets=None):
        animate = self.loading and self.isVisible() and self.ambient
        h0, loader_t = self.height(), time.monotonic() - self._t0
        self._cache_key = None
        self.card, self.loading = card, False
        cls = view_for(card)
        self.view = cls(self, card, cls.prepare(card) if assets is None else assets)
        self._timer.stop()
        self.resize(self.WIDTH, self._layout(None))
        self.update()
        if not animate:
            return
        self._h0, self._h1 = h0, self.height()
        self._loader_t = loader_t
        self._final = self._render()
        self._trans_t0 = time.monotonic()
        self.resize(self.WIDTH, h0)
        self._trans_timer.start()

    def transitioning(self):
        return self._trans_t0 is not None

    def layout_height(self):
        return self._h1 if self._trans_t0 is not None else self.height()

    def _layout(self, p):
        targets = {}
        h = self.view.layout(p, targets)
        self._targets = targets
        return int(h)

    def _target_at(self, pos):
        return next((name for name, (r, _) in self._targets.items() if r.contains(pos)), None)

    def mouseMoveEvent(self, e):
        self.mouse = e.position()
        hover = self._target_at(e.position())
        if hover and hover.startswith("series"):
            self.hover = hover
            self.update()
            return
        if hover != self.hover:
            self.hover = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def mousePressEvent(self, e):
        name = self._target_at(e.position())
        if name and self._targets[name][1] is not None:
            self._targets[name][1]()
        e.accept()

    def _render(self):
        pm = QPixmap(self.size() * self.devicePixelRatioF())
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        pm.fill(Qt.GlobalColor.transparent)
        self._paint_now(QPainter(pm))
        return pm

    def paintEvent(self, e):
        if self._trans_t0 is not None:
            return self._paint_transition(QPainter(self))
        if self.loading or not self.card:
            return self._paint_now(QPainter(self))
        key = (self.size().width(), self.size().height(), self.hover,
               round(self.mouse.x()) if self.hover and self.hover.startswith("series") else None)
        if self._cache_key != key:
            self._cache, self._cache_key = self._render(), key
        QPainter(self).drawPixmap(0, 0, self._cache)

    def _trans_step(self):
        raw = min(1.0, (time.monotonic() - self._trans_t0) / TRANSITION)
        self.resize(self.WIDTH, round(self._h0 + (self._h1 - self._h0) * TRANSITION_SPRING.valueForProgress(raw)))
        self.update()
        if raw >= 1.0:
            self._trans_timer.stop()
            self._trans_t0 = None
            self._final = None
            self.resize(self.WIDTH, self._h1)
            self.update()

    def _tint(self):
        return C(self.view.tint()) if self.view else self.palette_["surface"]

    def _paint_transition(self, p):
        raw = min(1.0, (time.monotonic() - self._trans_t0) / TRANSITION)
        e = TRANSITION_SPRING.valueForProgress(raw)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, self.radius(), self.radius())
        tint = self._tint()
        surface = self.palette_["surface"]
        k = ramp(raw, 0.0, 0.5)
        bg = QColor.fromRgbF(*(a + (b - a) * k for a, b in zip(surface.getRgbF()[:3], tint.getRgbF()[:3])))
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.setBrush(bg)
        p.drawPath(clip)
        p.save()
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        p.setOpacity(ramp(raw, 0.12, 0.45))
        p.drawPixmap(0, 0, self._final)
        p.restore()
        pad = CardView.PAD
        start = QRectF(pad, 34, 56, 56)
        end = QRectF(pad - 2, pad, 92, 92) if self.view.loader_grows else start
        rect = QRectF(start.x() + (end.x() - start.x()) * e, start.y() + (end.y() - start.y()) * e,
                      start.width() + (end.width() - start.width()) * e, start.height() + (end.height() - start.height()) * e)
        alpha = 1.0 - ramp(raw, 0.35, 0.35)
        if alpha > 0:
            p.setOpacity(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(T.PRIMARY_CONTAINER))
            p.drawPath(self._loader_path(self._loader_t, rect, settle=e))
        label_alpha = 1.0 - ramp(raw, 0.0, 0.22)
        if label_alpha > 0:
            p.setOpacity(label_alpha)
            self._paint_loader_label(p, start)
        p.setOpacity(1.0)

    def _paint_now(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(self._tint() if self.card else self.palette_["surface"])
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawRoundedRect(r, self.radius(), self.radius())
        if self.loading:
            self._paint_loader(p)
        elif self.card:
            self._layout(p)

    def _loader_path(self, t, rect, settle=0.0):
        seq = self.LOADER_SEQ
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

    def _paint_loader(self, p):
        rect = QRectF(CardView.PAD, 34, 56, 56)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(T.PRIMARY_CONTAINER))
        p.drawPath(self._loader_path(time.monotonic() - self._t0, rect))
        self._paint_loader_label(p, rect)

    def _paint_loader_label(self, p, rect):
        f = card_font(15, 560); p.setFont(f); p.setPen(self.palette_["on_surface"])
        p.drawText(QPointF(rect.right() + 18, 58), self.loading_label)
        f = card_font(12, 480); p.setFont(f); p.setPen(self.palette_["on_surface_variant"])
        p.drawText(QPointF(rect.right() + 18, 80), "Wikipedia · Wikidata · OpenStreetMap")
