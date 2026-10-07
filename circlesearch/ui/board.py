from PyQt6 import sip
from PyQt6.QtCore import QPointF, QRect, QRectF, QTimer
from PyQt6.QtWidgets import QGraphicsOpacityEffect

from circlesearch.core import settings
from circlesearch.ui.motion import AMBIENT, CARD_SPRING, MOTION, Tween, lerp
from circlesearch.ui.theme import PALETTE

MAX_CARDS = 5
MAX_TEXT = 8000
BALANCE = 160
BATCH_MS = 250
GAP = 12


def shadow_rect(widget):
    return QRectF(widget.geometry()).adjusted(-48, -40, 48, 64).toAlignedRect()


class CardBoard:
    def __init__(self, host, on_copy, on_open, on_pin=None, on_save=None, on_run=None, on_arrive=None):
        self.host, self.on_copy, self.on_open = host, on_copy, on_open
        self.on_pin, self.on_save, self.on_run, self.on_arrive = on_pin, on_save, on_run, on_arrive
        self.cards = []
        self.busy = False
        self._col = {}
        self._cols = None
        self._pending = []
        self._anims = {}
        self._stagger = {}
        self.feed = None
        self._text = None
        self._token = None

    def request(self, text, words=None, route=None):
        text = text.strip()
        key = ("route", route.kind, route.text) if route is not None else text
        if key == self._text:
            return
        self.clear()
        self._text = key
        if not settings.CARDS or (route is None and (not text or len(text) > MAX_TEXT)):
            return
        if self.feed is None:
            from circlesearch.ui.feed import CardFeed
            self.feed = CardFeed(self.host)
            self.feed.routed.connect(self._routed)
            self.feed.ready.connect(self._ready)
            self.feed.extra.connect(self._extra)
        self._token = self.feed.start(text, words, route)
        self.busy = True

    @property
    def text(self):
        return self._text if isinstance(self._text, str) else None

    def clear(self, keep_request=False):
        for card in self.cards:
            if card.isVisible():
                self.host.update(shadow_rect(card))
            card.hide()
            card.deleteLater()
        self.cards = []
        self._col = {}
        self._cols = None
        self._pending = []
        self._anims.clear()
        self._stagger.clear()
        self.busy = False
        if not keep_request:
            if self.feed is not None:
                self.feed.cancel()
            self._token = None
            self._text = None

    def columns(self):
        bar, _ = self.host.card_anchor()
        cols = 2 if bar.width() >= 2 * 360 + GAP else 1
        return cols, (bar.width() - GAP * (cols - 1)) / cols

    def _new_card(self, role="secondary"):
        from circlesearch.ui.cards import CardWidget
        _, width = self.columns()
        card = CardWidget(self.host, PALETTE, ambient=AMBIENT, width=round(width), role=role,
                          pinnable=self.on_pin is not None)
        card.pane_alpha = self.host.pane_alpha
        card.hide()
        card.copyRequested.connect(self.on_copy)
        card.openRequested.connect(self.on_open)
        if self.on_pin:
            card.pinRequested.connect(self.on_pin)
        if self.on_save:
            card.saveRequested.connect(self.on_save)
        if self.on_run:
            card.runRequested.connect(self.on_run)
        return card

    def _routed(self, token, route, placeholder):
        if token == self._token and self.host.cards_wanted() and placeholder:
            card = self._new_card("hero")
            card.set_loading()
            self.cards = [card]
            self._col = {card: 0}
            self.layout()

    def _ready(self, token, info, assets):
        if token != self._token or not self.host.cards_wanted():
            return
        if info is None:
            self.clear(keep_request=True)
            return
        if not self.cards:
            self.cards = [self._new_card("hero")]
            self._col = {self.cards[0]: 0}
        self.cards[0].set_card(info, assets)
        self.layout()
        if self.busy and self.on_arrive is not None:
            self.on_arrive(self.cards[0])
        self.busy = False

    def _extra(self, token, info, assets):
        if token != self._token or not self.host.cards_wanted() or not self.cards:
            return
        self._pending.append((info, assets))
        if len(self._pending) == 1:
            QTimer.singleShot(BATCH_MS, lambda t=token: self._flush(t))

    def _flush(self, token):
        pending = sorted(self._pending, key=lambda p: p[0].priority)
        self._pending = []
        if token != self._token or not self.cards or not self.host.cards_wanted():
            return
        for k, (info, assets) in enumerate(pending):
            if len(self.cards) >= MAX_CARDS:
                break
            card = self._new_card()
            card.set_card(info, assets)
            self._stagger[card] = k * 0.04
            self.cards.append(card)
        self.layout()

    def _plan(self, cols):
        if self._cols != cols:
            self._col, self._cols = {}, cols
        col_of = self._col
        heights, spots = [0.0] * cols, {}
        for card in self.cards:
            if card not in col_of:
                shortest = min(range(cols), key=lambda c: heights[c])
                if card is self.cards[0]:
                    col_of[card] = 0
                elif card.card is not None and card.card.anchored and heights[0] <= min(heights) + BALANCE:
                    col_of[card] = 0
                else:
                    col_of[card] = shortest
            c = col_of[card]
            spots[card] = (c, heights[c])
            heights[c] += card.layout_height() + GAP
        return spots, heights

    def _options(self, colw):
        bar, sel = self.host.card_anchor()
        usable = self.host.width() - 32
        max_cols = max(1, int((usable + GAP) // (colw + GAP)))
        first = min(2, max_cols)
        sides = ["below", "above"] if bar.top() >= sel.center().y() else ["above", "below"]
        for side in sides:
            for cols in range(first, max_cols + 1):
                yield side, cols
        for side in ("right", "left"):
            for cols in range(1, max_cols + 1):
                yield side, cols

    def _rect(self, side, cols, colw, height):
        bar, sel = self.host.card_anchor()
        sel = sel.adjusted(-4, -4, 4, 4)
        block = bar.united(sel)
        width = cols * colw + (cols - 1) * GAP
        screen = QRectF(16, 16, self.host.width() - 32, self.host.height() - 32)
        if side in ("below", "above"):
            x = min(max(screen.left(), bar.left()), screen.right() - width)
            y = max(bar.bottom(), sel.bottom()) + GAP if side == "below" else min(bar.top(), sel.top()) - GAP - height
        else:
            x = block.right() + GAP + 4 if side == "right" else block.left() - GAP - 4 - width
            y = min(max(screen.top(), block.top()), screen.bottom() - height)
        rect = QRectF(x, y, width, height)
        if not screen.contains(rect) or rect.intersects(sel) or rect.intersects(bar):
            return None
        return rect

    def layout(self):
        _, colw = self.columns()
        while True:
            choice = None
            for side, cols in self._options(colw):
                spots, heights = self._plan(cols)
                rect = self._rect(side, cols, colw, max(heights) - GAP)
                if rect is not None:
                    choice = (side, cols, spots, heights, rect)
                    break
            if choice or len(self.cards) <= 1:
                break
            victim = max(self.cards[1:], key=lambda c: c.card.priority if c.card else 9)
            self.cards.remove(victim)
            self._col.pop(victim, None)
            self._anims.pop(victim, None)
            if victim.isVisible():
                self.host.update(shadow_rect(victim))
            victim.hide()
            victim.deleteLater()
        if choice is None:
            spots, heights = self._plan(1)
            bar, _ = self.host.card_anchor()
            choice = ("below", 1, spots, heights,
                      QRectF(bar.left(), min(bar.bottom() + GAP, self.host.height() - 16 - heights[0]), colw, heights[0]))
        side, cols, spots, heights, rect = choice
        for card in self.cards:
            c, offset = spots[card]
            x = rect.left() + c * (colw + GAP)
            y = rect.bottom() - offset - card.layout_height() if side == "above" else rect.top() + offset
            target = QPointF(x, y)
            if card.isVisible():
                if (target - QPointF(card.pos())).manhattanLength() > 1:
                    self._anims[card] = (QPointF(card.pos()), target, Tween(0.5, CARD_SPRING))
                self.host.update(shadow_rect(card))
                continue
            offset_in = {"below": QPointF(0, -18), "above": QPointF(0, 18), "right": QPointF(-18, 0), "left": QPointF(18, 0)}[side]
            start = target + offset_in
            tween = Tween(0.5, CARD_SPRING)
            tween.start += self._stagger.get(card, 0.0) * MOTION
            self._anims[card] = (start, target, tween)
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.0)
            card.setGraphicsEffect(effect)
            card.move(start.toPoint())
            card.show()
            self.host.stack_card(card)

    def step(self, now):
        for card, (start, end, t) in list(self._anims.items()):
            if sip.isdeleted(card):
                del self._anims[card]
                continue
            old = shadow_rect(card)
            card.move(QPointF(lerp(start.x(), end.x(), t.value(now)), lerp(start.y(), end.y(), t.value(now))).toPoint())
            effect = card.graphicsEffect()
            if effect is not None:
                effect.setOpacity(min(1.0, t.raw(now) * 3))
            self.host.update(old.united(shadow_rect(card)))
            if t.done(now):
                del self._anims[card]
                card.setGraphicsEffect(None)
        for card in self.cards:
            if card.transitioning():
                grown = QRect(card.x(), card.y(), card.width(), card.layout_height())
                self.host.update(grown.adjusted(-48, -40, 48, 64))
