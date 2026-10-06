from PyQt6.QtCore import QRectF, Qt

from circlesearch.core.locale import current
from circlesearch.plugins.country import HolidaysCard, TrendsCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import C, type_font


def short(v, fmt):
    loc = current()
    if fmt == "compact":
        return loc.format_compact(v)
    if fmt == "usd":
        return loc.format_money(v, "$", 0)
    return loc.format_number(v, 2)


def when(days):
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"


@view(TrendsCard)
class TrendsView(CardView):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, card.title)
        for s in card.series:
            pts = s.points
            v0, v1 = pts[0][1], pts[-1][1]
            pct = (v1 - v0) / v0 * 100
            y += self.text(p, s.label, pad, y, style="label", color=self.c["on_surface_variant"])[0] + 2
            vh, vw = self.text(p, short(v1, s.format), pad, y, style="headline")
            delta = f"{'↑' if pct > 0 else '↓'} {current().format_number(abs(pct), 0)}% since {pts[0][0]}"
            self.chip(p, Chip(delta), pad + vw + 12, y + (vh - T.CHIP_SMALL_H) / 2, small=True)
            y += vh + 6
            plot = QRectF(pad + 2, y, self.inner - 4, 46)
            if p:
                self.line_plot(p, pts, plot, 1)
            y = plot.bottom() + 18 + T.SECTION
        return self.footer(p, y, targets)


@view(HolidaysCard)
class HolidaysView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        y = self.header(p, pad, card.title)
        first = card.holidays[0]
        badge = QRectF(pad - 2, y, 84, 84)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.container())
            p.drawPath(star_path(badge, *STARS["cookie9"]))
        self.text(p, f"{first.date:%-d}", badge.left(), badge.top() + 14, badge.width(), "headline",
                  self.on_container(), align="center", weight=680)
        self.text(p, f"{first.date:%b}".upper(), badge.left(), badge.top() + 50, badge.width(), "caption",
                  self.on_container(), align="center", weight=760)
        tx = badge.right() + 16
        tw = self.inner - (tx - pad)
        ty = y + 2
        ty += self.text(p, first.name, tx, ty, tw, "subhead", weight=620, lines=2)[0]
        if first.local:
            ty += self.text(p, first.local, tx, ty, tw, "body_small", c["on_surface_variant"])[0]
        ty += 6
        self.chip(p, Chip(when(first.days), "container"), tx, ty, small=True)
        y = max(badge.bottom(), ty + T.CHIP_SMALL_H) + T.SECTION
        for h in card.holidays[1:]:
            if p:
                chip = QRectF(pad, y + 6, 62, 28)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
                p.drawRoundedRect(chip, T.RADIUS["chip"], T.RADIUS["chip"])
                p.setFont(type_font("label", 620)); p.setPen(c["on_surface"])
                p.drawText(chip, Qt.AlignmentFlag.AlignCenter, f"{h.date:%-d %b}")
            right = f"{h.days} d" if h.days > 1 else when(h.days)
            rw = self.measure(right, "label")
            self.text(p, h.name, pad + 74, y + 10, self.inner - 84 - rw - 10, "body", weight=520)
            self.text(p, right, pad, y + 11, self.inner, "label", c["on_surface_variant"], align="right")
            y += 40
        return self.footer(p, y + T.SECTION - 4, targets)
