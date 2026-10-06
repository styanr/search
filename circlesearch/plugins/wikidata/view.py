from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QFontMetrics

from circlesearch.plugins.wikidata import FactsCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.shapes import glyph
from circlesearch.ui.theme import C, type_font

GLYPHS = {"Population": "people", "Area": "area", "Elevation": "mountain", "Founded": "calendar", "Capital": "capital",
          "Currency": "coins", "Languages": "chat", "Calling code": "phone", "Developer": "person", "Latest version": "tag",
          "Licence": "tag", "Written in": "code", "First released": "calendar", "Born": "calendar", "Died": "calendar",
          "Occupation": "person", "Citizenship": "capital", "Country": "capital", "Headquarters": "capital",
          "Chief executive": "person", "Employees": "people", "Industry": "tag"}


@view(FactsCard)
class FactsView(CardView):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, card.title)
        gap, row_h = T.GAP, 70
        half = (self.inner - gap) / 2
        vf = QFontMetrics(type_font("subhead", 620))
        items = [(label, value, vf.horizontalAdvance(value) > half - 28) for label, value in card.rows]
        narrow = [it for it in items if not it[2]]
        if len(narrow) % 2:
            last = narrow[-1]; items[items.index(last)] = (last[0], last[1], True)
        tiles, pending = [], None
        for label, value, wide in items:
            if wide:
                tiles.append((QRectF(pad, y, self.inner, row_h), label, value)); y += row_h + gap
            elif pending is None:
                pending = (label, value)
            else:
                tiles.append((QRectF(pad, y, half, row_h), *pending))
                tiles.append((QRectF(pad + half + gap, y, half, row_h), label, value))
                pending = None; y += row_h + gap
        for i, (r, label, value) in enumerate(tiles):
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
                p.drawRoundedRect(r, T.RADIUS["tile"], T.RADIUS["tile"])
                glyph(p, GLYPHS.get(label, "tag"), QRectF(r.left() + 14, r.top() + 13, 14, 14), self.c["on_surface_variant"])
            self.copyable(p, targets, f"row{i}", r, value)
            self.text(p, label, r.left() + 34, r.top() + 12, r.width() - 48 - 30, "label", self.c["on_surface_variant"])
            self.text(p, value, r.left() + 14, r.top() + 34, r.width() - 28, "subhead", weight=620, fit=True)
        y += T.SECTION - gap
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)
