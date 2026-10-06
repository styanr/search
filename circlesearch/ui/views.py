from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath

from circlesearch.core.cards import Card, HeroCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, decode, view, wrap
from circlesearch.ui.shapes import STARS, star_path
from circlesearch.ui.theme import C, card_font, ui_font

MAP_TINT = QColor("#9DB4E0")


@view(Card)
class TextView(CardView):
    def layout(self, paint, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.width - 2 * pad
        role = getattr(card, "title_role", "name")
        y = pad - 2

        def text(s, px, weight, color, x, y, w=None, max_lines=1):
            f = ui_font(px, weight)
            fm = QFontMetrics(f)
            lines = wrap(fm, s, w or width, max_lines)
            if paint:
                paint.setFont(f)
                paint.setPen(color)
                for i, line in enumerate(lines):
                    paint.drawText(QPointF(x, y + fm.ascent() + i * fm.lineSpacing()), line)
            return len(lines) * fm.lineSpacing(), (fm.horizontalAdvance(lines[0]) if lines else 0)

        def copy_button(name, rect, payload):
            targets[name] = (rect, lambda: self.copy(payload))
            if paint:
                self.copy_icon(paint, rect, self.hover == name)

        if role == "passage":
            title_h, title_w = text(card.title, 15, 450, c["on_surface_variant"], pad, y, max_lines=3)
        elif role == "query":
            title_h, title_w = text(card.title, 17, 520, c["on_surface_variant"], pad, y, max_lines=2)
        else:
            title_h, title_w = text(card.title, 24, 620, c["on_surface"], pad, y, max_lines=2)
        pronunciation = getattr(card, "pronunciation", "")
        if pronunciation:
            fp = QFontMetrics(ui_font(15, 430))
            pw = fp.horizontalAdvance(pronunciation)
            if title_h < 40 and title_w + 12 + pw <= width:
                f24 = QFontMetrics(ui_font(24, 620))
                text(pronunciation, 15, 430, c["on_surface_variant"], pad + title_w + 12, y + f24.ascent() - fp.ascent())
            else:
                title_h += text(pronunciation, 15, 430, c["on_surface_variant"], pad, y + title_h)[0]
        y += title_h + 6

        chips = [s for s in (getattr(card, "part_of_speech", ""), getattr(card, "description", ""),
                             *getattr(card, "chips", [])) if s]
        if chips:
            chip_font = ui_font(12, 600)
            fm = QFontMetrics(chip_font)
            x = pad
            for label in chips:
                cw = min(fm.horizontalAdvance(label) + 24, width)
                if x + cw > pad + width and x > pad:
                    x, y = pad, y + 24 + 6
                if paint:
                    paint.setPen(Qt.PenStyle.NoPen)
                    paint.setBrush(c["surface_high"])
                    paint.drawRoundedRect(QRectF(x, y, cw, 24), 8, 8)
                    paint.setFont(chip_font)
                    paint.setPen(c["on_surface_variant"])
                    paint.drawText(QRectF(x, y, cw, 24), Qt.AlignmentFlag.AlignCenter,
                                   fm.elidedText(label, Qt.TextElideMode.ElideRight, int(cw - 20)))
                x += cw + 8
            y += 24 + 12

        definition = getattr(card, "definition", "")
        if definition and role != "passage":
            y += text(definition, 15, 420, c["on_surface"], pad, y, max_lines=3)[0] + 14

        value = getattr(card, "value", "")
        if value:
            vf = QFontMetrics(ui_font(34, 600))
            h = vf.lineSpacing()
            text(value, 34, 600, c["on_surface"], pad, y, w=width - 48)
            copy_button("value", QRectF(pad + width - 36, y + (h - 36) / 2, 36, 36), value)
            y += h + 10

        rows = getattr(card, "rows", [])
        for i, (label, row_value) in enumerate(rows):
            lf, vf_ = QFontMetrics(ui_font(13, 560)), QFontMetrics(ui_font(15, 460))
            value_lines = len(wrap(vf_, row_value, width - 116 - 36, 2))
            row_h = max(36, value_lines * vf_.lineSpacing() + 12)
            row = QRectF(pad - 8, y, width + 16, row_h)
            name = f"row{i}"
            targets[name] = (row, lambda v=row_value: self.copy(v))
            if paint and self.hover == name:
                paint.setPen(Qt.PenStyle.NoPen)
                paint.setBrush(QColor(255, 255, 255, 14))
                paint.drawRoundedRect(row, 12, 12)
                self.copy_icon(paint, QRectF(row.right() - 34, row.top() + (row_h - 28) / 2, 28, 28), True)
            text(label, 13, 560, c["on_surface_variant"], pad, y + 6 + (vf_.lineSpacing() - lf.lineSpacing()) / 2, w=110)
            text(row_value, 15, 460, c["on_surface"], pad + 116, y + 6, w=width - 116 - 36, max_lines=2)
            y += row_h
        if rows:
            y += 8

        translation = getattr(card, "translation", "")
        if translation:
            alternatives = getattr(card, "alternatives", [])
            passage = role == "passage"
            inner = QRectF(pad - 8, y, width + 16, 0)
            ix, iw = inner.left() + 16, inner.width() - 32 - 40
            label_h = QFontMetrics(ui_font(12, 600)).lineSpacing()
            big = 17 if passage else 19
            fm_big = QFontMetrics(ui_font(big, 560))
            n_lines = len(wrap(fm_big, translation, iw, 6 if passage else 2))
            alt_h = QFontMetrics(ui_font(13, 430)).lineSpacing() if alternatives else 0
            inner.setHeight(14 + label_h + 4 + n_lines * fm_big.lineSpacing() + (4 + alt_h if alt_h else 0) + 14)
            if paint:
                paint.setPen(Qt.PenStyle.NoPen)
                paint.setBrush(c["surface_high"])
                paint.drawRoundedRect(inner, 18, 18)
            copy_button("copy", QRectF(inner.right() - 14 - 36, inner.top() + 12, 36, 36), translation)
            ty = inner.top() + 14
            ty += text(getattr(card, "translation_label", ""), 12, 600, c["primary"], ix, ty)[0] + 4
            ty += text(translation, big, 560, c["on_surface"], ix, ty, w=iw, max_lines=6 if passage else 2)[0]
            if alternatives:
                text(", ".join(alternatives), 13, 430, c["on_surface_variant"], ix, ty + 4, w=iw)
            y = inner.bottom() + 12

        if card.actions:
            af = ui_font(13, 580)
            afm = QFontMetrics(af)
            x = pad - 8
            for i, action in enumerate(card.actions):
                aw = afm.horizontalAdvance(action.label) + 32
                if x + aw > pad + width + 8 and x > pad:
                    x, y = pad - 8, y + 40 + 8
                r = QRectF(x, y, aw, 40)
                name = f"action{i}"
                targets[name] = (r, self.action_handler(action))
                if paint:
                    primary = i == 0
                    bg = c["primary"] if primary else c["surface_high"]
                    fg = c["on_primary"] if primary else c["on_surface"]
                    paint.setPen(Qt.PenStyle.NoPen)
                    paint.setBrush(bg)
                    paint.drawRoundedRect(r, 20, 20)
                    if self.hover == name:
                        paint.setBrush(QColor(fg.red(), fg.green(), fg.blue(), 22))
                        paint.drawRoundedRect(r, 20, 20)
                    paint.setFont(af)
                    paint.setPen(fg)
                    paint.drawText(r, Qt.AlignmentFlag.AlignCenter, action.label)
                x += aw + 8
            y += 40 + 14

        if card.source:
            f = ui_font(12, 560)
            fm = QFontMetrics(f)
            r = QRectF(pad, y, fm.horizontalAdvance(card.source) + 2, fm.lineSpacing())
            if card.url:
                targets["source"] = (r.adjusted(-6, -4, 6, 4), lambda: self.open(card.url))
            if paint:
                paint.setFont(f)
                hover = self.hover == "source"
                paint.setPen(c["on_surface"] if hover else c["on_surface_variant"])
                paint.drawText(QPointF(r.left(), r.top() + fm.ascent()), card.source)
                if hover:
                    paint.drawLine(QPointF(r.left(), r.bottom() - 1), QPointF(r.right(), r.bottom() - 1))
            y += fm.lineSpacing()
        else:
            y -= 10
        return y + pad - 4


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
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        img = self.assets.get("image")
        shape = card.image_shape or "cookie9"
        media = 92
        if img is not None and p:
            p.drawImage(QPointF(pad - 2, y), self.shaped(img, shape, media, cover=shape != "logo_squircle"))
        elif media and p:
            r = QRectF(pad - 2, y, media, media)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.PRIMARY_CONTAINER)); p.drawPath(star_path(r, *STARS["cookie9"]))
            self.text(p, card.title[:1].upper(), 40, 640, C(T.ON_PRIMARY_CONTAINER), r.left(), r.top() + 20, r.width(), align="center")
        tx = pad + (media + 16 if media else 0)
        tw = width - (media + 16 if media else 0)
        ty = y + (4 if media else 0)
        h, _ = self.text(p, card.title, 28, 640, c["on_surface"], tx, ty, tw, lines=2, wdth=100, fit=True)
        ty += h + 2
        if card.translation:
            h, tw_ = self.text(p, card.translation, 17, 560, c["primary"], tx, ty, tw)
            targets["copy"] = (QRectF(tx - 4, ty - 2, tw_ + 34, h + 4), lambda: self.copy(card.translation))
            if p and self.hover == "copy":
                self.copy_icon(p, QRectF(tx + tw_ + 4, ty - 4, 28, 28), True)
            ty += h + 2
        if card.description:
            ty += self.text(p, card.description, 13, 480, c["on_surface_variant"], tx, ty, tw, lines=2)[0]
        y = max(y + media, ty) + 14
        map_image = self.assets.get("map")
        if card.definition:
            y += self.text(p, card.definition, 14.5, 430, c["on_surface"], pad, y, width,
                           lines=3 if map_image is None else 2)[0] + 14
        if map_image is not None:
            m = QRectF(pad, y, width, 132)
            if p:
                clip = QPainterPath(); clip.addRoundedRect(m, 20, 20)
                p.save(); p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                src_h = map_image.width() * m.height() / m.width()
                p.drawImage(m, map_image, QRectF(0, (map_image.height() - src_h) / 2, map_image.width(), src_h))
                af = card_font(9.5, 520); p.setFont(af); fm = QFontMetrics(af)
                a = "© OpenStreetMap"; aw = fm.horizontalAdvance(a) + 12
                ar = QRectF(m.right() - aw - 8, m.bottom() - fm.height() - 8, aw, fm.height() + 2)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 110)); p.drawRoundedRect(ar, 6, 6)
                p.setPen(QColor(255, 255, 255, 170)); p.drawText(ar, Qt.AlignmentFlag.AlignCenter, a)
                p.restore()
            y = m.bottom() + 14
        if card.actions:
            y = self.buttons(p, card.actions, pad, y, targets) + 14
        return self.source(p, y, targets) + pad - 4
