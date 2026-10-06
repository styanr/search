from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor

from circlesearch.core.cards import Action
from circlesearch.plugins.color import ColorCard, PaletteCard, describe
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, rrect, view
from circlesearch.ui.motion import Spring, mix
from circlesearch.ui.shapes import STARS, shape_path, star_path

TONES = (0.92, 0.82, 0.70, 0.58, None, 0.38, 0.28, 0.18, 0.10)
HARMONIES = [("Complement", [180]), ("Analogous", [-30, 30]), ("Triadic", [120, 240])]


def ink_for(color):
    return QColor("#111") if T.lum(color.name()) > 0.35 else QColor("white")


class Swatches(CardView):
    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.colors = {}
        self.selected = None
        self.blend = Spring(520, 0.78, 1.0)
        self.shown = self.start = self.base()
        self.target = self.base()

    def base(self):
        return QColor(self.card.swatch[:7])

    def focus(self):
        name = self.w.hover if self.w.hover in self.colors else self.selected
        return self.colors.get(name, self.base())

    def step(self, dt):
        target = self.focus()
        if target.rgb() != self.target.rgb():
            self.start, self.target = self.current(), target
            self.blend.value, self.blend.target = 0.0, 1.0
        return self.blend.step(dt)

    def current(self):
        return mix(self.start, self.target, max(0.0, min(1.0, self.blend.value)))

    def state_key(self):
        return round(self.blend.value, 3), self.selected, self.target.rgb()

    def pick(self, name):
        color = self.colors[name]
        self.selected = None if self.selected == name else name
        self.copy(color.name().upper())

    def swatch(self, p, targets, rect, radius, name, color):
        self.colors[name] = color
        targets[name] = (rect, lambda n=name: self.pick(n))


@view(ColorCard)
class ColorView(Swatches):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        base = self.base()
        shown, target = self.current(), self.target
        hex_, formats, contrast = describe(target.red(), target.green(), target.blue()) \
            if target.rgb() != base.rgb() else (card.title, card.formats, card.contrast)
        y = pad
        sw = QRectF(pad, y, self.inner, 112)
        ink = ink_for(shown)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(shown); p.drawRoundedRect(sw, T.RADIUS["media"], T.RADIUS["media"])
        self.copyable(p, targets, "value", sw, hex_, radius=T.RADIUS["media"], always=True, ink=ink)
        k = max(0.0, min(1.0, self.blend.value))
        if p:
            p.save()
            p.setOpacity(0.35 + 0.65 * k)
            self.text(p, hex_, sw.left() + 20, sw.top() + 18 + (1 - k) * 6, sw.width() - 80, "headline", ink)
            self.text(p, contrast, sw.left() + 20, sw.top() + 60, sw.width() - 40, "label", ink)
            p.restore()
        self.text(p, "Aa", sw.left(), sw.top() + 60, sw.width() - 20, "headline", QColor("white"), align="right", weight=700)
        self.text(p, "Aa", sw.left(), sw.top() + 60, sw.width() - 66, "headline", QColor("#111"), align="right", weight=700)
        y = sw.bottom() + T.GAP + 4
        h, s, l, _ = base.getHslF()
        h = h if h >= 0 else 0
        steps = [base if lt is None else QColor.fromHslF(h, s, lt) for lt in TONES]
        n, gap = len(steps), 2
        weights = [1 + 1.4 * max(-0.2, self.fx(f"tone{i}").lift.value) for i in range(n)]
        unit = (self.inner - gap * (n - 1)) / sum(weights)
        x = pad
        for i, col in enumerate(steps):
            name = f"tone{i}"
            w = unit * weights[i]
            r = QRectF(x, y, w, 40)
            x += w + gap
            self.swatch(p, targets, r, 4, name, col)
            if not p:
                continue
            lift = max(0.0, self.fx(name).lift.value)
            tl, tr = (12 if i == 0 else 4 + 8 * lift), (12 if i == n - 1 else 4 + 8 * lift)
            p.save()
            self.squeezed(p, r, name, 0.06)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(col); p.drawPath(rrect(r, tl, tr, tr, tl))
            mark = ink_for(col)
            if self.selected == name or i == 4:
                p.setBrush(mark); p.drawEllipse(QPointF(r.center().x(), r.bottom() - 9), 3, 3)
            if lift > 0.3 and w > 52:
                p.setOpacity(min(1.0, (lift - 0.3) * 2))
                done = self.done(name)
                label = "Copied" if done > 0.01 else col.name().upper()[1:]
                self.text(p, label, r.left(), r.top() + 8, r.width(), "caption", mark, align="center", weight=650)
            p.restore()
        y += 40 + T.SECTION
        gx = pad
        for label, offs in HARMONIES:
            self.text(p, label, gx, y, 120, "caption", self.c["on_surface_variant"])
            for j, o in enumerate(offs):
                col = QColor.fromHslF(((h * 360 + o) % 360) / 360, s, l)
                name = f"harm{label}{j}"
                cr = QRectF(gx + j * 40, y + 20, 34, 34)
                self.swatch(p, targets, cr, 17, name, col)
                if p:
                    lift = max(-0.1, self.fx(name).lift.value)
                    grow = 1 + 0.16 * lift - 0.08 * self.fx(name).squish.value
                    c = cr.center()
                    p.save()
                    p.translate(c); p.scale(grow, grow); p.rotate(18 * lift if label == "Complement" else 0)
                    p.translate(-c)
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
                    p.drawPath(star_path(cr, *STARS["cookie6"]) if label == "Complement" else shape_path("circle", cr))
                    if self.selected == name or self.done(name) > 0.01:
                        p.setBrush(ink_for(col)); p.drawEllipse(c, 3, 3)
                    p.restore()
            gx += 128 if label != "Complement" else 104
        y += 20 + 34 + T.SECTION
        y = self.button_group(p, [Action(label, "copy", value) for label, value in formats], y, targets)
        return self.footer(p, y, targets)


@view(PaletteCard)
class PaletteView(Swatches):
    def base(self):
        return QColor(self.card.colors[0])

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        shown, target = self.current(), self.target
        hex_, formats, contrast = describe(target.red(), target.green(), target.blue())
        sw = QRectF(pad, pad, self.inner, 96)
        ink = ink_for(shown)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(shown); p.drawRoundedRect(sw, T.RADIUS["media"], T.RADIUS["media"])
        self.copyable(p, targets, "value", sw, hex_, radius=T.RADIUS["media"], always=True, ink=ink)
        k = max(0.0, min(1.0, self.blend.value))
        if p:
            p.save()
            p.setOpacity(0.35 + 0.65 * k)
            self.text(p, hex_, sw.left() + 20, sw.top() + 16 + (1 - k) * 6, sw.width() - 80, "headline", ink)
            self.text(p, contrast, sw.left() + 20, sw.top() + 58, sw.width() - 40, "label", ink)
            p.restore()
        y = sw.bottom() + T.GAP + 4
        n, gap = len(card.colors), 6
        weights = [1 + 0.9 * max(-0.2, self.fx(f"tone{i}").lift.value) for i in range(n)]
        unit = (self.inner - gap * (n - 1)) / sum(weights)
        x = pad
        for i, hx in enumerate(card.colors):
            name = f"tone{i}"
            col = QColor(hx)
            w = unit * weights[i]
            r = QRectF(x, y, w, 56)
            x += w + gap
            self.swatch(p, targets, r, 12, name, col)
            if not p:
                continue
            lift = max(0.0, self.fx(name).lift.value)
            p.save()
            self.squeezed(p, r, name, 0.06)
            radius = 12 + 10 * lift
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(col); p.drawRoundedRect(r, radius, radius)
            mark = ink_for(col)
            if self.selected == name:
                p.setBrush(mark); p.drawEllipse(QPointF(r.center().x(), r.bottom() - 9), 3, 3)
            if lift > 0.3 and w > 56:
                p.setOpacity(min(1.0, (lift - 0.3) * 2))
                label = "Copied" if self.done(name) > 0.01 else hx[1:]
                self.text(p, label, r.left(), r.top() + 18, r.width(), "caption", mark, align="center", weight=650)
            p.restore()
        y += 56 + T.SECTION
        y = self.button_group(p, [Action(label, "copy", value) for label, value in formats] + card.actions, y, targets)
        return self.footer(p, y, targets)
