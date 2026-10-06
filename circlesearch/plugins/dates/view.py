from datetime import date, timedelta

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPen

from circlesearch.plugins.dates import DateCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import C, card_font


@view(DateCard)
class DateView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        d = card.date
        today = date.today()
        y = pad
        self.text(p, card.title, 16, 560, c["on_surface_variant"], pad, y, width)
        fm = QFontMetrics(card_font(12.5, 620))
        self.pill(p, card.relative, pad + width - fm.horizontalAdvance(card.relative) - 24, y - 4,
                  T.mixh(T.ERROR_CONTAINER, T.SURFACE, 0.35), C(T.ON_ERROR_CONTAINER), h=28, px=12.5, weight=620)
        y += 30
        y += self.text(p, d.strftime("%A"), 44, 560, c["on_surface"], pad, y, width, wdth=100)[0]
        y += self.text(p, f"{d:%-d %B %Y}  ·  week {d.isocalendar()[1]}", 14, 500, c["on_surface_variant"], pad, y, width)[0] + 14
        cw, chh = width / 7, 34
        first = d.replace(day=1)
        start = first - timedelta(days=first.weekday())
        if p:
            p.setFont(card_font(11.5, 620)); p.setPen(c["on_surface_variant"])
            for i, wd in enumerate("MTWTFSS"):
                p.drawText(QRectF(pad + i * cw, y, cw, 18), Qt.AlignmentFlag.AlignCenter, wd)
        y += 22
        last = first.replace(month=first.month % 12 + 1, year=first.year + (first.month == 12)) - timedelta(days=1)
        cur = start
        rows = 0
        while cur <= last or cur.weekday() != 0:
            cell = QRectF(pad + cur.weekday() * cw, y + rows * chh, cw, chh)
            if p:
                inside = cur.month == d.month
                if cur == d:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.ERROR_CONTAINER))
                    p.drawPath(star_path(QRectF(cell.center().x() - 17, cell.center().y() - 17, 34, 34), *STARS["cookie9"]))
                elif cur == today:
                    p.setPen(QPen(c["primary"], 1.6)); p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(cell.center(), 14, 14)
                p.setFont(card_font(13, 680 if cur == d else 480))
                p.setPen(C(T.ON_ERROR_CONTAINER) if cur == d else (c["on_surface"] if inside else QColor(255, 255, 255, 50)))
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(cur.day))
            cur += timedelta(days=1)
            if cur.weekday() == 0:
                rows += 1
        y += rows * chh + 12
        if card.actions:
            y = self.buttons(p, card.actions, pad, y, targets) + 6
        return y + pad - 4
