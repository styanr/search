from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QPainterPath

from circlesearch.plugins.nearby import NearbyCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, decode, view

WIDTHS = [172, 118, 54]


@view(NearbyCard)
class NearbyView(CardView):
    @staticmethod
    def prepare(card):
        return {"images": [decode(place.image) for place in card.places]}

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, card.title)
        y = self.paragraph(p, y, card.blurb, lines=2, quiet=True, style="body_small")
        shown = [(place, img) for place, img in zip(card.places, self.assets["images"]) if img is not None]
        gap, h = T.GAP, 168
        x = pad
        for i, ((place, img), w) in enumerate(zip(shown, WIDTHS)):
            if x >= pad + self.inner:
                break
            w = min(w, pad + self.inner - x)
            r = QRectF(x, y, w, h)
            radius = T.RADIUS["media"] if w > 60 else w / 2
            name = f"item{i}"
            targets[name] = (r.adjusted(0, 0, 0, 44), lambda u=place.url: self.open(u))
            if p:
                clip = QPainterPath(); clip.addRoundedRect(r, radius, radius)
                p.save(); p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                zoom = 1 + 0.06 * max(0.0, self.fx(name).lift.value)
                sc = max(w / img.width(), h / img.height()) * zoom
                sw, sh = w / sc, h / sc
                p.drawImage(r, img, QRectF((img.width() - sw) / 2, (img.height() - sh) / 2, sw, sh))
                p.restore()
                self.state(p, r, radius, name)
            if w >= 100:
                self.text(p, place.title, x + 2, y + h + 8, w - 4, "label", weight=600)
                self.text(p, place.distance, x + 2, y + h + 26, w - 4, "caption", self.c["on_surface_variant"])
            x += w + gap
        return self.footer(p, y + h + 44 + T.SECTION, targets)
