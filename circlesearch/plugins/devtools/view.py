import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainterPath, QBrush

from circlesearch.core.cards import Action
from circlesearch.plugins.devtools import CodeCard, CronCard, ErrorCard, JwtCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, rrect, view
from circlesearch.ui.motion import MOTION, Spring, ramp, with_alpha
from circlesearch.ui.shapes import STARS, glyph, star_path
from circlesearch.ui.theme import C, type_font

MAX_LINES = 12
SCROLL_SPRING = (520, 0.92)


def mono(px=13):
    f = QFont("monospace")
    f.setStyleHint(QFont.StyleHint.TypeWriter)
    f.setPixelSize(px)
    return f


class Revealing(CardView):
    REVEAL = 0.6

    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.born = time.monotonic()

    def reveal(self, i, step=0.06, length=0.35):
        if MOTION <= 0:
            return 1.0
        t = (time.monotonic() - self.born) / MOTION - i * step
        k = ramp(t, 0.0, length)
        return 1 - (1 - k) ** 3

    def step(self, dt):
        return (time.monotonic() - self.born) / max(MOTION, 0.01) < self.REVEAL + 0.6

    def state_key(self):
        return round(min(1.0, (time.monotonic() - self.born) / max(MOTION, 0.01)), 2)


class CodeBlock:
    def __init__(self):
        self.offset = Spring(*SCROLL_SPRING)
        self.rect = QRectF()
        self.max_offset = 0

    def wheel(self, delta, pos):
        if self.max_offset <= 0 or not self.rect.contains(pos):
            return False
        target = min(self.max_offset, max(0.0, self.offset.target - delta.y() / 120 * 3))
        if target == self.offset.target:
            return False
        self.offset.set(target)
        return True

    def step(self, dt):
        return self.offset.step(dt)

    def draw(self, view, p, targets, y, code, visible=MAX_LINES, name="code"):
        f = mono()
        fm = QFontMetrics(f)
        lines = code.split("\n")
        shown = min(visible, len(lines))
        line_h = fm.lineSpacing()
        r = QRectF(view.PAD, y, view.inner, shown * line_h + 28)
        self.rect = r
        self.max_offset = max(0, len(lines) - shown)
        s = T.ICON_BUTTON - 8
        view.copyable(p, targets, name, r, code, radius=T.RADIUS["tile"], always=True,
                      icon=QRectF(r.right() - s - 8, r.top() + 8, s, s))
        if not p:
            return r.bottom() + T.SECTION
        p.save()
        clip = QPainterPath(); clip.addRoundedRect(r, T.RADIUS["tile"], T.RADIUS["tile"])
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 90)); p.drawPath(clip)
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        inner = r.adjusted(16, 14, -(s + 18), -14)
        p.setClipRect(inner.adjusted(-16, 0, s + 18, 0), Qt.ClipOperation.IntersectClip)
        p.setFont(f)
        offset = self.offset.value
        first = int(offset)
        gutter = fm.horizontalAdvance(str(len(lines))) + 12 if len(lines) > 1 else 0
        for i in range(first, min(len(lines), first + shown + 2)):
            ly = inner.top() + (i - offset) * line_h
            if gutter:
                p.setPen(QColor(255, 255, 255, 60))
                p.drawText(QRectF(inner.left(), ly, gutter - 10, line_h), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           str(i + 1))
            p.setPen(view.c["on_surface"])
            text = fm.elidedText(lines[i].replace("\t", "    "), Qt.TextElideMode.ElideRight, int(inner.width() - gutter))
            p.drawText(QPointF(inner.left() + gutter, ly + fm.ascent() + (line_h - fm.height()) / 2), text)
        if self.max_offset > 0:
            for edge, show in ((inner.top(), offset > 0.05), (inner.bottom() - 18, offset < self.max_offset - 0.05)):
                if show:
                    g = QLinearGradient(0, edge, 0, edge + 18)
                    dark = QColor(14, 15, 18, 230)
                    g.setColorAt(0.0 if edge == inner.top() else 1.0, dark)
                    g.setColorAt(1.0 if edge == inner.top() else 0.0, with_alpha(dark, 0.0))
                    p.fillRect(QRectF(r.left(), edge, r.width(), 18), QBrush(g))
            track = QRectF(r.right() - 7, r.top() + 46, 3, r.height() - 60)
            thumb_h = max(18.0, track.height() * shown / len(lines))
            ty = track.top() + (track.height() - thumb_h) * (offset / self.max_offset)
            p.setBrush(QColor(255, 255, 255, 50 + round(60 * view.fx(name).hover.value)))
            p.drawRoundedRect(QRectF(track.left(), ty, track.width(), thumb_h), 1.5, 1.5)
        p.restore()
        return r.bottom() + T.SECTION


@view(CodeCard)
class CodeView(CardView):
    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.block = CodeBlock()

    def wheel(self, delta, pos):
        return self.block.wheel(delta, pos)

    def step(self, dt):
        return self.block.step(dt)

    def state_key(self):
        return round(self.block.offset.value, 2)

    def layout(self, p, targets):
        card = self.card
        chips = [Chip(c, "quiet") for c in card.chips]
        y = self.header(p, self.PAD, card.title, chips[0] if chips else None, quiet=True)
        y = self.chip_row(p, chips[1:], y, small=True)
        y = self.paragraph(p, y, card.definition, lines=2, quiet=True, style="body_small")
        y = self.block.draw(self, p, targets, y, card.code)
        y = self.button_group(p, [Action(card.copy_label, "copy", card.code), *card.actions], y, targets)
        return self.footer(p, y, targets)


@view(JwtCard)
class JwtView(Revealing):
    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.fill = Spring(140, 0.75)
        self.fill.set(card.progress or 0.0)

    def step(self, dt):
        return self.fill.step(dt) or super().step(dt)

    def state_key(self):
        return round(self.fill.value, 3), super().state_key()

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = pad
        badge = QRectF(pad, y, 52, 52)
        tone = {"valid": T.TERTIARY_CONTAINER, "expired": T.ERROR_CONTAINER}.get(card.state, T.AMBER_CONTAINER)
        on = {"valid": T.ON_TERTIARY_CONTAINER, "expired": T.ON_ERROR_CONTAINER}.get(card.state, T.ON_AMBER_CONTAINER)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(tone))
            p.drawPath(star_path(badge, *STARS["cookie7"]))
            glyph(p, "key", badge.adjusted(14, 14, -14, -14), C(on))
        tx = pad + 64
        self.text(p, card.title, tx, y + 2, self.inner - 64, "title")
        self.text(p, card.status, tx, y + 26, self.inner - 64, "body_small", C(on) if card.state != "none" else
                  self.c["on_surface_variant"], weight=600)
        y = badge.bottom() + T.SECTION
        y = self.chip_row(p, [Chip(c, "quiet") for c in card.chips], y, small=True)
        if card.progress is not None:
            track = QRectF(pad, y, self.inner, 10)
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile())); p.drawRoundedRect(track, 5, 5)
                k = max(0.0, min(1.05, self.fill.value))
                if k > 0.001:
                    fill = QRectF(track.left(), track.top(), max(10.0, track.width() * min(1.0, k)), track.height())
                    p.setBrush(C(tone)); p.drawRoundedRect(fill, 5, 5)
                    p.setBrush(C(on)); p.drawEllipse(QPointF(fill.right() - 5, fill.center().y()), 2.5, 2.5)
            y = track.bottom() + 6
            self.text(p, "Issued", pad, y, 120, "caption", self.c["on_surface_variant"])
            self.text(p, "Expires", pad, y, self.inner, "caption", self.c["on_surface_variant"], align="right")
            y += 18 + T.SECTION
        y = self.rows(p, y, card.rows, targets)
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)


@view(CronCard)
class CronView(Revealing):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, card.expression, quiet=True)
        y += self.text(p, card.description, pad, y - 4, self.inner, "headline", lines=3)[0] + T.SECTION - 4
        n = len(card.fields)
        gap = 6
        w = (self.inner - gap * (n - 1)) / n
        for i, (label, value) in enumerate(card.fields):
            r = QRectF(pad + i * (w + gap), y, w, 54)
            star = value in ("*", "?")
            if p:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C(self.tile()) if star else self.container())
                tl = 14 if i == 0 else 6
                tr = 14 if i == n - 1 else 6
                p.drawPath(rrect(r, tl, tr, tr, tl))
                px = 15
                while px > 10 and QFontMetrics(mono(px)).horizontalAdvance(value) > r.width() - 10:
                    px -= 1
                p.setFont(mono(px)); p.setPen(self.c["on_surface_variant"] if star else self.on_container())
                fm = QFontMetrics(mono(px))
                p.drawText(QRectF(r.left(), r.top() + 6, r.width(), 24), Qt.AlignmentFlag.AlignCenter,
                           fm.elidedText(value, Qt.TextElideMode.ElideMiddle, int(r.width() - 6)))
            self.text(p, label, r.left(), r.top() + 32, r.width(), "caption",
                      self.c["on_surface_variant"] if star else self.on_container(), align="center")
        y += 54 + T.SECTION + 4
        self.text(p, "Next runs", pad, y, self.inner, "label", self.c["on_surface_variant"], weight=620)
        y += 24
        row_h = 34
        for i, run in enumerate(card.runs):
            k = self.reveal(i)
            ry = y + i * row_h + (1 - k) * 10
            dot = QPointF(pad + 8, ry + row_h / 2)
            if p:
                p.save()
                p.setOpacity(k)
                if i < len(card.runs) - 1:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 26))
                    p.drawRect(QRectF(dot.x() - 1, dot.y() + 6, 2, row_h - 12))
                p.setPen(Qt.PenStyle.NoPen)
                if i == 0:
                    p.setBrush(self.container()); p.drawPath(star_path(QRectF(dot.x() - 8, dot.y() - 8, 16, 16), *STARS["cookie6"]))
                else:
                    p.setBrush(QColor(255, 255, 255, 70)); p.drawEllipse(dot, 4, 4)
                p.restore()
            when = run.when.strftime("%a %-d %b, %H:%M")
            self.text(p, when, pad + 26, ry + 7, self.inner - 140, "body", weight=600 if i == 0 else None)
            self.text(p, run.relative, pad, ry + 9, self.inner, "body_small", self.c["on_surface_variant"], align="right")
        y += len(card.runs) * row_h + T.SECTION
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)


@view(ErrorCard)
class ErrorView(Revealing):
    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = pad
        for i, e in enumerate(card.entries):
            k = self.reveal(i, 0.08)
            if i:
                if p:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 14))
                    p.drawRect(QRectF(pad, y - T.SECTION / 2 - 1, self.inner, 1))
            size = 64
            badge = QRectF(pad, y, size, size)
            if p:
                p.save()
                p.setOpacity(k)
                c = badge.center()
                s = 0.7 + 0.3 * k
                p.translate(c); p.scale(s, s); p.rotate((1 - k) * -40); p.translate(-c)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.container())
                p.drawPath(star_path(badge, *STARS["cookie9" if i == 0 else "cookie6"]))
                p.restore()
            label = e.badge or e.code
            style = "title" if len(label) <= 4 else "label"
            line = QFontMetrics(type_font(style)).lineSpacing()
            self.text(p, label, badge.left() + 6, badge.top() + (size - line) / 2, size - 12, style, self.on_container(),
                      align="center", fit=True, weight=720)
            tx, tw = pad + size + 14, self.inner - size - 14
            h = self.text(p, e.title, tx, y + 2, tw, "title" if i else "subhead", lines=2)[0]
            cy = y + 2 + h + 2
            detail = e.code if e.code not in (e.badge, e.title) else e.family
            cy += self.text(p, detail, tx, cy, tw, "label", self.c["on_surface_variant"])[0] + 6
            if e.explanation:
                cy += self.text(p, e.explanation, tx, cy, tw, "body_small", self.c["on_surface_variant"], lines=4)[0]
            y = max(badge.bottom(), cy) + T.SECTION + 4
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)
