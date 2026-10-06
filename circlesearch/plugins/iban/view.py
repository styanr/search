from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFontMetrics

from circlesearch.plugins.devtools.view import mono
from circlesearch.plugins.iban import IbanCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.effects import draw_check
from circlesearch.ui.shapes import STARS, glyph, star_path
from circlesearch.ui.theme import C


@view(IbanCard)
class IbanView(CardView):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, "IBAN", quiet=True)
        box = QRectF(pad, y, self.inner, 64)
        px = 22
        while px > 13 and QFontMetrics(mono(px)).horizontalAdvance(card.title) > box.width() - 70:
            px -= 1
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
            p.drawRoundedRect(box, T.RADIUS["tile"], T.RADIUS["tile"])
            p.setFont(mono(px)); p.setPen(self.c["on_surface"])
            p.drawText(QRectF(box.left() + 16, box.top(), box.width() - 60, box.height()), Qt.AlignmentFlag.AlignVCenter,
                       card.title)
        s = T.ICON_BUTTON - 8
        self.copyable(p, targets, "value", box, card.iban, always=True,
                      icon=QRectF(box.right() - s - 10, box.center().y() - s / 2, s, s))
        y = box.bottom() + 12
        tone, on = (T.TERTIARY_CONTAINER, T.ON_TERTIARY_CONTAINER) if card.valid else (T.ERROR_CONTAINER, T.ON_ERROR_CONTAINER)
        badge = QRectF(pad, y, 28, 28)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(tone)); p.drawPath(star_path(badge, *STARS["cookie9"]))
            if card.valid:
                draw_check(p, badge.center(), 1.0, C(on), size=5.5)
            else:
                glyph(p, "close", badge.adjusted(8, 8, -8, -8), C(on))
        h = self.text(p, card.status, pad + 38, y + 4, self.inner - 38, "body_small", C(on) if not card.valid
                      else self.c["on_surface"], lines=2, weight=560)[0]
        y = max(badge.bottom(), y + 4 + h) + T.SECTION
        if card.suggestion:
            tile = QRectF(pad, y, self.inner, 62)
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.container())
                p.drawRoundedRect(tile, T.RADIUS["tile"], T.RADIUS["tile"])
            self.copyable(p, targets, "suggestion", tile, card.suggestion.replace(" ", ""), always=True,
                          ink=self.on_container(), icon=QRectF(tile.right() - s - 10, tile.center().y() - s / 2, s, s))
            self.text(p, "Corrected", tile.left() + 16, tile.top() + 10, tile.width() - 70, "caption",
                      self.on_container(), weight=620)
            if p:
                p.setFont(mono(15)); p.setPen(self.on_container())
                p.drawText(QPointF(tile.left() + 16, tile.top() + 48), card.suggestion)
            y = tile.bottom() + T.SECTION
        y = self.rows(p, y, card.rows, targets)
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)
