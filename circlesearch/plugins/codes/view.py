import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFontMetrics, QPen

from circlesearch.core.cards import Action
from circlesearch.plugins.codes import OtpCard, WifiCard
from circlesearch.plugins.devtools.view import mono
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view
from circlesearch.ui.motion import MOTION, Spring, mix, ramp
from circlesearch.ui.shapes import STARS, glyph, star_path
from circlesearch.ui.theme import C, type_font


def badge(view, p, rect, name, shape="cookie9"):
    if p:
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(view.container())
        p.drawPath(star_path(rect, *STARS[shape]))
        inset = rect.width() * 0.27
        glyph(p, name, rect.adjusted(inset, inset, -inset, -inset), view.on_container())


@view(WifiCard)
class WifiView(CardView):
    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.shown = Spring(420, 0.72)

    def toggle(self):
        self.shown.set(0.0 if self.shown.target else 1.0)

    def step(self, dt):
        return self.shown.step(dt)

    def state_key(self):
        return round(self.shown.value, 3)

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        b = QRectF(pad - 2, pad, 64, 64)
        badge(self, p, b, "wifi")
        tx = pad + 76
        self.text(p, card.ssid or "Hidden network", tx, pad + 14, self.inner - 76, "headline", fit=True)
        y = b.bottom() + T.SECTION
        y = self.chip_row(p, [Chip(card.security, "quiet", icon="shield"),
                              *([Chip("hidden", "quiet")] if card.hidden else [])], y, small=True)
        if card.password:
            tile = QRectF(pad, y, self.inner, 64)
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
                p.drawRoundedRect(tile, T.RADIUS["tile"], T.RADIUS["tile"])
            s = T.ICON_BUTTON - 8
            copy = QRectF(tile.right() - s - 10, tile.center().y() - s / 2, s, s)
            eye = QRectF(copy.left() - s - 4, copy.top(), s, s)
            self.copyable(p, targets, "password", QRectF(copy), card.password, radius=s / 2, always=True, icon=copy)
            targets["reveal"] = (eye, self.toggle)
            k = max(0.0, min(1.0, self.shown.value))
            if p:
                self.state(p, eye, s / 2, "reveal")
                p.save()
                self.squeezed(p, eye, "reveal", 0.12)
                color = mix(self.c["on_surface_variant"], self.c["primary"], k)
                glyph(p, "eye", eye.adjusted(6, 6, -6, -6), color)
                if k < 0.5:
                    p.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    reach = 1 - k * 2
                    p.drawLine(QPointF(eye.left() + 8, eye.top() + 8),
                               QPointF(eye.left() + 8 + (s - 16) * reach, eye.top() + 8 + (s - 16) * reach))
                p.restore()
            self.text(p, "Password", tile.left() + 16, tile.top() + 10, 200, "caption", self.c["on_surface_variant"],
                      weight=620)
            if p:
                width = eye.left() - tile.left() - 24
                p.save()
                p.setClipRect(QRectF(tile.left() + 10, tile.top(), width + 6, tile.height()))
                p.setFont(mono(16))
                fm = QFontMetrics(mono(16))
                base = tile.top() + 48
                p.setOpacity(1 - k)
                p.setPen(self.c["on_surface"])
                p.drawText(QPointF(tile.left() + 16, base - 8 * k), "•" * min(16, max(8, len(card.password))))
                p.setOpacity(k)
                p.drawText(QPointF(tile.left() + 16, base + 8 * (1 - k)),
                           fm.elidedText(card.password, Qt.TextElideMode.ElideRight, int(width)))
                p.restore()
            y = tile.bottom() + T.SECTION
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)


@view(OtpCard)
class OtpView(CardView):
    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.code = card.code()
        self.previous = self.code
        self.changed = 0.0

    def step(self, dt):
        code = self.card.code()
        if code != self.code:
            self.previous, self.code, self.changed = self.code, code, time.monotonic()
        return True

    def state_key(self):
        return time.monotonic()

    def digits(self, p, x, y, code, previous, h):
        f = type_font("display", 560)
        fm = QFontMetrics(f)
        p.setFont(f)
        cx = x
        since = (time.monotonic() - self.changed) / max(MOTION, 0.01)
        for i, ch in enumerate(code):
            if i and i == len(code) // 2:
                cx += 14
            w = fm.horizontalAdvance("0")
            old = previous[i] if i < len(previous) else ch
            k = ramp(since, i * 0.04, 0.32)
            k = 1 - (1 - k) ** 3
            p.save()
            p.setClipRect(QRectF(cx - 2, y, w + 4, h))
            p.setPen(self.c["on_surface"])
            if old != ch and k < 1:
                p.setOpacity(1 - k)
                p.drawText(QPointF(cx, y + fm.ascent() - h * 0.7 * k), old)
                p.setOpacity(k)
                p.drawText(QPointF(cx, y + fm.ascent() + h * 0.7 * (1 - k)), ch)
            else:
                p.drawText(QPointF(cx, y + fm.ascent()), ch)
            p.restore()
            cx += w + 2
        return cx - x

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        b = QRectF(pad - 2, pad, 56, 56)
        badge(self, p, b, "key", "cookie7")
        tx = pad + 68
        self.text(p, card.issuer or "One-time code", tx, pad + 4, self.inner - 68, "title")
        self.text(p, card.account, tx, pad + 28, self.inner - 68, "body_small", self.c["on_surface_variant"])
        y = b.bottom() + T.SECTION
        f = type_font("display", 560)
        h = QFontMetrics(f).height()
        zone = QRectF(pad - 8, y - 4, self.inner + 16, h + 8)
        self.copyable(p, targets, "value", zone, self.code, radius=T.RADIUS["tile"])
        if p:
            self.digits(p, pad, y, self.code, self.previous, h)
        if card.counter is None:
            now = time.time()
            left = card.period - now % card.period
            ring = QRectF(pad + self.inner - 52, y + (h - 48) / 2, 48, 48)
            if p:
                urgent = left < 6
                color = C(T.ON_ERROR_CONTAINER) if urgent else self.on_container()
                track = C(T.ERROR_CONTAINER) if urgent else self.container()
                p.save()
                p.setPen(QPen(track, 6)); p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(ring.adjusted(3, 3, -3, -3))
                p.setPen(QPen(color, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawArc(ring.adjusted(3, 3, -3, -3), 90 * 16, round(360 * 16 * left / card.period))
                p.setFont(type_font("label", 700)); p.setPen(self.c["on_surface"])
                p.drawText(ring, Qt.AlignmentFlag.AlignCenter, str(int(left) + 1 if left % 1 else int(left)))
                p.restore()
        y += h + T.SECTION
        chips = [Chip(f"{card.digits} digits", "quiet"), Chip(card.algorithm, "quiet"),
                 Chip(f"every {card.period} s" if card.counter is None else f"counter {card.counter}", "quiet",
                      icon="clock")]
        y = self.chip_row(p, chips, y, small=True)
        actions = [Action("Copy code", "copy", self.code), Action("Copy secret", "copy", card.secret)]
        y = self.button_group(p, actions, y, targets)
        return self.footer(p, y, targets)
