from datetime import date, timedelta

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPen

from circlesearch.plugins.dates import DateCard, EventCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view
from circlesearch.ui.shapes import STARS, glyph, shape_path, star_path
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


@view(EventCard)
class EventView(CardView):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        start, end = card.start, card.end
        tile = QRectF(pad, pad, 76, 84)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.container())
            p.drawPath(shape_path("squircle", tile))
        self.text(p, start.strftime("%b").upper(), tile.left(), tile.top() + 12, tile.width(), "caption",
                  self.on_container(), align="center", weight=700)
        self.text(p, str(start.day), tile.left(), tile.top() + 26, tile.width(), "headline", self.on_container(),
                  align="center")
        self.text(p, start.strftime("%a"), tile.left(), tile.top() + 60, tile.width(), "caption", self.on_container(),
                  align="center")
        tx, tw = pad + tile.width() + 16, self.inner - tile.width() - 16
        h = self.text(p, card.title, tx, pad + 2, tw, "headline", lines=2)[0]
        if card.all_day:
            when = "All day"
        else:
            when = f"{start:%H:%M} – {end:%H:%M}" + (f" (+{(end.date() - start.date()).days})" if end.date() != start.date() else "")
        h2 = self.text(p, when, tx, pad + 4 + h, tw, "subhead", self.c["primary"])[0]
        ty = pad + 4 + h + h2 + 2
        place = card.location or card.link
        if place:
            if p:
                glyph(p, "place", QRectF(tx - 1, ty + 1, 16, 16), self.c["on_surface_variant"])
            ty += self.text(p, place, tx + 20, ty, tw - 20, "body", self.c["on_surface_variant"])[0]
        y = max(tile.bottom(), ty) + T.SECTION
        chips = [Chip(card.relative, "quiet")]
        if not card.all_day:
            minutes = round((end - start).total_seconds() / 60)
            chips.append(Chip(f"{minutes // 60} h {minutes % 60} min".replace(" 0 min", "").replace("0 h ", ""), "quiet",
                              icon="clock"))
        y = self.chip_row(p, chips, y, small=True)
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)
