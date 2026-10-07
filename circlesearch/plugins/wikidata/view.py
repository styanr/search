import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainterPath, QPen

from circlesearch.plugins.wikidata import FactsCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import SECTION, CardView, decode, view
from circlesearch.ui.effects import draw_loader
from circlesearch.ui.motion import WORD_SPRING, Spring, lerp, mix
from circlesearch.ui.shapes import glyph
from circlesearch.ui.theme import C, type_font

GLYPHS = {"Population": "people", "Area": "area", "Elevation": "mountain", "Founded": "calendar", "Capital": "capital",
          "Currency": "coins", "Languages": "chat", "Calling code": "phone", "Developer": "person", "Latest version": "tag",
          "Licence": "tag", "Written in": "code", "First released": "calendar", "Born": "calendar", "Died": "calendar",
          "Occupation": "person", "Citizenship": "capital", "Country": "capital", "Headquarters": "capital",
          "Chief executive": "person", "Employees": "people", "Industry": "tag", "Author": "person", "Artist": "person",
          "Directed by": "person", "Starring": "people", "Created by": "person", "Released": "calendar",
          "First published": "calendar", "First aired": "calendar", "Runtime": "clock", "Length": "clock",
          "Genre": "tag", "Seasons": "tag", "Rating": "star", "Pages": "tag", "Tracks": "tag", "Status": "tag",
          "Network": "tag", "Next episode": "calendar"}


@view(FactsCard)
class FactsView(CardView):
    @staticmethod
    def prepare(card):
        return {"cover": decode(card.image)}

    PEOPLE_COLUMNS = 5
    AVATAR = 56
    TRACK_ROW = 32
    TRACK_LIMIT = 14
    BYLINE = ("Author", "Artist", "Directed by", "Created by")

    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.chevrons = {}
        self.pane = Spring(420, 0.9)
        self.final = False
        self.scroll = 0.0
        self.closed = False
        self.entered = 0.0
        self.overflow = 0.0
        self.loaded = -1.0
        self.entry = None
        self.ratio = 1.0
        self.closing = False
        self.faces = {}
        self.last = None
        self.started = time.monotonic()

    def step(self, dt):
        moving = any([s.step(dt) for s in [*self.chevrons.values(), self.pane]])
        return moving or self.appearing() or any(d == "loading" for d in self.w.details.values())

    def state_key(self):
        w = self.w
        return (w.open_section, round(self.scroll), tuple((i, d if isinstance(d, str) else type(d).__name__)
                                                          for i, d in w.details.items()))

    def section_row(self, p, y, targets):
        w, x = self.w, self.PAD
        for i, section in enumerate(self.card.sections):
            name = f"{SECTION}{i}"
            spring = self.chevrons.setdefault(i, Spring(*T.SPRING_SPATIAL))
            spring.set(1.0 if w.open_section == i else 0.0)
            k = max(0.0, min(1.0, spring.value))
            width = self.measure(section.label, "button") + 48
            r = QRectF(x, y, width, 34)
            targets[name] = (r, lambda i=i: w.toggle_section(i))
            if p:
                shape = QPainterPath()
                shape.addRoundedRect(r, 17, 17)
                fg = mix(self.c["on_surface"], self.on_container(), k)
                p.save()
                self.squeezed(p, r, name)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(mix(C(self.tile()), self.container(), k))
                p.drawPath(shape)
                it = self.fx(name)
                alpha = T.HOVER_ALPHA * it.hover.value + T.PRESS_ALPHA * it.press.value
                if alpha > 0.5:
                    p.setBrush(QColor(fg.red(), fg.green(), fg.blue(), round(min(255.0, alpha * 1.4))))
                    p.drawPath(shape)
                p.setFont(type_font("button"))
                p.setPen(fg)
                p.drawText(QRectF(r.left() + 16, r.top(), width - 40, r.height()), Qt.AlignmentFlag.AlignVCenter,
                           section.label)
                c = QPointF(r.right() - 17, r.center().y())
                turn = lerp(1.0, -1.0, k)
                p.setPen(QPen(fg, 1.8, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
                p.drawPolyline([c + QPointF(-4, -2 * turn), c + QPointF(0, 2 * turn), c + QPointF(4, -2 * turn)])
                p.restore()
            x += width + 6
        return y + 34 + T.SECTION

    def animating(self):
        return self.pane.active

    def appearing(self):
        return self.w.open_section is not None and time.monotonic() - self.entered < 1.2 or \
            time.monotonic() - self.loaded < 0.3

    def pop(self, i, n=1, gap=0.045, length=0.38):
        if self.closing:
            return max(0.0, min(1.0, self.ratio * 2.4 - 0.7 * (i / max(n, 1))))
        raw = (time.monotonic() - self.entered - i * gap) / length
        return WORD_SPRING.valueForProgress(max(0.0, min(1.0, raw)))

    def final_height(self):
        self.final = True
        try:
            return self.w._layout(None)
        finally:
            self.final = False

    def closed_height(self):
        self.closed = True
        try:
            return self.w._layout(None)
        finally:
            self.closed = False

    MIN_ROOM = 150

    def wheel(self, delta, pos):
        w = self.w
        if w.open_section is None or self.overflow <= 0:
            return False
        self.scroll = min(self.overflow, max(0.0, self.scroll - delta.y() / 120 * 48))
        return True

    def detail_area(self, p, y, targets):
        w = self.w
        if self.closed:
            return y
        if w.open_section is not None:
            self.last = w.open_section
        detail = w.details.get(self.last) if self.last is not None else None
        entry = (w.open_section, self.last, "loading" if detail == "loading" else id(detail))
        if entry != self.entry:
            self.scroll = 0.0
        if w.open_section is not None and entry != self.entry:
            self.entered = time.monotonic()
            if self.entry is not None and self.entry[2] == "loading" and entry[2] != "loading":
                self.loaded = self.entered
        self.entry = entry
        self.closing = w.open_section is None
        content = self.content_height(detail)
        full = content + T.SECTION if w.open_section is not None else 0.0
        room = w.room() if full else 10 ** 6
        if full > room:
            full = max(self.MIN_ROOM, room)
        self.overflow = max(0.0, content + T.SECTION - full) if full else 0.0
        self.scroll = min(self.scroll, self.overflow)
        self.pane.set(full)
        if self.final:
            return y + full
        used = max(0.0, self.pane.value)
        self.register_links(detail, y, used, targets)
        self.ratio = used / max(full if full else self.content_height(detail) + T.SECTION, 1.0)
        if self.pane.active:
            self.settling = True
        if p and used > 1 and self.last is not None:
            p.save()
            p.setClipRect(QRectF(0, y, self.width, used))
            p.translate(0, -self.scroll)
            self.detail_content(p, y, detail)
            fade = 1.0 - (time.monotonic() - self.loaded) / 0.2
            if fade > 0 and w.open_section is not None:
                p.setOpacity(p.opacity() * fade)
                self.spinner(p, y, 1.0)
            p.restore()
        return y + used

    def spinner(self, p, y, u):
        c = QPointF(self.PAD + self.inner / 2, y + 32)
        p.save()
        p.translate(c)
        p.scale(max(0.0, 0.4 + 0.6 * u), max(0.0, 0.4 + 0.6 * u))
        p.translate(-c)
        p.setOpacity(p.opacity() * max(0.0, min(1.0, u * 1.6)))
        draw_loader(p, c, time.monotonic() - self.started, self.c["primary"], radius=10)
        p.restore()

    LINK_ROW = 38

    def register_links(self, detail, y, used, targets):
        if not detail or detail == "loading" or detail.kind != "works" or self.w.open_section is None:
            return
        window = QRectF(self.PAD, y, self.inner, used)
        for i, link in enumerate(detail.items):
            row = QRectF(self.PAD + 6, y + 6 + i * self.LINK_ROW - self.scroll, self.inner - 12, self.LINK_ROW)
            visible = row.intersected(window)
            if visible.height() > 8:
                targets[f"link{i}"] = (visible, lambda link=link: self.w.open_link(link))

    def works(self, p, y, items):
        height = len(items) * self.LINK_ROW + 12
        if p:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(self.tile()))
            p.drawRoundedRect(QRectF(self.PAD, y, self.inner, height), T.RADIUS["tile"], T.RADIUS["tile"])
        lh = QFontMetrics(type_font("body_small")).lineSpacing()
        for i, link in enumerate(items):
            row = QRectF(self.PAD + 6, y + 6 + i * self.LINK_ROW, self.inner - 12, self.LINK_ROW)
            u = self.pop(i, len(items), gap=0.03, length=0.34) if p else 1.0
            if p:
                p.save()
                p.setOpacity(p.opacity() * max(0.0, min(1.0, u * 1.4)))
                p.translate((1 - u) * -16, 0)
                p.setPen(Qt.PenStyle.NoPen)
                it = self.fx(f"link{i}")
                alpha = T.HOVER_ALPHA * it.hover.value + T.PRESS_ALPHA * it.press.value
                if alpha > 0.5:
                    p.setBrush(QColor(255, 255, 255, round(alpha)))
                    p.drawRoundedRect(row, 12, 12)
            sub_w = self.measure(link.sub, "body_small") + 2 if link.sub else 0
            self.text(p, link.label, row.left() + 12, row.top() + (row.height() - lh) / 2,
                      row.width() - 24 - sub_w - 26, "body_small")
            if sub_w:
                self.text(p, link.sub, row.right() - 34 - sub_w, row.top() + (row.height() - lh) / 2, sub_w,
                          "body_small", self.c["on_surface_variant"], align="right")
            if p:
                c = QPointF(row.right() - 18, row.center().y())
                p.setPen(QPen(self.c["on_surface_variant"], 1.7, cap=Qt.PenCapStyle.RoundCap,
                              join=Qt.PenJoinStyle.RoundJoin))
                p.drawPolyline([c + QPointF(-2.5, -4.5), c + QPointF(2.5, 0), c + QPointF(-2.5, 4.5)])
                p.restore()
        return height

    def content_height(self, detail):
        if detail == "loading":
            return 64
        if not detail:
            return 40
        if detail.kind == "people":
            return self.people(None, 0, detail.items)
        if detail.kind == "tracks":
            return self.tracks(None, 0, detail.items)
        if detail.kind == "works":
            return self.works(None, 0, detail.items)
        return self.about(None, 0, detail.items[0])

    def detail_content(self, p, y, detail):
        if detail == "loading":
            height = 64
            if p:
                self.spinner(p, y, self.pop(0, length=0.4))
        elif not detail:
            height = 40
            self.text(p, "Could not load this", self.PAD + 4, y + 8, self.inner, "body_small",
                      self.c["on_surface_variant"])
        elif detail.kind == "people":
            height = self.people(p, y, detail.items)
        elif detail.kind == "tracks":
            height = self.tracks(p, y, detail.items)
        elif detail.kind == "works":
            height = self.works(p, y, detail.items)
        else:
            height = self.about(p, y, detail.items[0])
        return height

    def about(self, p, y, text):
        h = self.text(None, text, self.PAD + 4, y, self.inner - 8, "body", lines=8)[0]
        if p:
            u = self.pop(0, length=0.45)
            p.save()
            p.setOpacity(p.opacity() * max(0.0, min(1.0, u)))
            p.translate(0, (1 - u) * 12)
            self.text(p, text, self.PAD + 4, y, self.inner - 8, "body", self.c["on_surface_variant"], lines=8)
            p.restore()
        return h

    def tracks(self, p, y, items):
        shown = items[:self.TRACK_LIMIT]
        extra = len(items) - len(shown)
        rows = len(shown) + (1 if extra > 0 else 0)
        height = rows * self.TRACK_ROW + 12
        if p:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(self.tile()))
            p.drawRoundedRect(QRectF(self.PAD, y, self.inner, height), T.RADIUS["tile"], T.RADIUS["tile"])
        top = y + 6
        for index, (number, title, length) in enumerate(shown):
            u = self.pop(index, len(shown), gap=0.03, length=0.34) if p else 1.0
            if p:
                p.save()
                p.setOpacity(p.opacity() * max(0.0, min(1.0, u * 1.4)))
                p.translate((1 - u) * -16, 0)
            row = QRectF(self.PAD + 14, top, self.inner - 28, self.TRACK_ROW)
            lh = QFontMetrics(type_font("body_small")).lineSpacing()
            self.text(p, str(number), row.left(), row.top() + (row.height() - lh) / 2, 22, "body_small",
                      self.c["on_surface_variant"], align="right")
            self.text(p, title, row.left() + 34, row.top() + (row.height() - lh) / 2, row.width() - 34 - 52,
                      "body_small")
            self.text(p, length, row.right() - 48, row.top() + (row.height() - lh) / 2, 48, "body_small",
                      self.c["on_surface_variant"], align="right")
            if p:
                p.restore()
            top += self.TRACK_ROW
        if extra > 0:
            self.text(p, f"+{extra} more", self.PAD + 14 + 34, top + 8, self.inner, "body_small",
                      self.c["on_surface_variant"])
        return height

    def people(self, p, y, items):
        cols = self.PEOPLE_COLUMNS
        cell = self.inner / cols
        label_h = QFontMetrics(type_font("caption")).lineSpacing() * 2
        row_h = self.AVATAR + 8 + label_h + 10
        for i, (name, photo) in enumerate(items):
            cx = self.PAD + (i % cols + 0.5) * cell
            top = y + (i // cols) * row_h
            circle = QRectF(cx - self.AVATAR / 2, top, self.AVATAR, self.AVATAR)
            u = self.pop(i, len(items)) if p else 1.0
            if p:
                p.save()
                p.translate(cx, top + self.AVATAR / 2)
                p.scale(max(0.0, 0.45 + 0.55 * u), max(0.0, 0.45 + 0.55 * u))
                p.translate(-cx, -(top + self.AVATAR / 2))
                p.setOpacity(p.opacity() * max(0.0, min(1.0, u * 1.8)))
                self.avatar(p, circle, name, photo, i)
                p.restore()
                p.save()
                p.setOpacity(p.opacity() * max(0.0, min(1.0, (u - 0.3) * 1.6)))
                p.translate(0, (1 - min(u, 1.0)) * 6)
            self.text(p, name, cx - cell / 2 + 2, top + self.AVATAR + 6, cell - 4, "caption", lines=2, align="center")
            if p:
                p.restore()
        return math.ceil(len(items) / cols) * row_h - 6

    def avatar(self, p, circle, name, photo, i):
        image = self.faces.get(i)
        if image is None and photo:
            image = self.faces[i] = decode(photo)
        clip = QPainterPath()
        clip.addEllipse(circle)
        p.save()
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        if image is not None:
            side = min(image.width(), image.height())
            src = QRectF((image.width() - side) / 2, (image.height() - side) * 0.12, side, side)
            p.drawImage(circle, image, src)
        else:
            p.fillRect(circle, self.container())
            p.setFont(type_font("subhead", 620))
            p.setPen(self.on_container())
            p.drawText(circle, Qt.AlignmentFlag.AlignCenter, "".join(w[0] for w in name.split()[:2]).upper())
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, T.BORDER_ALPHA), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(circle)
    DATED = ("Released", "First published", "First aired")

    def cover_header(self, p, cover):
        pad = self.PAD
        h = 156
        w = round(h * cover.width() / cover.height())
        if w > 116:
            w, h = 116, round(116 * cover.height() / cover.width())
        box = QRectF(pad, pad, w, h)
        if p:
            clip = QPainterPath()
            clip.addRoundedRect(box, 14, 14)
            p.save()
            p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
            p.drawImage(box, cover)
            p.restore()
        name, _, kind = self.card.title.partition(" · ")
        rows = dict(self.card.rows)
        by = next((rows[k] for k in self.BYLINE if k in rows), "")
        when = next((rows[k] for k in self.DATED if k in rows), "")
        tx, tw = pad + w + 18, self.inner - w - 18
        ty = pad + 2
        ty += self.text(p, name, tx, ty, tw, "headline", lines=3)[0] + 4
        if by:
            ty += self.text(p, by, tx, ty, tw, "subhead", self.c["primary"], lines=2)[0] + 4
        tag = " · ".join(x for x in (kind, when) if x)
        if tag:
            ty += self.text(p, tag, tx, ty, tw, "body_small", self.c["on_surface_variant"])[0]
        return max(pad + h, ty) + T.SECTION

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        cover = self.assets.get("cover")
        y = self.cover_header(p, cover) if cover is not None else self.header(p, pad, card.title)
        gap, row_h = T.GAP, 70
        half = (self.inner - gap) / 2
        vf = QFontMetrics(type_font("subhead", 620))
        shown = [(label, value) for label, value in card.rows
                 if cover is None or label not in self.BYLINE + self.DATED]
        items = [(label, value, vf.horizontalAdvance(value) > half - 28) for label, value in shown]
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
        if card.sections and not self.w.pinned:
            y = self.detail_area(p, self.section_row(p, y, targets), targets)
        y = self.button_group(p, card.actions, y, targets)
        return self.footer(p, y, targets)
