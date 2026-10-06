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
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        base = QColor(card.swatch[:7])
        y = pad
        sw = QRectF(pad, y, width, 112)
        ink = QColor("#111") if T.lum(card.swatch[:7]) > 0.35 else QColor("white")
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(base); p.drawRoundedRect(sw, 24, 24)
        self.text(p, card.title, 30, 640, ink, sw.left() + 20, sw.top() + 18, sw.width() - 40, wdth=100)
        self.text(p, card.contrast, 12.5, 600, ink, sw.left() + 20, sw.top() + 60, sw.width() - 40)
        self.text(p, "Aa", 30, 700, QColor("white"), sw.left(), sw.top() + 56, sw.width() - 20, align="right")
        self.text(p, "Aa", 30, 700, QColor("#111"), sw.left(), sw.top() + 56, sw.width() - 72, align="right")
        targets["value"] = (sw, lambda: self.copy(card.title))
        y = sw.bottom() + 12
        h, s, l, _ = base.getHslF()
        steps = [QColor.fromHslF(h if h >= 0 else 0, s, lt) for lt in (0.92, 0.82, 0.70, 0.58, l, 0.38, 0.28, 0.18, 0.10)]
        steps[4] = base
        n = len(steps); gap = 2; segw = (width - gap * (n - 1)) / n
        for i, col in enumerate(steps):
            r = QRectF(pad + i * (segw + gap), y, segw, 34)
            targets[f"tone{i}"] = (r, lambda col=col: self.copy(col.name().upper()))
            if p:
                tl = 12 if i == 0 else 4; tr = 12 if i == n - 1 else 4
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
                p.drawPath(rrect(r, tl, tr, tr, tl))
                if i == 4:
                    p.setBrush(QColor("#111") if col.lightnessF() > 0.5 else QColor("white"))
                    p.drawEllipse(r.center(), 3, 3)
        y += 34 + 14
        hue = (h if h >= 0 else 0) * 360
        groups = [("Complement", [180]), ("Analogous", [-30, 30]), ("Triadic", [120, 240])]
        gx = pad
        for label, offs in groups:
            self.text(p, label, 11.5, 560, c["on_surface_variant"], gx, y, 120)
            for j, o in enumerate(offs):
                col = QColor.fromHslF(((hue + o) % 360) / 360, s, l)
                cr = QRectF(gx + j * 40, y + 20, 34, 34)
                targets[f"harm{label}{j}"] = (cr, lambda col=col: self.copy(col.name().upper()))
                if p:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
                    p.drawPath(star_path(cr, *STARS["cookie6"]) if label == "Complement" else shape_path("circle", cr))
            gx += 128 if label != "Complement" else 104
        y += 20 + 34 + 16
        y = self.buttons(p, [Action(label, "copy", value) for label, value in card.formats], pad, y, targets)
        return y + pad
