from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath

from circlesearch.plugins.nearby import NearbyCard
from circlesearch.ui.cards import CardView, decode, view

WIDTHS = [172, 118, 54]


@view(NearbyCard)
class NearbyView(CardView):
    @staticmethod
    def prepare(card):
        return {"images": [decode(place.image) for place in card.places]}

    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        self.text(p, card.title, 16, 620, c["on_surface"], pad, y, width)
        y += 28
        if card.blurb:
            y += self.text(p, card.blurb, 13.5, 440, c["on_surface_variant"], pad, y, width, lines=2)[0] + 12
        shown = [(place, img) for place, img in zip(card.places, self.assets["images"]) if img is not None]
        gap, h = 8, 168
        x = pad
        for i, ((place, img), w) in enumerate(zip(shown, WIDTHS)):
            if x >= pad + width:
                break
            w = min(w, pad + width - x)
            r = QRectF(x, y, w, h)
            targets[f"item{i}"] = (r.adjusted(0, 0, 0, 44), (lambda u=place.url: self.open(u)) if place.url else None)
            if p:
                clip = QPainterPath(); clip.addRoundedRect(r, 24 if w > 60 else w / 2, 24 if w > 60 else w / 2)
                p.save(); p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                sc = max(w / img.width(), h / img.height())
                sw, sh = w / sc, h / sc
                p.drawImage(r, img, QRectF((img.width() - sw) / 2, (img.height() - sh) / 2, sw, sh))
                if self.hover == f"item{i}":
                    p.fillRect(r, QColor(255, 255, 255, 30))
                p.restore()
            if w >= 100:
                self.text(p, place.title, 13.5, 600, c["on_surface"], x + 2, y + h + 8, w - 4, lines=1)
                self.text(p, place.distance, 12, 500, c["on_surface_variant"], x + 2, y + h + 26, w - 4)
            x += w + gap
        y += h + 26 + 18 + 14
        return self.source(p, y, targets) + pad - 4
