from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath

from circlesearch.plugins.nearby import NearbyCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, decode, view
from circlesearch.ui.motion import Spring, lerp, ramp

KEYLINES = [0.0, 172.0, 118.0, 54.0, 0.0]
HEIGHT = 168
DRAG_SLOT = 130


@view(NearbyCard)
class NearbyView(CardView):
    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.scroll = Spring(360, 0.82)
        self.strip = QRectF()
        self.press_at = None
        self.dragged = False
        self.wheel_left = 0.0

    @staticmethod
    def prepare(card):
        return {"images": [decode(place.image) for place in card.places]}

    def shown(self):
        return [(place, img) for place, img in zip(self.card.places, self.assets["images"]) if img is not None]

    def limit(self):
        return max(0, len(self.shown()) - 3)

    def width_at(self, t, scale):
        t = max(-1.0, min(3.0, t)) + 1
        i = min(3, int(t))
        return lerp(KEYLINES[i], KEYLINES[i + 1], t - i) * scale

    def step(self, dt):
        return self.scroll.step(dt)

    def state_key(self):
        return round(self.scroll.value, 3)

    def wheel(self, delta, pos):
        if not self.strip.contains(pos) or self.limit() == 0:
            return False
        self.wheel_left += delta.y() if abs(delta.y()) >= abs(delta.x()) else delta.x()
        moved = False
        while abs(self.wheel_left) >= 120:
            step = -1 if self.wheel_left > 0 else 1
            self.wheel_left -= 120 * -step
            target = min(self.limit(), max(0, round(self.scroll.target) + step))
            moved = moved or target != self.scroll.target
            self.scroll.set(target)
        return moved or abs(self.wheel_left) > 0

    def press(self, pos):
        if not self.strip.contains(pos) or self.limit() == 0:
            return False
        self.press_at = (pos.x(), self.scroll.value)
        self.dragged = False
        return True

    def drag(self, pos):
        if self.press_at is None:
            return
        dx = pos.x() - self.press_at[0]
        if abs(dx) > 6:
            self.dragged = True
        if self.dragged:
            value = self.press_at[1] - dx / DRAG_SLOT
            value = min(self.limit() + 0.35, max(-0.35, value))
            self.scroll.value = self.scroll.target = value
            self.scroll.velocity = 0.0

    def release(self, pos):
        dragged = self.dragged
        if dragged:
            self.scroll.set(min(self.limit(), max(0, round(self.scroll.value))))
        self.press_at, self.dragged = None, False
        return dragged

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, card.title)
        y = self.paragraph(p, y, card.blurb, lines=2, quiet=True, style="body_small")
        shown = self.shown()
        gap = T.GAP
        scale = (self.inner - 2 * gap) / (sum(KEYLINES) or 1)
        self.strip = QRectF(pad, y, self.inner, HEIGHT + 44)
        offset = self.scroll.value
        x = pad
        if p:
            p.save()
            p.setClipRect(QRectF(pad - 1, y - 4, self.inner + 2, HEIGHT + 52))
        for i, (place, img) in enumerate(shown):
            w = self.width_at(i - offset, scale)
            if w < 0.5:
                if i - offset < 0:
                    continue
                break
            r = QRectF(x, y, w, HEIGHT)
            radius = min(T.RADIUS["media"], w / 2)
            name = f"item{i}"
            if w > 24:
                targets[name] = (r.adjusted(0, 0, 0, 44), lambda u=place.url: self.open(u))
            if p:
                clip = QPainterPath(); clip.addRoundedRect(r, radius, radius)
                p.save(); p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                zoom = 1 + 0.06 * max(0.0, self.fx(name).lift.value)
                sc = max(w / img.width(), HEIGHT / img.height()) * zoom
                sw, sh = w / sc, HEIGHT / sc
                p.drawImage(r, img, QRectF((img.width() - sw) / 2, (img.height() - sh) / 2, sw, sh))
                p.restore()
                self.state(p, r, radius, name)
                fade = ramp(w, 92, 36)
                if fade > 0.01:
                    p.save()
                    p.setOpacity(fade)
                    self.text(p, place.title, x + 2, y + HEIGHT + 8, w - 4, "label", weight=600)
                    self.text(p, place.distance, x + 2, y + HEIGHT + 26, w - 4, "caption", self.c["on_surface_variant"])
                    p.restore()
            x += w + gap * min(1.0, w / 16)
        if p:
            p.restore()
        y += HEIGHT + 44
        if len(shown) > 3:
            dots = []
            for i in range(self.limit() + 1):
                near = max(0.0, 1 - abs(i - offset))
                dots.append((6 + 16 * near, near))
            total = sum(w for w, _ in dots) + 5 * (len(dots) - 1)
            dx = pad + (self.inner - total) / 2
            if p:
                p.setPen(Qt.PenStyle.NoPen)
                for w, near in dots:
                    p.setBrush(QColor(255, 255, 255, round(60 + 140 * near)))
                    p.drawRoundedRect(QRectF(dx, y + 2, w, 6), 3, 3)
                    dx += w + 5
            y += 14
        return self.footer(p, y + T.SECTION, targets)
