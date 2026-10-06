import importlib
import time
from dataclasses import dataclass
from functools import cache

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from circlesearch.core import plugins
from circlesearch.core.registry import Registry
from circlesearch.ui import tokens as T
from circlesearch.ui.effects import loader_path
from circlesearch.ui.motion import MOTION, Spring, SpringCurve, mix, ramp
from circlesearch.ui.shapes import glyph, shape_path
from circlesearch.ui.theme import C, type_font

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


class Interaction:
    def __init__(self):
        self.hover, self.press = Spring(*T.SPRING_EFFECTS), Spring(*T.SPRING_EFFECTS)
        self.lift, self.squish = Spring(*T.SPRING_SPATIAL), Spring(*T.SPRING_SPATIAL)

    def aim(self, hovered, pressed):
        self.hover.set(float(hovered)); self.lift.set(float(hovered))
        self.press.set(float(pressed)); self.squish.set(float(pressed))

    def step(self, dt):
        return any([s.step(dt) for s in (self.hover, self.press, self.lift, self.squish)])

    @property
    def idle(self):
        return all(s.value == 0 and not s.active for s in (self.hover, self.press, self.lift, self.squish))


IDLE = Interaction()


@dataclass
class Chip:
    label: str
    tone: str = "tile"
    icon: str | None = None
    dot: str | None = None
    payload: str | None = None


class CardView:
    PAD = T.PAD
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

    def copy(self, payload):
        self.w.copyRequested.emit(payload)

    def open(self, url):
        self.w.openRequested.emit(url)

    def action_handler(self, action):
        if action.kind == "open":
            return lambda: self.open(action.payload)
        return lambda: self.copy(action.payload)

    def family(self):
        return self.card.accent if self.card.accent in T.FAMILY else "neutral"

    def tint(self):
        return T.TINT[self.family()]

    def tile(self):
        return T.mixh(self.tint(), "#FFFFFF", 0.065)

    def container(self):
        return C(T.FAMILY[self.family()][0])

    def on_container(self):
        return C(T.FAMILY[self.family()][1])

    def text(self, p, s, x, y, width=None, style="body", color=None, lines=1, align="left", fit=False, weight=None,
             wdth=100):
        width = width or self.inner
        f = type_font(style, weight, wdth)
        fm = QFontMetrics(f)
        if fit and lines == 1:
            while fm.horizontalAdvance(s) > width and wdth > 80:
                wdth -= 5; f = type_font(style, weight, wdth); fm = QFontMetrics(f)
        ls = [fm.elidedText(s, Qt.TextElideMode.ElideRight, int(width))] if lines == 1 else wrap(fm, s, width, lines)
        if p:
            p.setFont(f); p.setPen(color or self.c["on_surface"])
            for i, line in enumerate(ls):
                lx = x
                if align == "right":
                    lx = x + width - fm.horizontalAdvance(line)
                elif align == "center":
                    lx = x + (width - fm.horizontalAdvance(line)) / 2
                p.drawText(QPointF(lx, y + fm.ascent() + i * fm.lineSpacing()), line)
        return len(ls) * fm.lineSpacing(), (max(fm.horizontalAdvance(l) for l in ls) if ls else 0)

    def measure(self, s, style, weight=None):
        return QFontMetrics(type_font(style, weight)).horizontalAdvance(s)

    def fx(self, name):
        return self.w.interaction(name)

    def state(self, p, rect, radius, name, color=None):
        if not p:
            return
        it = self.fx(name)
        alpha = T.HOVER_ALPHA * it.hover.value + T.PRESS_ALPHA * it.press.value
        if alpha > 0.5:
            c = QColor(color or QColor(255, 255, 255))
            c.setAlpha(round(min(255, alpha)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(rect, radius, radius)

    def squeezed(self, p, rect, name, depth=0.05):
        k = 1 - depth * self.fx(name).squish.value
        c = rect.center()
        p.translate(c)
        p.scale(k, k)
        p.translate(-c)

    def copy_icon(self, p, r, amount, color=None, reveal=1.0):
        if reveal <= 0.01:
            return
        p.save()
        p.setOpacity(p.opacity() * min(1.0, reveal))
        k = 0.6 + 0.4 * reveal
        c = r.center()
        p.translate(c); p.scale(k, k); p.translate(-c)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, round(T.HOVER_ALPHA * amount)))
        p.drawEllipse(r)
        p.setPen(QPen(color or mix(self.c["on_surface_variant"], self.c["on_surface"], amount), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(c.x() - 5, c.y() - 3, 9, 10), 2.5, 2.5)
        p.drawRoundedRect(QRectF(c.x() - 2, c.y() - 7, 9, 10), 2.5, 2.5)
        p.restore()

    def copyable(self, p, targets, name, rect, payload, radius=T.RADIUS["tile"], always=False, icon=None, ink=None):
        targets[name] = (rect, lambda: self.copy(payload))
        if not p:
            return
        it = self.fx(name)
        self.state(p, rect, radius, name)
        s = T.ICON_BUTTON - 8
        r = icon or QRectF(rect.right() - s - 6, rect.top() + 6, s, s)
        p.save()
        self.squeezed(p, r, name, 0.12)
        self.copy_icon(p, r, it.hover.value, ink, 1.0 if always else it.lift.value)
        p.restore()

    def chip(self, p, chip, x, y, small=False, name=None, targets=None):
        h = T.CHIP_SMALL_H if small else T.CHIP_H
        f = type_font("label")
        fm = QFontMetrics(f)
        lead = 22 if chip.icon or chip.dot else 0
        w = fm.horizontalAdvance(chip.label) + 24 + lead
        r = QRectF(x, y, w, h)
        active = chip.payload is not None and targets is not None and name
        if active:
            targets[name] = (r, lambda: self.copy(chip.payload))
        if p:
            bg, fg = {"tile": (C(self.tile()), self.c["on_surface"]),
                      "quiet": (C(self.tile()), self.c["on_surface_variant"]),
                      "container": (self.container(), self.on_container())}[chip.tone]
            p.save()
            if active:
                self.squeezed(p, r, name)
            radius = T.RADIUS["chip"] + (h / 2 - T.RADIUS["chip"]) * min(1.0, self.fx(name).lift.value) if active \
                else T.RADIUS["chip"]
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg)
            p.drawRoundedRect(r, radius, radius)
            if active:
                self.state(p, r, radius, name)
            if chip.dot:
                p.setBrush(C(chip.dot)); p.drawEllipse(QPointF(x + 16, y + h / 2), 5, 5)
            if chip.icon:
                glyph(p, chip.icon, QRectF(x + 9, y + (h - 15) / 2, 15, 15), fg)
            p.setFont(f); p.setPen(fg)
            p.drawText(QRectF(x + 12 + lead, y, w - 24 - lead, h), Qt.AlignmentFlag.AlignVCenter, chip.label)
            p.restore()
        return w

    def chip_row(self, p, chips, y, targets=None, small=False):
        chips = [Chip(c) if isinstance(c, str) else c for c in chips if c]
        if not chips:
            return y
        h = T.CHIP_SMALL_H if small else T.CHIP_H
        x = self.PAD
        for i, chip in enumerate(chips):
            w = self.measure(chip.label, "label") + 24 + (22 if chip.icon or chip.dot else 0)
            if x + w > self.PAD + self.inner and x > self.PAD:
                x, y = self.PAD, y + h + 6
            x += self.chip(p, chip, x, y, small=small, name=f"chip{i}", targets=targets) + 6
        return y + h + T.SECTION

    def header(self, p, y, title, chip=None, quiet=False, lines=1):
        chip_w = self.measure(chip.label, "label") + 24 + (22 if chip.icon or chip.dot else 0) if chip else 0
        width = self.inner - (chip_w + T.GAP if chip else 0)
        color = self.c["on_surface_variant"] if quiet else self.c["on_surface"]
        h, _ = self.text(p, title, self.PAD, y, width, "title", color, lines=lines, weight=560 if quiet else None)
        if chip:
            line = QFontMetrics(type_font("title")).lineSpacing()
            self.chip(p, chip, self.PAD + self.inner - chip_w, y + (line - T.CHIP_SMALL_H) / 2, small=True)
        return y + h + T.SECTION

    def paragraph(self, p, y, text, lines=3, quiet=False, style="body"):
        if not text:
            return y
        h, _ = self.text(p, text, self.PAD, y, self.inner, style,
                         self.c["on_surface_variant"] if quiet else self.c["on_surface"], lines=lines)
        return y + h + T.SECTION

    def big_value(self, p, y, value, targets, copy=True, style="display", lead=0):
        icon = T.ICON_BUTTON
        width = self.inner - lead - (icon + T.GAP if copy else 0)
        h, w = self.text(p, value, self.PAD + lead, y, width, style, fit=True)
        if copy:
            r = QRectF(self.PAD + self.inner - icon, y + (h - icon) / 2, icon, icon)
            self.copyable(p, targets, "value", r, value, radius=icon / 2, always=True, icon=r)
        return y + h + 4

    def rows(self, p, y, rows, targets):
        lf, vf = QFontMetrics(type_font("label")), QFontMetrics(type_font("body"))
        label_w, value_x = 110, self.PAD + 116
        value_w = self.inner - 116 - T.ICON_BUTTON
        for i, (label, value) in enumerate(rows):
            row_h = max(36, len(wrap(vf, value, value_w, 2)) * vf.lineSpacing() + 12)
            row = QRectF(self.PAD - 8, y, self.inner + 16, row_h)
            s = T.ICON_BUTTON - 8
            self.copyable(p, targets, f"row{i}", row, value, radius=12,
                          icon=QRectF(row.right() - s - 6, row.top() + (row_h - s) / 2, s, s))
            self.text(p, label, self.PAD, y + 6 + (vf.lineSpacing() - lf.lineSpacing()) / 2, label_w, "label",
                      self.c["on_surface_variant"])
            self.text(p, value, value_x, y + 6, value_w, "body", lines=2)
            y += row_h
        return y + T.SECTION - 6 if rows else y

    def button_group(self, p, actions, y, targets):
        if not actions:
            return y
        f = type_font("button"); fm = QFontMetrics(f)
        h, gap = T.BUTTON_H, 2
        x = self.PAD
        for i, a in enumerate(actions):
            w = fm.horizontalAdvance(a.label) + 32
            r = QRectF(x, y, w, h)
            first, last = i == 0, i == len(actions) - 1
            name = f"action{i}"
            targets[name] = (r, self.action_handler(a))
            if p:
                lift = max(0.0, min(1.0, self.fx(name).lift.value))
                big, small = h / 2, 8 + (h / 2 - 8) * lift
                path = rrect(r, big if first else small, big if last else small, big if last else small, big if first else small)
                bg = self.c["primary"] if first else C(self.tile())
                fg = self.c["on_primary"] if first else self.c["on_surface"]
                p.save()
                self.squeezed(p, r, name)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg); p.drawPath(path)
                it = self.fx(name)
                alpha = T.HOVER_ALPHA * it.hover.value + T.PRESS_ALPHA * it.press.value
                if alpha > 0.5:
                    p.setBrush(QColor(fg.red(), fg.green(), fg.blue(), round(alpha * 1.4))); p.drawPath(path)
                p.setFont(f); p.setPen(fg); p.drawText(r, Qt.AlignmentFlag.AlignCenter, a.label)
                p.restore()
            x += w + gap
        return y + h + T.SECTION

    def footer(self, p, y, targets):
        card = self.card
        if not card.source:
            return y - T.SECTION + self.PAD
        f = type_font("caption"); fm = QFontMetrics(f)
        r = QRectF(self.PAD, y, fm.horizontalAdvance(card.source) + 2, fm.lineSpacing())
        if card.url:
            targets["source"] = (r.adjusted(-6, -4, 6, 4), lambda: self.open(card.url))
        if p:
            it = self.fx("source")
            color = mix(self.c["on_surface_variant"], self.c["on_surface"], it.hover.value)
            p.setFont(f); p.setPen(color)
            p.drawText(QPointF(r.left(), r.top() + fm.ascent()), card.source)
            reach = max(0.0, min(1.05, it.lift.value))
            if reach > 0.01:
                p.drawLine(QPointF(r.left(), r.bottom() - 1), QPointF(r.left() + r.width() * reach, r.bottom() - 1))
        return y + fm.lineSpacing() + self.PAD - 4

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

    def line_plot(self, p, points, plot, floor):
        vs = [v for _, v in points]
        lo, hi = min(vs), max(vs)
        pv = (hi - lo) * 0.1 or floor
        lo, hi = lo - pv, hi + pv

        def pos(i, v):
            return QPointF(plot.left() + plot.width() * i / (len(points) - 1),
                           plot.bottom() - (v - lo) / (hi - lo) * plot.height())

        line_color = C(T.LINE)
        line = QPainterPath(pos(0, points[0][1]))
        for i, (_, v) in enumerate(points[1:], 1):
            line.lineTo(pos(i, v))
        wash = QPainterPath(line); wash.lineTo(plot.bottomRight()); wash.lineTo(plot.bottomLeft()); wash.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.LINE, 26)); p.drawPath(wash)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(line_color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(line)
        p.setPen(QPen(C(self.tint()), 2)); p.setBrush(line_color); p.drawEllipse(pos(len(points) - 1, points[-1][1]), 5, 5)
        p.setFont(type_font("caption")); p.setPen(self.c["on_surface_variant"])
        axis = QRectF(plot.left(), plot.bottom() + 4, plot.width(), 14)
        p.drawText(axis, Qt.AlignmentFlag.AlignLeft, str(points[0][0]))
        p.drawText(axis, Qt.AlignmentFlag.AlignRight, str(points[-1][0]))


class CardWidget(QWidget):
    copyRequested = pyqtSignal(str)
    openRequested = pyqtSignal(str)

    def __init__(self, parent, palette, ambient=True, width=404, role="secondary"):
        super().__init__(parent)
        self.palette_, self.ambient, self.role = palette, ambient, role
        self.WIDTH = width
        self.card = None
        self.view = None
        self.loading = False
        self.loading_label = "Looking it up…"
        self.hover = None
        self.pressed = None
        self.interactions = {}
        self._targets = {}
        self._t0 = time.monotonic()
        screen = QGuiApplication.primaryScreen()
        rate = (screen.refreshRate() if screen else 60.0) or 60.0
        self._timer = QTimer(self, interval=max(4, round(1000 / rate)), timeout=self.update)
        self._cache = self._cache_key = None
        self._trans_t0 = None
        self._trans_timer = QTimer(self, interval=max(4, round(1000 / rate)), timeout=self._trans_step)
        self._motion_timer = QTimer(self, interval=max(4, round(1000 / rate)), timeout=self._motion_step)
        self._motion_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._motion_last = 0.0
        self.setMouseTracking(True)
        self.resize(width, 120)

    def radius(self):
        return T.RADIUS["hero"] if self.role == "hero" else T.RADIUS["card"]

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

    def interaction(self, name):
        return self.interactions.get(name, IDLE)

    def _aim(self):
        for name in {self.hover, self.pressed} - {None}:
            self.interactions.setdefault(name, Interaction())
        for name, it in self.interactions.items():
            it.aim(name == self.hover, name == self.pressed)
        if not self._motion_timer.isActive():
            self._motion_last = time.monotonic()
            self._motion_timer.start()

    def _motion_step(self):
        now = time.monotonic()
        dt, self._motion_last = now - self._motion_last, now
        active = False
        for name, it in list(self.interactions.items()):
            if it.step(dt):
                active = True
            elif it.idle and name not in (self.hover, self.pressed):
                del self.interactions[name]
        self.update()
        if not active:
            self._motion_timer.stop()

    def mouseMoveEvent(self, e):
        hover = self._target_at(e.position())
        if hover != self.hover:
            self.hover = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor)
            self._aim()

    def leaveEvent(self, e):
        self.hover = self.pressed = None
        self._aim()

    def mousePressEvent(self, e):
        name = self._target_at(e.position())
        if name and self._targets[name][1]:
            self.pressed = name
            self._aim()
        e.accept()

    def mouseReleaseEvent(self, e):
        pressed, self.pressed = self.pressed, None
        self._aim()
        if pressed and self._target_at(e.position()) == pressed and pressed in self._targets:
            self._targets[pressed][1]()
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
        if self._motion_timer.isActive():
            return self._paint_now(QPainter(self))
        key = (self.size().width(), self.size().height(), self.hover, self.pressed)
        if self._cache_key != key:
            self._cache, self._cache_key = self._render(), key
        QPainter(self).drawPixmap(0, 0, self._cache)

    def _progress(self):
        duration = TRANSITION * MOTION
        return 1.0 if duration <= 0 else min(1.0, (time.monotonic() - self._trans_t0) / duration)

    def _trans_step(self):
        raw = self._progress()
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
        raw = self._progress()
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
        p.setPen(QPen(QColor(255, 255, 255, T.BORDER_ALPHA), 1))
        p.setBrush(bg)
        p.drawPath(clip)
        p.save()
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        p.setOpacity(ramp(raw, 0.12, 0.45))
        p.drawPixmap(0, 0, self._final)
        p.restore()
        pad = T.PAD
        start = QRectF(pad, 34, 56, 56)
        end = QRectF(pad - 2, pad, 92, 92) if self.view.loader_grows else start
        rect = QRectF(start.x() + (end.x() - start.x()) * e, start.y() + (end.y() - start.y()) * e,
                      start.width() + (end.width() - start.width()) * e, start.height() + (end.height() - start.height()) * e)
        alpha = 1.0 - ramp(raw, 0.35, 0.35)
        if alpha > 0:
            p.setOpacity(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(T.PRIMARY_CONTAINER))
            p.drawPath(loader_path(self._loader_t, rect, settle=e))
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
        p.setPen(QPen(QColor(255, 255, 255, T.BORDER_ALPHA), 1))
        p.drawRoundedRect(r, self.radius(), self.radius())
        if self.loading:
            self._paint_loader(p)
        elif self.card:
            self._layout(p)

    def _paint_loader(self, p):
        rect = QRectF(T.PAD, 34, 56, 56)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(T.PRIMARY_CONTAINER))
        p.drawPath(loader_path(time.monotonic() - self._t0, rect))
        self._paint_loader_label(p, rect)

    def _paint_loader_label(self, p, rect):
        p.setFont(type_font("body", 560)); p.setPen(self.palette_["on_surface"])
        p.drawText(QPointF(rect.right() + 18, 58), self.loading_label)
        p.setFont(type_font("caption")); p.setPen(self.palette_["on_surface_variant"])
        p.drawText(QPointF(rect.right() + 18, 80), "Wikipedia · Wikidata · OpenStreetMap")
