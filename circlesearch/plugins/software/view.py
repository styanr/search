from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont

from circlesearch.core.locale import current
from circlesearch.plugins.software import PackageCard, RepoCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view
from circlesearch.ui.shapes import star_path
from circlesearch.ui.theme import C

LANGUAGE_COLORS = {"Go": "#00ADD8", "Python": "#3572A5", "Rust": "#DEA584", "C": "#A8B9CC", "JavaScript": "#F1E05A",
                   "TypeScript": "#3178C6"}


@view(RepoCard)
class RepoView(CardView):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        loc = current()
        y = self.header(p, pad, card.title)
        y = self.paragraph(p, y, card.description, lines=2)
        if card.stars is not None:
            stars = loc.format_compact(card.stars)
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.YELLOW))
                p.drawPath(star_path(QRectF(pad, y + 18, 30, 30), 5, 0.5, 0.9))
            h, w = self.text(p, stars, pad + 40, y, style="display")
            self.text(p, "stars", pad + 40 + w + 8, y + h - 34, 100, "body", self.c["on_surface_variant"])
            y += h + 4
        chips = []
        if card.language:
            chips.append(Chip(card.language, dot=LANGUAGE_COLORS.get(card.language, T.ON_VAR)))
        if card.release:
            chips.append(Chip(card.release, icon="tag"))
        if card.pushed:
            chips.append(Chip("pushed " + card.pushed, icon="clock"))
        if card.open_issues is not None:
            chips.append(Chip(loc.format_compact(card.open_issues) + " open issues"))
        y = self.chip_row(p, chips, y)
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)


@view(PackageCard)
class PackageView(CardView):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, card.title, Chip(card.released, "quiet", icon="clock") if card.released else None)
        y = self.big_value(p, y - 6, card.version, targets, copy=False)
        y = self.paragraph(p, y, card.summary, lines=2, quiet=True)
        r = QRectF(pad, y, self.inner, 48)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 90))
            p.drawRoundedRect(r, T.RADIUS["tile"], T.RADIUS["tile"])
        s = T.ICON_BUTTON
        self.copyable(p, targets, "command", r, card.command, always=True,
                      icon=QRectF(r.right() - s - 6, r.top() + (r.height() - s) / 2, s, s))
        if p:
            mono = QFont("monospace"); mono.setPixelSize(15); p.setFont(mono)
            p.setPen(self.c["primary"]); p.drawText(QRectF(r.left() + 16, r.top(), 20, r.height()), Qt.AlignmentFlag.AlignVCenter, "$")
            p.setPen(self.c["on_surface"])
            p.drawText(QRectF(r.left() + 34, r.top(), r.width() - 80, r.height()), Qt.AlignmentFlag.AlignVCenter, card.command)
        y = r.bottom() + T.SECTION
        if card.python:
            y = self.chip_row(p, [Chip("Python " + card.python, icon="code")], y)
        return self.footer(p, y, targets)
