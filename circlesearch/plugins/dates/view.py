from datetime import date, timedelta

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPen

from circlesearch.plugins.dates import DateCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import type_font


@view(DateCard)
class DateView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        d, today = card.date, date.today()
        y = self.header(p, pad, card.title, Chip(card.relative, "container"), quiet=True)
        y += self.text(p, d.strftime("%A"), pad, y - 6, style="display", fit=True)[0] - 6
        y = self.paragraph(p, y, f"{d:%-d %B %Y}  ·  week {d.isocalendar()[1]}", lines=1, quiet=True, style="body_small")
        cw, chh = self.inner / 7, 34
        first = d.replace(day=1)
        last = first.replace(month=first.month % 12 + 1, year=first.year + (first.month == 12)) - timedelta(days=1)
        if p:
            p.setFont(type_font("caption", 620)); p.setPen(c["on_surface_variant"])
            for i, wd in enumerate("MTWTFSS"):
                p.drawText(QRectF(pad + i * cw, y, cw, 18), Qt.AlignmentFlag.AlignCenter, wd)
        y += 22
        cur, rows = first - timedelta(days=first.weekday()), 0
        while cur <= last or cur.weekday() != 0:
            cell = QRectF(pad + cur.weekday() * cw, y + rows * chh, cw, chh)
            if p:
                if cur == d:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.container())
                    p.drawPath(star_path(QRectF(cell.center().x() - 17, cell.center().y() - 17, 34, 34), *STARS["cookie9"]))
                elif cur == today:
                    p.setPen(QPen(c["primary"], 1.6)); p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(cell.center(), 14, 14)
                p.setFont(type_font("body_small", 680 if cur == d else 480))
                p.setPen(self.on_container() if cur == d else (c["on_surface"] if cur.month == d.month else QColor(255, 255, 255, 50)))
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(cur.day))
            cur += timedelta(days=1)
            if cur.weekday() == 0:
                rows += 1
        y += rows * chh + T.SECTION
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)
