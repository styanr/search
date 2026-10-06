import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPen

from circlesearch.plugins.times import TimeCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import C, card_font


@view(TimeCard)
class TimeView(CardView):
    def clock(self, p, rect, h, m, label, sub, accent=False):
        c = self.c
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.PRIMARY_CONTAINER) if accent else C(self.tile()))
            p.drawPath(star_path(rect, *STARS["cookie12"]))
            cx, cy, R = rect.center().x(), rect.center().y(), rect.width() / 2 * 0.86
            p.setBrush(QColor(255, 255, 255, 60 if accent else 40))
            for k in range(12):
                a = math.radians(k * 30)
                p.drawEllipse(QPointF(cx + math.sin(a) * R * 0.86, cy - math.cos(a) * R * 0.86), 2.2 if k % 3 == 0 else 1.2, 2.2 if k % 3 == 0 else 1.2)
            fg = C(T.ON_PRIMARY_CONTAINER) if accent else c["on_surface"]
            ha, ma = math.radians((h % 12 + m / 60) * 30), math.radians(m * 6)
            p.setPen(QPen(fg, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx, cy), QPointF(cx + math.sin(ha) * R * 0.48, cy - math.cos(ha) * R * 0.48))
            p.setPen(QPen(fg, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx, cy), QPointF(cx + math.sin(ma) * R * 0.72, cy - math.cos(ma) * R * 0.72))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(c["primary"] if not accent else QColor("white")); p.drawEllipse(QPointF(cx, cy), 4, 4)
        y = rect.bottom() + 10
        h1, _ = self.text(p, label, 26, 600, c["on_surface"], rect.left() - 20, y, rect.width() + 40, align="center", wdth=100)
        self.text(p, sub, 12.5, 520, c["on_surface_variant"], rect.left() - 30, y + h1, rect.width() + 60, align="center")

    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        self.text(p, card.title, 16, 560, c["on_surface_variant"], pad, y, width)
        if card.relative:
            fm = QFontMetrics(card_font(12.5, 600))
            self.pill(p, card.relative, pad + width - fm.horizontalAdvance(card.relative) - 24, y - 4, self.tile(),
                      c["on_surface"], h=28, px=12.5, weight=600)
        y += 36
        size = 128
        left = QRectF(pad + width * 0.25 - size / 2, y, size, size)
        right = QRectF(pad + width * 0.75 - size / 2, y, size, size)
        here = card.here.strftime("%H:%M")
        self.clock(p, left, card.there.hour, card.there.minute, card.there.strftime("%H:%M"), card.zone_there)
        self.clock(p, right, card.here.hour, card.here.minute, here,
                   f"{card.city_here or 'Your time'} · {card.day.lower()}", accent=True)
        if p:
            cy = left.center().y()
            p.setPen(QPen(c["on_surface_variant"], 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            a, b = QPointF(left.right() + 14, cy), QPointF(right.left() - 14, cy)
            p.drawLine(a, b); p.drawPolyline([QPointF(b.x() - 6, cy - 6), b, QPointF(b.x() - 6, cy + 6)])
        targets["value"] = (right, lambda: self.copy(here))
        y = left.bottom() + 10 + 34 + 18 + 18
        return y + pad - 10
