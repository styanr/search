import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPen

from circlesearch.plugins.times import TimeCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import C


@view(TimeCard)
class TimeView(CardView):
    def clock(self, p, rect, when, label, sub, accent=False):
        c = self.c
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.container() if accent else C(self.tile()))
            p.drawPath(star_path(rect, *STARS["cookie12"]))
            cx, cy, R = rect.center().x(), rect.center().y(), rect.width() / 2 * 0.86
            p.setBrush(QColor(255, 255, 255, 60 if accent else 40))
            for k in range(12):
                a = math.radians(k * 30)
                dot = 2.2 if k % 3 == 0 else 1.2
                p.drawEllipse(QPointF(cx + math.sin(a) * R * 0.86, cy - math.cos(a) * R * 0.86), dot, dot)
            fg = self.on_container() if accent else c["on_surface"]
            ha, ma = math.radians((when.hour % 12 + when.minute / 60) * 30), math.radians(when.minute * 6)
            p.setPen(QPen(fg, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx, cy), QPointF(cx + math.sin(ha) * R * 0.48, cy - math.cos(ha) * R * 0.48))
            p.setPen(QPen(fg, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx, cy), QPointF(cx + math.sin(ma) * R * 0.72, cy - math.cos(ma) * R * 0.72))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(fg); p.drawEllipse(QPointF(cx, cy), 4, 4)
        y = rect.bottom() + 10
        h, _ = self.text(p, label, rect.left() - 20, y, rect.width() + 40, "headline", align="center")
        self.text(p, sub, rect.left() - 30, y + h, rect.width() + 60, "body_small", c["on_surface_variant"], align="center")
        return y + h + 18

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, card.title, Chip(card.relative, "quiet"), quiet=True)
        size = 128
        left = QRectF(pad + self.inner * 0.25 - size / 2, y, size, size)
        right = QRectF(pad + self.inner * 0.75 - size / 2, y, size, size)
        here = card.here.strftime("%H:%M")
        self.clock(p, left, card.there, card.there.strftime("%H:%M"), card.zone_there)
        bottom = self.clock(p, right, card.here, here, f"{card.city_here or 'Your time'} · {card.day.lower()}", accent=True)
        if p:
            cy = left.center().y()
            p.setPen(QPen(self.c["on_surface_variant"], 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            a, b = QPointF(left.right() + 14, cy), QPointF(right.left() - 14, cy)
            p.drawLine(a, b); p.drawPolyline([QPointF(b.x() - 6, cy - 6), b, QPointF(b.x() - 6, cy + 6)])
        self.copyable(p, targets, "value", right.adjusted(-8, -8, 8, 8), here, radius=T.RADIUS["tile"])
        return self.footer(p, bottom + T.SECTION, targets)
