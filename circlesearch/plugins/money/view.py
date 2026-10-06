from PyQt6.QtCore import QRectF

from circlesearch.core.locale import current
from circlesearch.plugins.money import MoneyCard, money_str
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view


@view(MoneyCard)
class MoneyView(CardView):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        history = card.history
        y = self.header(p, pad, card.title, Chip(card.unit, "quiet") if card.unit else None, quiet=not history)
        y = self.big_value(p, y, card.value, targets)
        if history:
            first, last = history[0][1], history[-1][1]
            delta = last - first
            pct = delta / first * 100
            arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
            loc = current()
            label = (f"{arrow} {money_str(abs(delta), loc.currency)}  "
                     f"({'+' if pct > 0 else ''}{loc.format_number(pct, 1)}%) in 30 days")
            y = self.chip_row(p, [Chip(label)], y)
            plot = QRectF(pad + 2, y, self.inner - 4, 64)
            if p:
                self.line_plot(p, history, plot, 0.01)
            y = plot.bottom() + 18 + T.SECTION
        chips = [Chip(f"{label} = {value}" if history else value, payload=value) for label, value in card.conversions]
        if card.rate:
            chips.append(Chip(card.rate, "quiet"))
        y = self.chip_row(p, chips, y, targets)
        return self.footer(p, y, targets)
