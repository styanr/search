from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath

from circlesearch.core.cards import Card, HeroCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, decode, view
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import C, type_font

MAP_TINT = QColor("#9DB4E0")


@view(Card)
class TextView(CardView):
    def layout(self, p, targets):
        card = self.card
        role = getattr(card, "title_role", "name")
        y = self.PAD
        if role == "name":
            y = self.title(p, y)
        else:
            y = self.header(p, y, card.title, quiet=True, lines=3 if role == "passage" else 2)
        y = self.chip_row(p, [Chip(s, "quiet") for s in (getattr(card, "part_of_speech", ""),
                                                          getattr(card, "description", ""),
                                                          *getattr(card, "chips", [])) if s], y, small=True)
        if role != "passage":
            y = self.paragraph(p, y, getattr(card, "definition", ""))
        if getattr(card, "value", ""):
            y = self.big_value(p, y, card.value, targets)
        y = self.rows(p, y, getattr(card, "rows", []), targets)
        if getattr(card, "translation", ""):
            y = self.translation(p, y, targets, role == "passage")
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)

    def title(self, p, y):
        card = self.card
        h, w = self.text(p, card.title, self.PAD, y, style="headline", lines=2)
        pronunciation = getattr(card, "pronunciation", "")
        if pronunciation:
            pw = self.measure(pronunciation, "body")
            line = QFontMetrics(type_font("headline")).lineSpacing()
            if h <= line and w + 12 + pw <= self.inner:
                ascent = QFontMetrics(type_font("headline")).ascent() - QFontMetrics(type_font("body")).ascent()
                self.text(p, pronunciation, self.PAD + w + 12, y + ascent, pw + 2, "body", self.c["on_surface_variant"])
            else:
                h += self.text(p, pronunciation, self.PAD, y + h, style="body", color=self.c["on_surface_variant"])[0]
        return y + h + T.GAP

    def translation(self, p, y, targets, passage):
        card = self.card
        alternatives = getattr(card, "alternatives", [])
        icon = T.ICON_BUTTON - 8
        x, width = self.PAD + 14, self.inner - 28 - icon
        lines = 6 if passage else 2
        label_h = self.text(None, card.translation_label, x, 0, width, "caption")[0]
        text_h = self.text(None, card.translation, x, 0, width, "subhead", lines=lines)[0]
        alt_h = self.text(None, ", ".join(alternatives), x, 0, width, "body_small")[0] if alternatives else 0
        box = QRectF(self.PAD, y, self.inner, 14 + label_h + 4 + text_h + (4 + alt_h if alt_h else 0) + 14)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
            p.drawRoundedRect(box, T.RADIUS["tile"], T.RADIUS["tile"])
        self.copyable(p, targets, "translation", box, card.translation, always=True)
        ty = y + 14
        ty += self.text(p, card.translation_label, x, ty, width, "caption", self.c["primary"], weight=600)[0] + 4
        ty += self.text(p, card.translation, x, ty, width, "subhead", lines=lines)[0]
        if alternatives:
            self.text(p, ", ".join(alternatives), x, ty + 4, width, "body_small", self.c["on_surface_variant"])
        return box.bottom() + T.SECTION


def dark_tile(data):
    tile = QImage()
    tile.loadFromData(data)
    tile = tile.convertToFormat(QImage.Format.Format_Grayscale8)
    tile.invertPixels()
    tile = tile.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(tile)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    p.fillRect(tile.rect(), MAP_TINT)
    p.end()
    return tile


def render_map(tiles):
    img = QImage(tiles.width, tiles.height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(T.SURFACE))
    p = QPainter(img)
    for x, y, data in tiles.tiles:
        p.drawImage(QPointF(x, y), dark_tile(data))
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QPointF(tiles.width / 2, tiles.height / 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(168, 199, 250, 60))
    p.drawEllipse(c, 18, 18)
    p.setBrush(QColor("white"))
    p.drawEllipse(c, 8, 8)
    p.setBrush(QColor("#4285F4"))
    p.drawEllipse(c, 5.5, 5.5)
    p.end()
    return img


@view(HeroCard)
class HeroView(CardView):
    loader_grows = True

    @staticmethod
    def prepare(card):
        return {"image": decode(card.image), "map": render_map(card.map) if card.map else None}

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y, media = pad, 92
        img = self.assets.get("image")
        shape = card.image_shape or "cookie9"
        if p and img is not None:
            p.drawImage(QPointF(pad - 2, y), self.shaped(img, shape, media, cover=shape != "logo_squircle"))
        elif p:
            r = QRectF(pad - 2, y, media, media)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.container()); p.drawPath(star_path(r, *STARS["cookie9"]))
            self.text(p, card.title[:1].upper(), r.left(), r.top() + 22, r.width(), "headline", self.on_container(),
                      align="center")
        tx = pad + media + 16
        tw = self.inner - media - 16
        ty = y + 4
        ty += self.text(p, card.title, tx, ty, tw, "headline", lines=2)[0] + 2
        if card.translation:
            h, w = self.text(p, card.translation, tx, ty, tw, "subhead", self.c["primary"])
            s = T.ICON_BUTTON - 8
            self.copyable(p, targets, "translation", QRectF(tx - 6, ty - 2, w + s + 14, h + 4), card.translation,
                          radius=T.RADIUS["chip"], icon=QRectF(tx + w + 4, ty + (h - s) / 2, s, s))
            ty += h + 2
        if card.description:
            ty += self.text(p, card.description, tx, ty, tw, "body_small", self.c["on_surface_variant"], lines=2)[0]
        y = max(y + media, ty) + T.SECTION
        map_image = self.assets.get("map")
        y = self.paragraph(p, y, card.definition, lines=3 if map_image is None else 2)
        if map_image is not None:
            m = QRectF(pad, y, self.inner, 132)
            if p:
                clip = QPainterPath(); clip.addRoundedRect(m, T.RADIUS["media"], T.RADIUS["media"])
                p.save(); p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                src_h = map_image.width() * m.height() / m.width()
                p.drawImage(m, map_image, QRectF(0, (map_image.height() - src_h) / 2, map_image.width(), src_h))
                af = type_font("caption", 500); p.setFont(af); fm = QFontMetrics(af)
                a = "© OpenStreetMap"; aw = fm.horizontalAdvance(a) + 12
                ar = QRectF(m.right() - aw - 8, m.bottom() - fm.height() - 8, aw, fm.height() + 2)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 110)); p.drawRoundedRect(ar, 6, 6)
                p.setPen(QColor(255, 255, 255, 170)); p.drawText(ar, Qt.AlignmentFlag.AlignCenter, a)
                p.restore()
            y = m.bottom() + T.SECTION
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)
