from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics

from circlesearch.core.text import compact
from circlesearch.plugins.software import PackageCard, RepoCard
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import C, card_font

LANGUAGE_COLORS = {"Go": "#00ADD8", "Python": "#3572A5", "Rust": "#DEA584", "C": "#A8B9CC"}


@view(RepoCard)
class RepoView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        badge = QRectF(pad - 2, y, 56, 56)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile())); p.drawPath(star_path(badge, *STARS["clover4"]))
        self.text(p, card.title.split("/")[-1][:1].upper(), 24, 700, c["on_surface"], badge.left(), badge.top() + 13, badge.width(), align="center")
        tx = badge.right() + 14
        self.text(p, card.title, 17, 620, c["on_surface"], tx, y + 6, width - (tx - pad), fit=True)
        self.text(p, card.source + " repository", 12.5, 500, c["on_surface_variant"], tx, y + 30, width - (tx - pad))
        y = badge.bottom() + 14
        if card.description:
            y += self.text(p, card.description, 14, 440, c["on_surface"], pad, y, width, lines=2)[0] + 14
        if card.stars is not None:
            n = card.stars
            shown = f"{n / 1000:.1f}K".replace(".0K", "K") if n >= 1000 else compact(n)
            sh, sw = self.text(p, shown, 52, 560, c["on_surface"], pad + 40, y - 4, width, wdth=105)
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#FBBC05"))
                p.drawPath(star_path(QRectF(pad, y + 14, 30, 30), 5, 0.5, 0.9))
            self.text(p, "stars", 14, 520, c["on_surface_variant"], pad + 40 + sw + 8, y + 28, 100)
            y += sh + 6
        x = pad
        chips = []
        if card.language:
            chips.append((card.language, LANGUAGE_COLORS.get(card.language, "#A6A9B4"), None))
        if card.release:
            chips.append((card.release, None, "tag"))
        if card.pushed:
            chips.append(("pushed " + card.pushed, None, "clock"))
        if card.open_issues is not None:
            chips.append((compact(card.open_issues) + " open issues", None, None))
        for label, dot, icon in chips:
            w = QFontMetrics(card_font(13, 560)).horizontalAdvance(label) + 24 + (22 if dot or icon else 0)
            if x + w > pad + width and x > pad:
                x, y = pad, y + 38
            x += self.pill(p, label, x, y, self.tile(), c["on_surface"], h=32, dot=dot, icon=icon) + 6
        y += 32 + 16
        if card.actions:
            y = self.buttons(p, card.actions, pad, y, targets) + 14
        return self.source(p, y, targets) + pad - 4


@view(PackageCard)
class PackageView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        self.text(p, card.registry, 15, 620, c["on_surface"], pad, y, width)
        if card.released:
            self.text(p, "released " + card.released, 12.5, 520, c["on_surface_variant"], pad, y + 2, width, align="right")
        y += 26
        vh, _ = self.text(p, card.version, 56, 540, c["on_surface"], pad, y, width, wdth=105)
        y += vh + 2
        if card.summary:
            y += self.text(p, card.summary, 14, 440, c["on_surface_variant"], pad, y, width, lines=2)[0] + 14
        r = QRectF(pad, y, width, 48)
        targets["cmd"] = (r, lambda: self.copy(card.command))
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 90)); p.drawRoundedRect(r, 16, 16)
            if self.hover == "cmd":
                p.setBrush(QColor(255, 255, 255, 14)); p.drawRoundedRect(r, 16, 16)
            mono = QFont("monospace"); mono.setPixelSize(15); p.setFont(mono)
            p.setPen(c["primary"]); p.drawText(QRectF(r.left() + 16, r.top(), 20, r.height()), Qt.AlignmentFlag.AlignVCenter, "$")
            p.setPen(c["on_surface"]); p.drawText(QRectF(r.left() + 34, r.top(), r.width() - 80, r.height()), Qt.AlignmentFlag.AlignVCenter, card.command)
            self.copy_icon(p, QRectF(r.right() - 44, r.top() + 6, 36, 36), self.hover == "cmd")
        y = r.bottom() + 12
        if card.python:
            self.pill(p, "Python " + card.python, pad, y, self.tile(), c["on_surface"], h=30, icon="code")
            y += 30 + 14
        return self.source(p, y, targets) + pad - 4
