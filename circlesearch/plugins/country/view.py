from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QFontMetrics

from circlesearch.plugins.country import HolidaysCard, TrendsCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import C, card_font


def short(v, fmt):
    if fmt == "compact":
        for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(v) >= size:
                return f"{v / size:.1f}".rstrip("0").rstrip(".") + suffix
        return f"{v:,.0f}"
    if fmt == "usd":
        return f"${v:,.0f}"
    return f"{v:,.2f}"


def when(days):
    return "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"


@view(TrendsCard)
class TrendsView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        self.text(p, card.title, 16, 620, c["on_surface"], pad, y, width)
        y += 30
        for k, s in enumerate(card.series):
            pts = s.points
            v0, v1 = pts[0][1], pts[-1][1]
            pct = (v1 - v0) / v0 * 100
            self.text(p, s.label, 12.5, 560, c["on_surface_variant"], pad, y, width)
            y += 18
            vh, vw = self.text(p, short(v1, s.format), 26, 620, c["on_surface"], pad, y, width)
            delta = f"{'↑' if pct > 0 else '↓'} {abs(pct):.0f}% since {pts[0][0]}"
            self.pill(p, delta, pad + vw + 12, y + 3, self.tile(), c["on_surface"], h=26, px=12, weight=600)
            y += vh + 6
            plot = QRectF(pad + 2, y, width - 4, 46)
            targets[f"series{k}"] = (plot, None)
            if p:
                self.line_plot(p, pts, plot, 1)
            y = plot.bottom() + 26
        return self.source(p, y, targets) + pad - 4


@view(HolidaysCard)
class HolidaysView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        self.text(p, card.title, 16, 620, c["on_surface"], pad, y, width)
        y += 32
        first = card.holidays[0]
        badge = QRectF(pad - 2, y, 84, 84)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.ERROR_CONTAINER))
            p.drawPath(star_path(badge, *STARS["cookie9"]))
        self.text(p, f"{first.date:%-d}", 32, 680, C(T.ON_ERROR_CONTAINER), badge.left(), badge.top() + 12, badge.width(), align="center", wdth=110)
        self.text(p, f"{first.date:%b}".upper(), 11.5, 760, C(T.ON_ERROR_CONTAINER), badge.left(), badge.top() + 52, badge.width(), align="center")
        tx = badge.right() + 16; tw = width - (tx - pad)
        ty = y + 2
        ty += self.text(p, first.name, 18, 620, c["on_surface"], tx, ty, tw, lines=2)[0]
        if first.local:
            ty += self.text(p, first.local, 13, 470, c["on_surface_variant"], tx, ty, tw)[0]
        ty += 6
        self.pill(p, when(first.days), tx, ty, T.mixh(T.ERROR_CONTAINER, T.SURFACE, 0.35), C(T.ON_ERROR_CONTAINER), h=28, px=12.5, weight=620)
        y = max(badge.bottom(), ty + 28) + 14
        for h in card.holidays[1:]:
            if p:
                chip = QRectF(pad, y + 6, 62, 28)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile())); p.drawRoundedRect(chip, 8, 8)
                p.setFont(card_font(12, 620)); p.setPen(c["on_surface"]); p.drawText(chip, Qt.AlignmentFlag.AlignCenter, f"{h.date:%-d %b}")
            right = f"{h.days} d" if h.days > 1 else when(h.days)
            rw = QFontMetrics(card_font(12.5, 560)).horizontalAdvance(right)
            self.text(p, h.name, 14, 520, c["on_surface"], pad + 74, y + 10, width - 84 - rw - 10)
            self.text(p, right, 12.5, 560, c["on_surface_variant"], pad, y + 11, width, align="right")
            y += 40
        y += 10
        return self.source(p, y, targets) + pad - 4
