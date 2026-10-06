from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor

from circlesearch.core.cards import Action
from circlesearch.plugins.color import ColorCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, rrect, view
from circlesearch.ui.shapes import STARS, shape_path, star_path


@view(ColorCard)
class ColorView(CardView):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        base = QColor(card.swatch[:7])
        y = pad
        sw = QRectF(pad, y, self.inner, 112)
        ink = QColor("#111") if T.lum(card.swatch[:7]) > 0.35 else QColor("white")
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(base); p.drawRoundedRect(sw, T.RADIUS["media"], T.RADIUS["media"])
        self.copyable(p, targets, "value", sw, card.title, radius=T.RADIUS["media"], always=True, ink=ink)
        self.text(p, card.title, sw.left() + 20, sw.top() + 18, sw.width() - 80, "headline", ink)
        self.text(p, card.contrast, sw.left() + 20, sw.top() + 60, sw.width() - 40, "label", ink)
        self.text(p, "Aa", sw.left(), sw.top() + 60, sw.width() - 20, "headline", QColor("white"), align="right", weight=700)
        self.text(p, "Aa", sw.left(), sw.top() + 60, sw.width() - 66, "headline", QColor("#111"), align="right", weight=700)
        y = sw.bottom() + T.GAP + 4
        h, s, l, _ = base.getHslF()
        steps = [QColor.fromHslF(h if h >= 0 else 0, s, lt) for lt in (0.92, 0.82, 0.70, 0.58, l, 0.38, 0.28, 0.18, 0.10)]
        steps[4] = base
        n, gap = len(steps), 2
        segw = (self.inner - gap * (n - 1)) / n
        for i, col in enumerate(steps):
            r = QRectF(pad + i * (segw + gap), y, segw, 34)
            tl, tr = (12 if i == 0 else 4), (12 if i == n - 1 else 4)
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(col); p.drawPath(rrect(r, tl, tr, tr, tl))
                if i == 4:
                    p.setBrush(QColor("#111") if col.lightnessF() > 0.5 else QColor("white"))
                    p.drawEllipse(r.center(), 3, 3)
            targets[f"tone{i}"] = (r, lambda col=col: self.copy(col.name().upper()))
            self.state(p, r, 4, f"tone{i}")
        y += 34 + T.SECTION
        hue = (h if h >= 0 else 0) * 360
        gx = pad
        for label, offs in [("Complement", [180]), ("Analogous", [-30, 30]), ("Triadic", [120, 240])]:
            self.text(p, label, gx, y, 120, "caption", self.c["on_surface_variant"])
            for j, o in enumerate(offs):
                col = QColor.fromHslF(((hue + o) % 360) / 360, s, l)
                cr = QRectF(gx + j * 40, y + 20, 34, 34)
                if p:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
                    p.drawPath(star_path(cr, *STARS["cookie6"]) if label == "Complement" else shape_path("circle", cr))
                targets[f"harm{label}{j}"] = (cr, lambda col=col: self.copy(col.name().upper()))
                self.state(p, cr, 17, f"harm{label}{j}")
            gx += 128 if label != "Complement" else 104
        y += 20 + 34 + T.SECTION
        y = self.button_group(p, [Action(label, "copy", value) for label, value in card.formats], y, targets)
        return self.footer(p, y, targets)
