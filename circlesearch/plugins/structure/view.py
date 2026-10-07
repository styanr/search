from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainterPath

from circlesearch.plugins.devtools.view import SCROLL_SPRING
from circlesearch.plugins.structure import TableCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view
from circlesearch.ui.motion import Spring
from circlesearch.ui.theme import C, type_font

ROW_H = 30
VISIBLE = 8


@view(TableCard)
class TableView(CardView):
    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.offset = Spring(*SCROLL_SPRING)
        self.grid = QRectF()
        self.max_offset = 0

    def wheel(self, delta, pos):
        if self.max_offset <= 0 or not self.grid.contains(pos):
            return False
        target = min(self.max_offset, max(0.0, self.offset.target - delta.y() / 120 * 2))
        if target == self.offset.target:
            return False
        self.offset.set(target)
        return True

    def step(self, dt):
        return self.offset.step(dt)

    def state_key(self):
        return round(self.offset.value, 2)

    def widths(self, rows, total):
        fm = QFontMetrics(type_font("body_small"))
        n = max(len(r) for r in rows)
        natural = [max(fm.horizontalAdvance(r[i]) if i < len(r) else 0 for r in rows[:40]) + 20 for i in range(n)]
        floor = [min(w, 60) for w in natural]
        if sum(natural) <= total:
            extra = (total - sum(natural)) / n
            return [w + extra for w in natural]
        spare = total - sum(floor)
        want = sum(w - f for w, f in zip(natural, floor)) or 1
        return [f + (w - f) * spare / want for w, f in zip(natural, floor)]

    def row(self, p, cells, widths, x, y, i):
        if i and i % 2 == 0:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 10))
            p.drawRect(QRectF(x, y, sum(widths), ROW_H))
        f = type_font("label" if i == 0 else "body_small")
        fm = QFontMetrics(f)
        p.setFont(f)
        p.setPen(self.on_container() if i == 0 else self.c["on_surface"])
        for j, w in enumerate(widths):
            cell = cells[j] if j < len(cells) else ""
            p.drawText(QRectF(x + 10, y, w - 16, ROW_H), Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(cell, Qt.TextElideMode.ElideRight, int(w - 16)))
            x += w
        p.setPen(Qt.PenStyle.NoPen)

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        rows = card.table.rows
        y = self.header(p, pad, "Table", Chip(card.title, "quiet"), quiet=True)
        shown = min(VISIBLE, len(rows))
        self.max_offset = max(0, len(rows) - shown)
        grid = QRectF(pad, y, self.inner, shown * ROW_H)
        self.grid = grid
        if p:
            widths = self.widths(rows, grid.width())
            clip = QPainterPath(); clip.addRoundedRect(grid, T.RADIUS["tile"], T.RADIUS["tile"])
            p.save()
            p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile())); p.drawRect(grid)
            offset = self.offset.value
            first = int(offset)
            p.save()
            p.setClipRect(grid.adjusted(0, ROW_H, 0, 0), Qt.ClipOperation.IntersectClip)
            for i in range(first + 1, min(len(rows), first + shown + 2)):
                self.row(p, rows[i], widths, grid.left(), grid.top() + (i - offset) * ROW_H, i)
            p.restore()
            p.setBrush(self.container()); p.drawRect(QRectF(grid.left(), grid.top(), grid.width(), ROW_H))
            self.row(p, rows[0], widths, grid.left(), grid.top(), 0)
            x = grid.left()
            p.setBrush(QColor(255, 255, 255, 18))
            for w in widths[:-1]:
                x += w
                p.drawRect(QRectF(x, grid.top(), 1, grid.height()))
            if self.max_offset:
                track = QRectF(grid.right() - 6, grid.top() + ROW_H + 4, 3, grid.height() - ROW_H - 8)
                thumb = max(16.0, track.height() * shown / len(rows))
                ty = track.top() + (track.height() - thumb) * offset / self.max_offset
                p.setBrush(QColor(255, 255, 255, 70)); p.drawRoundedRect(QRectF(track.left(), ty, 3, thumb), 1.5, 1.5)
            p.restore()
        y = grid.bottom() + T.SECTION
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)
