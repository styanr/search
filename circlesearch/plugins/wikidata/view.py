from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics

from circlesearch.plugins.wikidata import FactsCard
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.shapes import glyph
from circlesearch.ui.theme import C, card_font

GLYPHS = {"Population": "people", "Area": "area", "Elevation": "mountain", "Founded": "calendar", "Capital": "capital",
          "Currency": "coins", "Languages": "chat", "Calling code": "phone", "Developer": "person", "Latest version": "tag",
          "Licence": "tag", "Written in": "code", "First released": "calendar", "Born": "calendar", "Died": "calendar",
          "Occupation": "person", "Citizenship": "capital", "Country": "capital", "Headquarters": "capital",
          "Chief executive": "person", "Employees": "people", "Industry": "tag"}


@view(FactsCard)
class FactsView(CardView):
    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        self.text(p, card.title, 16, 620, c["on_surface"], pad, y, width)
        self.text(p, card.source, 11.5, 520, c["on_surface_variant"], pad, y + 3, width, align="right")
        if card.url:
            targets["source"] = (QRectF(pad + width - 70, y, 70, 20), lambda: self.open(card.url))
        y += 32
        gap = 8
        half = (width - gap) / 2
        vf = QFontMetrics(card_font(19, 620))
        row_h = 70
        items = [(label, value, vf.horizontalAdvance(value) > half - 28) for label, value in card.rows]
        narrow = [it for it in items if not it[2]]
        if len(narrow) % 2:
            last = narrow[-1]; items[items.index(last)] = (last[0], last[1], True)
        tiles, pending = [], None
        for label, value, wide in items:
            if wide:
                tiles.append((QRectF(pad, y, width, row_h), label, value)); y += row_h + gap
            elif pending is None:
                pending = (label, value)
            else:
                tiles.append((QRectF(pad, y, half, row_h), *pending)); tiles.append((QRectF(pad + half + gap, y, half, row_h), label, value))
                pending = None; y += row_h + gap
        bottom = y - gap
        for i, (r, label, value) in enumerate(tiles):
            name = f"row{i}"
            targets[name] = (r, lambda v=value: self.copy(v))
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
                p.drawRoundedRect(r, 16, 16)
                if self.hover == name:
                    p.setBrush(QColor(255, 255, 255, 14)); p.drawRoundedRect(r, 16, 16)
                glyph(p, GLYPHS.get(label, "tag"), QRectF(r.left() + 14, r.top() + 13, 14, 14), c["on_surface_variant"])
            self.text(p, label, 12, 540, c["on_surface_variant"], r.left() + 34, r.top() + 12, r.width() - 48)
            self.text(p, value, 19, 620, c["on_surface"], r.left() + 14, r.top() + 34, r.width() - 28, fit=True)
        y = bottom + 14
        if card.actions:
            y = self.buttons(p, card.actions, pad, y, targets) + 6
        return y + pad - 6
