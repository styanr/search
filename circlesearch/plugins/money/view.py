from PyQt6.QtCore import QRectF

from PyQt6.QtGui import QFontMetrics

from circlesearch.core.locale import current
from circlesearch.plugins.money import MoneyCard, money_str
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.theme import card_font


@view(MoneyCard)
class MoneyView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        history = card.history
        if history:
            self.text(p, card.title, 16, 620, c["on_surface"], pad, y, width)
            self.pill(p, card.unit, pad + width - QFontMetrics(card_font(12, 600)).horizontalAdvance(card.unit) - 24, y - 4,
                      self.tile(), c["on_surface_variant"], h=26, px=12, weight=600)
            y += 26
        else:
            self.text(p, card.title, 16, 560, c["on_surface_variant"], pad, y, width)
            y += 24
        vh, vw = self.text(p, card.value, 52, 520, c["on_surface"], pad, y, width - 44, rond=100, wdth=100, fit=True)
        copy = QRectF(pad + width - 40, y + (vh - 40) / 2, 40, 40)
        targets["value"] = (copy, lambda: self.copy(card.value))
        if p:
            self.copy_icon(p, copy, self.hover == "value")
        y += vh + 4
        if history:
            first, last = history[0][1], history[-1][1]
            delta = last - first
            pct = delta / first * 100
            arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
            loc = current()
            label = (f"{arrow} {money_str(abs(delta), loc.currency)}  "
                     f"({'+' if pct > 0 else ''}{loc.format_number(pct, 1)}%) in 30 days")
            self.pill(p, label, pad, y, self.tile(), c["on_surface"], h=28, px=12.5)
            y += 28 + 14
            plot = QRectF(pad + 2, y, width - 4, 64)
            if p:
                self.line_plot(p, history, plot, 0.01)
            targets["series0"] = (plot, None)
            y = plot.bottom() + 26
        x = pad
        for i, (label, value) in enumerate(card.conversions):
            text = f"{label} = {value}" if history else value
            w = QFontMetrics(card_font(13, 560)).horizontalAdvance(text) + 24
            if x + w > pad + width and x > pad:
                x, y = pad, y + 38
            x += self.pill(p, text, x, y, self.tile(), c["on_surface"], h=32, name=f"row{i}", targets=targets, payload=value) + 6
        if not history and card.rate:
            w = QFontMetrics(card_font(13, 560)).horizontalAdvance(card.rate) + 24
            if x + w > pad + width:
                x, y = pad, y + 38
            self.pill(p, card.rate, x, y, self.tile(), c["on_surface_variant"], h=32)
        y += 32 + 14
        return self.source(p, y, targets) + pad - 4
