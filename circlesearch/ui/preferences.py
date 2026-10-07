import copy
import os
from functools import cache

from PyQt6.QtCore import QEvent, QLocale, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainterPath, QPalette, QPen
from PyQt6.QtWidgets import QLineEdit

from circlesearch.core import currencies, history, locale, ocr, settings
from circlesearch.core.cards import Card
from circlesearch.ui import backdrop, tokens as T
from circlesearch.ui.cards import CardView, CardWidget, rrect
from circlesearch.ui.effects import draw_check
from circlesearch.ui.motion import Spring, lerp, mix
from circlesearch.ui.qtlocale import QtLocale
from circlesearch.ui.shapes import glyph
from circlesearch.ui.theme import C, ON_SURFACE_VARIANT, PALETTE, type_font

COLUMN = 340
LABEL = 112
FIELD_H = 40
ROW_H = 56
PICK_ROW = 40
PICK_ROWS = 6
EXPAND = (900, 1.0)
KEYS = {"cards": ("cards",), "history": ("history",), "reduce": ("gpu",), "debug": ("debug",),
        "language": ("locale", "language"), "currency": ("locale", "currency"), "units": ("locale", "units"),
        "ocr": ("ocr", "languages"), "contact": ("contact",)}
NEXT_TIME = ("reduce", "debug", "ocr")
UNITS = (("", "Automatic"), ("metric", "Metric"), ("imperial", "Imperial"))
VARIANTS = {"sim": "Simplified", "tra": "Traditional", "vert": "vertical", "latn": "Latin", "cyrl": "Cyrillic"}


@cache
def metrics(style, weight=None):
    return QFontMetrics(type_font(style, weight))


def language_name(code):
    base, _, variant = code.partition("_")
    language = QLocale.codeToLanguage(base)
    if language == QLocale.Language.AnyLanguage:
        return None
    name = QLocale.languageToString(language)
    return f"{name} ({VARIANTS.get(variant, variant)})" if variant else name


@cache
def language_options():
    found = {}
    for loc in QLocale.matchingLocales(QLocale.Language.AnyLanguage, QLocale.Script.AnyScript,
                                       QLocale.Country.AnyCountry):
        code = QLocale.languageToCode(loc.language(), QLocale.LanguageCodeType.ISO639Part1)
        if code and code not in found:
            name = QLocale.languageToString(loc.language())
            native = QLocale(loc.language()).nativeLanguageName()
            found[code] = (code, name, "" if native.lower().endswith(name.lower()) else native)
    return sorted(found.values(), key=lambda o: o[1])


@cache
def currency_options():
    return sorted(((code, name, code) for code, name in currencies.NAMES.items()), key=lambda o: o[1])


def short_path(path):
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def plain(edit):
    edit.setFont(type_font("body"))
    edit.setFrame(False)
    pal = edit.palette()
    for role, color in ((QPalette.ColorRole.Base, Qt.GlobalColor.transparent),
                        (QPalette.ColorRole.Text, PALETTE["on_surface"]),
                        (QPalette.ColorRole.Highlight, PALETTE["primary"]),
                        (QPalette.ColorRole.HighlightedText, PALETTE["on_primary"]),
                        (QPalette.ColorRole.PlaceholderText, ON_SURFACE_VARIANT)):
        pal.setColor(role, color)
    edit.setPalette(pal)
    return edit


class Field(QLineEdit):
    def __init__(self, panel, key):
        super().__init__(panel)
        self.panel, self.key = panel, key
        plain(self)
        self.setText(panel.value(key))
        self.editingFinished.connect(self.commit)

    def commit(self):
        self.panel.change(self.key, self.text().strip())

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.panel.focus_name = self.key
        self.panel.refresh()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.panel.refresh()


class SettingsView(CardView):
    PAD = 24

    def __init__(self, widget, card, assets):
        super().__init__(widget, card, assets)
        self.springs = {}
        self.scroll = 0.0
        self.content = 0.0
        self.fields = {}
        self.picker_area = QRectF()
        self.list_area = QRectF()
        self.shown = {}

    def family(self):
        return "neutral"

    def spring(self, name, target, params=T.SPRING_SPATIAL):
        s = self.springs.get(name)
        if s is None:
            s = self.springs[name] = Spring(*params, value=target)
        s.set(target)
        return s.value

    def step(self, dt):
        moving = any([s.step(dt) for s in self.springs.values()])
        if any(s.active for name, s in self.springs.items() if name.startswith("expand:")):
            self.w.relayout()
        return moving

    def state_key(self):
        w = self.w
        return (self.scroll, repr(w.values), w.focused(), w.contact.text(), w.note(), w.picking, w.search.text(),
                w.active, w.first, w.saved, w.cleared is not None, w.focus_name, w.ring)

    def wheel(self, delta, pos):
        w = self.w
        if w.picking and self.list_area.contains(pos):
            w.scroll_list(-1 if delta.y() > 0 else 1)
            return True
        limit = max(0.0, self.content - w.height())
        if limit <= 0:
            return False
        self.scroll = min(limit, max(0.0, self.scroll - delta.y() / 120 * 56))
        w.relayout()
        return True

    def layout(self, p, targets):
        w = self.w
        self.fields = {}
        if p and self.content > w.height():
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(w.rect()), w.radius(), w.radius())
            p.setClipPath(clip)
        y = self.title(p, targets, self.PAD - self.scroll)
        cols = 2 if self.inner >= 2 * COLUMN + 12 else 1
        colw = (self.inner - (cols - 1) * 12) / cols
        groups = [self.cards_group, self.region_group, self.ocr_group, self.effects_group, self.online_group]
        bottom = y
        for i, column in enumerate([groups[:2], groups[2:]] if cols == 2 else [groups]):
            cy = y
            for group in column:
                cy = group(p, targets, self.PAD + i * (colw + 12), cy, colw) + 20
            bottom = max(bottom, cy)
        self.content = self.footer_row(p, targets, bottom - 6) + self.scroll
        if p:
            self.focus_ring(p, targets)
        return min(self.content, w.max_height)

    def focus_ring(self, p, targets):
        w = self.w
        name = w.focus_name
        if not w.ring or name not in targets or name == w.picking_target():
            return
        r = targets[name][0]
        radius = (r.width() / 2 if name == "close" else 18 if name == "clear" else T.RADIUS["chip"]
                  if name.startswith("ocr:") else FIELD_H / 2 if name.startswith("units:")
                  else 6 if name == "file" else 12)
        p.save()
        p.setPen(QPen(self.c["primary"], 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
        p.restore()

    def title(self, p, targets, y):
        h, _ = self.text(p, "Settings", self.PAD, y, self.inner - 48, "headline")
        s = T.ICON_BUTTON
        b = QRectF(self.PAD + self.inner - s + 4, y + (h - s) / 2, s, s)
        targets["close"] = (b, self.w.closeRequested.emit)
        if p:
            it = self.fx("close")
            p.save()
            self.squeezed(p, b, "close", 0.1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, round(T.HOVER_ALPHA * (0.6 + it.hover.value))))
            p.drawEllipse(b)
            glyph(p, "close", b.adjusted(10, 10, -10, -10),
                  mix(self.c["on_surface_variant"], self.c["on_surface"], it.hover.value))
            p.restore()
        return y + h + 18

    def group(self, p, targets, title, x, y, width, rows, footer=""):
        y += self.text(p, title, x + 4, y, width - 8, "label", self.c["on_surface_variant"])[0] + 8
        for i, row in enumerate(rows):
            h = row(None, targets, x, y, width, None)
            path = None
            if p:
                big, small = T.RADIUS["media"], 6
                top, end = big if i == 0 else small, big if i == len(rows) - 1 else small
                path = rrect(QRectF(x, y, width, h), top, top, end, end)
            row(p, targets, x, y, width, h, path)
            y += h + 2
        if footer:
            y += 6 + self.text(p, footer, x + 4, y + 6, width - 8, "body_small", self.c["on_surface_variant"],
                               lines=3)[0]
        return y - 2

    def cards_group(self, p, targets, x, y, width):
        return self.group(p, targets, "Cards", x, y, width, [
            self.switch_row("cards", "Show cards", "Facts, translations and conversions"),
            self.switch_row("history", "Remember searches", "Kept on this computer"),
            self.clear_row(),
        ])

    def region_group(self, p, targets, x, y, width):
        return self.group(p, targets, "Region", x, y, width, [
            self.picker_row("language", "Language"),
            self.picker_row("currency", "Currency"),
            self.units_row(),
        ], "Used for translations and conversions in cards")

    def ocr_group(self, p, targets, x, y, width):
        return self.group(p, targets, "Text recognition", x, y, width, [self.languages_row()])

    def effects_group(self, p, targets, x, y, width):
        return self.group(p, targets, "Effects", x, y, width, [
            self.switch_row("reduce", "Reduce effects", "Always on with software rendering" if self.w.software
                            else "Stops the glow and shimmer"),
            self.switch_row("debug", "Save debug files", short_path(os.path.join(settings.CACHE_DIR, "debug"))),
        ])

    def online_group(self, p, targets, x, y, width):
        return self.group(p, targets, "Online services", x, y, width, [
            self.field_row("contact", "Contact", "Email or website"),
        ], "Sent only to Wikimedia, OpenStreetMap, Open Library and MusicBrainz, so they can reach you if something goes wrong")

    def tile(self, p, path, name=None):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(T.TILE["neutral"]))
        p.drawPath(path)
        if name:
            it = self.fx(name)
            alpha = T.HOVER_ALPHA * it.hover.value + T.PRESS_ALPHA * it.press.value
            if alpha > 0.5:
                p.setBrush(QColor(255, 255, 255, round(alpha)))
                p.drawPath(path)

    def switch_row(self, key, title, subtext=""):
        def row(p, targets, x, y, width, h, path=None):
            text_h = metrics("body", 560).lineSpacing() + (2 + metrics("body_small").lineSpacing() if subtext else 0)
            if h is None:
                return max(ROW_H, text_h + 28)
            on = self.w.value(key)
            targets[key] = (QRectF(x, y, width, h), lambda: self.w.change(key, not on))
            if p:
                self.tile(p, path, key)
                ty = y + (h - text_h) / 2
                ty += self.text(p, title, x + 16, ty, width - 100, "body", weight=560)[0] + 2
                if subtext:
                    self.text(p, subtext, x + 16, ty, width - 100, "body_small", self.c["on_surface_variant"])
                self.switch(p, QRectF(x + width - 16 - 52, y + (h - 32) / 2, 52, 32), key, on)
        return row

    def clear_row(self):
        def row(p, targets, x, y, width, h, path=None):
            w = self.w
            text_h = metrics("body", 560).lineSpacing() + 2 + metrics("body_small").lineSpacing()
            if h is None:
                return max(ROW_H, text_h + 28)
            undo = w.cleared is not None
            label = "Undo" if undo else "Clear"
            bw = self.measure(label, "button") + 36
            b = QRectF(x + width - 16 - bw, y + (h - 36) / 2, bw, 36)
            enabled = undo or w.saved > 0
            if enabled:
                targets["clear"] = (b, w.undo_clear if undo else w.clear_history)
            if not p:
                return
            count = "Cleared" if undo else f"{w.saved} saved" if w.saved else "Nothing saved"
            self.tile(p, path)
            ty = y + (h - text_h) / 2
            ty += self.text(p, "Clear history", x + 16, ty, b.left() - x - 28, "body", weight=560)[0] + 2
            self.text(p, count, x + 16, ty, b.left() - x - 28, "body_small", self.c["on_surface_variant"])
            shape = QPainterPath()
            shape.addRoundedRect(b, 18, 18)
            p.save()
            if not enabled:
                p.setOpacity(0.38)
            self.squeezed(p, b, "clear")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.c["surface"])
            p.drawPath(shape)
            self.state_layer(p, shape, "clear", self.c["on_surface"])
            p.setFont(type_font("button"))
            p.setPen(self.c["on_surface"])
            p.drawText(b, Qt.AlignmentFlag.AlignCenter, label)
            p.restore()
        return row

    def switch(self, p, r, name, on):
        k = self.spring("switch:" + name, 1.0 if on else 0.0)
        kc = max(0.0, min(1.0, k))
        p.setPen(QPen(mix(self.c["on_surface_variant"], self.c["primary"], kc), 2))
        p.setBrush(mix(C(T.SURFACE_HIGH), self.c["primary"], kc))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 15, 15)
        size = lerp(16, 24, kc) + 4 * self.fx(name).press.value
        c = QPointF(lerp(r.left() + 16, r.right() - 16, k), r.center().y())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix(self.c["on_surface_variant"], self.c["on_primary"], kc))
        p.drawEllipse(c, size / 2, size / 2)
        if kc > 0.3:
            draw_check(p, c, min(1.0, (kc - 0.3) / 0.6), self.c["primary"], size=5)

    def label(self, p, text, x, y):
        self.text(p, text, x + 16, y + 12 + (FIELD_H - metrics("body", 560).lineSpacing()) / 2, LABEL - 24, "body",
                  weight=560)

    def box(self, p, box, focused):
        p.setPen(QPen(self.c["primary"], 2) if focused else Qt.PenStyle.NoPen)
        p.setBrush(self.c["surface"])
        p.drawRoundedRect(box.adjusted(1, 1, -1, -1), 12, 12)

    def field_row(self, key, label, placeholder):
        def row(p, targets, x, y, width, h, path=None):
            if h is None:
                return 12 + FIELD_H + 12
            box = QRectF(x + LABEL, y + 12, width - LABEL - 12, FIELD_H)
            self.fields[key] = (box.adjusted(14, 0, -14, 0), placeholder)
            if p:
                self.tile(p, path)
                self.label(p, label, x, y)
                self.box(p, box, self.w.focused() == key)
        return row

    def option(self, p, r, title, sub, color=None):
        fm = metrics("body")
        tw = min(fm.horizontalAdvance(title) + 2, r.width())
        self.text(p, title, r.left(), r.top() + (r.height() - fm.lineSpacing()) / 2, tw, "body", color)
        room = r.width() - tw - 12
        if sub and room > 24:
            self.text(p, sub, r.right() - room, r.top() + (r.height() - metrics("body_small").lineSpacing()) / 2,
                      room, "body_small", self.c["on_surface_variant"], align="right")

    def picker_row(self, key, label):
        def row(p, targets, x, y, width, h, path=None):
            w = self.w
            open_ = w.picking == key
            if open_:
                self.shown[key] = w.visible_options()
            rows = self.shown.get(key, [])
            k = max(0.0, self.spring("expand:" + key, 1.0 if open_ else 0.0, EXPAND))
            list_h = max(1, len(rows)) * PICK_ROW + 8
            base = 12 + FIELD_H + 12
            if h is None:
                return round(base + k * (list_h + 4))
            box = QRectF(x + LABEL, y + 12, width - LABEL - 12, FIELD_H)
            targets["pick:" + key] = (box, lambda: w.toggle_picker(key))
            area = QRectF(x + 8, box.bottom() + 8, width - 16, list_h)
            if open_:
                self.picker_area = QRectF(x, y, width, h)
                self.list_area = area
                self.fields["search"] = (box.adjusted(14, 0, -36, 0), "Search")
                for i, (value, _, _) in enumerate(rows):
                    targets[f"choose:{value}"] = (QRectF(area.left() + 4, area.top() + 4 + i * PICK_ROW,
                                                         area.width() - 8, PICK_ROW), lambda v=value: w.pick(v))
            if not p:
                return
            self.tile(p, path, None)
            self.label(p, label, x, y)
            self.box(p, box, open_)
            if not open_:
                self.option(p, box.adjusted(14, 0, -36, 0), *w.display(key)[1:])
            chevron = QPointF(box.right() - 20, box.center().y())
            turn = 4 * (1 - 2 * min(1.0, k))
            p.setPen(QPen(self.c["on_surface_variant"], 1.8, cap=Qt.PenCapStyle.RoundCap,
                          join=Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPolyline([chevron + QPointF(-5, -turn / 2), chevron + QPointF(0, turn / 2),
                            chevron + QPointF(5, -turn / 2)])
            if k > 0.01:
                p.save()
                p.setClipRect(QRectF(x, box.bottom(), width, h - (box.bottom() - y)))
                p.setOpacity(p.opacity() * min(1.0, k * 1.5))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(self.c["surface"])
                p.drawRoundedRect(area, 12, 12)
                current = w.value(key)
                if not rows:
                    self.text(p, "No matches", area.left() + 14, area.top() + 4 + (PICK_ROW - metrics("body")
                              .lineSpacing()) / 2, area.width() - 28, "body", self.c["on_surface_variant"])
                for i, (value, title, sub) in enumerate(rows):
                    r = QRectF(area.left() + 4, area.top() + 4 + i * PICK_ROW, area.width() - 8, PICK_ROW)
                    it = self.fx(f"choose:{value}")
                    alpha = (T.HOVER_ALPHA * 1.4 if open_ and w.first + i == w.active else 0) + \
                        T.HOVER_ALPHA * it.hover.value + T.PRESS_ALPHA * it.press.value
                    if alpha > 0.5:
                        p.setBrush(QColor(255, 255, 255, round(alpha)))
                        p.drawRoundedRect(r, 10, 10)
                    chosen = value == current
                    self.option(p, r.adjusted(10, 0, -34, 0), title, sub, self.c["primary"] if chosen else None)
                    if chosen:
                        draw_check(p, QPointF(r.right() - 18, r.center().y()), 1.0, self.c["primary"], size=5)
                p.restore()
        return row

    def units_row(self):
        def row(p, targets, x, y, width, h, path=None):
            if h is None:
                return 12 + FIELD_H + 12
            area = QRectF(x + LABEL, y + 12, width - LABEL - 12, FIELD_H)
            seg = (area.width() - 2 * (len(UNITS) - 1)) / len(UNITS)
            current = self.w.value("units")
            if p:
                self.tile(p, path)
                self.label(p, "Units", x, y)
            for i, (value, text) in enumerate(UNITS):
                name = "units:" + value
                r = QRectF(area.left() + i * (seg + 2), area.top(), seg, FIELD_H)
                targets[name] = (r, lambda v=value: self.w.change("units", v))
                k = max(0.0, min(1.0, self.spring(name, 1.0 if value == current else 0.0)))
                if not p:
                    continue
                outer, inner = FIELD_H / 2, lerp(6, FIELD_H / 2, k)
                left, right = outer if i == 0 else inner, outer if i == len(UNITS) - 1 else inner
                shape = rrect(r, left, right, right, left)
                fg = mix(self.c["on_surface"], self.c["on_primary"], k)
                p.save()
                self.squeezed(p, r, name)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(mix(self.c["surface"], self.c["primary"], k))
                p.drawPath(shape)
                self.state_layer(p, shape, name, fg)
                p.setFont(type_font("button"))
                p.setPen(fg)
                p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
                p.restore()
        return row

    def state_layer(self, p, shape, name, color):
        it = self.fx(name)
        alpha = T.HOVER_ALPHA * it.hover.value + T.PRESS_ALPHA * it.press.value
        if alpha > 0.5:
            p.setBrush(QColor(color.red(), color.green(), color.blue(), round(min(255.0, alpha * 1.4))))
            p.drawPath(shape)

    def languages_row(self):
        def row(p, targets, x, y, width, h, path=None):
            w = self.w
            line = metrics("body_small").lineSpacing()
            chips = self.chip_layout(x + 16, y + 14 + line + 10, width - 32)
            if h is None:
                return (chips[-1][1].bottom() - y if chips else 14 + line) + 14
            if p:
                self.tile(p, path)
                self.text(p, "More languages make reading slower" if chips else "Tesseract is not installed", x + 16,
                          y + 14, width - 32, "body_small", self.c["on_surface_variant"])
            chosen = w.languages()
            for code, r in chips:
                self.toggle_chip(p, targets, "ocr:" + code, r, language_name(code) or code, code in chosen,
                                 lambda c=code: w.toggle_language(c))
        return row

    def chip_layout(self, x0, y0, width):
        out, x, y = [], x0, y0
        for code in self.w.installed():
            cw = self.measure(language_name(code) or code, "label") + 44
            if x + cw > x0 + width and x > x0:
                x, y = x0, y + T.CHIP_H + 6
            out.append((code, QRectF(x, y, cw, T.CHIP_H)))
            x += cw + 6
        return out

    def toggle_chip(self, p, targets, name, r, label, on, action):
        targets[name] = (r, action)
        k = max(0.0, min(1.0, self.spring(name, 1.0 if on else 0.0)))
        if not p:
            return
        fg = mix(self.c["on_surface"], C(T.ON_PRIMARY_CONTAINER), k)
        shape = QPainterPath()
        shape.addRoundedRect(r, T.RADIUS["chip"], T.RADIUS["chip"])
        p.save()
        self.squeezed(p, r, name)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(mix(self.c["surface"], C(T.PRIMARY_CONTAINER), k))
        p.drawPath(shape)
        self.state_layer(p, shape, name, fg)
        mark = QPointF(r.left() + 17, r.center().y())
        if k > 0.05:
            draw_check(p, mark, k, fg, size=5)
        else:
            p.setPen(QPen(self.c["on_surface_variant"], 1.6, cap=Qt.PenCapStyle.RoundCap))
            p.drawLine(mark - QPointF(5, 0), mark + QPointF(5, 0))
            p.drawLine(mark - QPointF(0, 5), mark + QPointF(0, 5))
        p.setFont(type_font("label"))
        p.setPen(fg)
        p.drawText(QRectF(r.left() + 32, r.top(), r.width() - 42, r.height()), Qt.AlignmentFlag.AlignVCenter, label)
        p.restore()

    def footer_row(self, p, targets, y):
        w = self.w
        fm = metrics("caption")
        saved = os.path.exists(settings.CONFIG_PATH)
        note = w.note()
        if not saved and not note:
            return y + self.PAD - 26
        label = short_path(settings.CONFIG_PATH) if saved else ""
        r = QRectF(self.PAD + 4, y, fm.horizontalAdvance(label) + 2 if label else 0, fm.lineSpacing())
        nw = fm.horizontalAdvance(note[0]) + 2 if note else 0
        stacked = note and label and r.width() + 24 + nw > self.inner - 8
        if saved:
            targets["file"] = (r.adjusted(-6, -4, 6, 4), lambda: w.openRequested.emit("file://" + settings.CONFIG_PATH))
        if p:
            it = self.fx("file")
            p.setFont(type_font("caption"))
            p.setPen(mix(self.c["on_surface_variant"], self.c["on_surface"], it.hover.value))
            p.drawText(QPointF(r.left(), r.top() + fm.ascent()), fm.elidedText(label, Qt.TextElideMode.ElideMiddle,
                                                                                round(self.inner - 8)))
            reach = max(0.0, min(1.05, it.lift.value))
            if reach > 0.01:
                p.drawLine(QPointF(r.left(), r.bottom() - 1), QPointF(r.left() + r.width() * reach, r.bottom() - 1))
            if note:
                text, good = note
                p.setPen(self.c["primary"] if good else C(T.ON_ERROR_CONTAINER))
                x = r.left() if stacked or not label else self.PAD + self.inner - nw - 4
                p.drawText(QPointF(x, r.top() + fm.ascent() + (fm.lineSpacing() + 4 if stacked else 0)), text)
        return y + fm.lineSpacing() * (2 if stacked else 1) + (4 if stacked else 0) + self.PAD - 6


class SettingsPanel(CardWidget):
    def __init__(self, parent, width, max_height):
        super().__init__(parent, PALETTE, ambient=False, width=width, role="hero")
        self.max_height = max_height
        self.pane_alpha = parent.pane_alpha
        self.values = copy.deepcopy(settings.config)
        self.launch = {key: self.value(key) for key in NEXT_TIME}
        self.error = None
        self.auto = QtLocale.detect(overrides=False)
        engine = ocr.active()
        self.engine = engine if hasattr(engine, "installed") else None
        self.picking = None
        self.active = self.first = 0
        self.saved = len(history.load())
        self.cleared = None
        self.focus_name = None
        self.ring = False
        self.software = backdrop.LITE and not self.launch["reduce"]
        self.card = Card(title="Settings")
        self.view = SettingsView(self, self.card, {})
        self.assets = {}
        self.contact = Field(self, "contact")
        self.search = plain(QLineEdit(self))
        self.search.hide()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.contact.installEventFilter(self)
        self.search.installEventFilter(self)
        self.search.textEdited.connect(self._searched)
        self.relayout()

    def value(self, key):
        table, *rest = KEYS[key]
        value = self.values[table][rest[0]] if rest else self.values[table]
        return value == "lite" if key == "reduce" else value

    def change(self, key, value):
        if key == "reduce":
            value = "lite" if value else "auto"
        table, *rest = KEYS[key]
        if (self.values[table][rest[0]] if rest else self.values[table]) == value:
            return
        try:
            settings.save({table: {rest[0]: value}} if rest else {table: value})
            self.error = None
        except OSError as e:
            self.error = f"Could not save: {e.strerror or e}"
        self.values = copy.deepcopy(settings.config)
        if table == "locale":
            locale.install(QtLocale.detect())
        self.relayout()

    def options(self, key):
        if key == "language":
            return [("", "Automatic", language_name(self.auto.language) or self.auto.language), *language_options()]
        return [("", "Automatic", currencies.NAMES.get(self.auto.currency, self.auto.currency)), *currency_options()]

    def display(self, key):
        value = self.value(key)
        found = next((o for o in self.options(key) if o[0] == value), None)
        return found or (value, value, "")

    def matches(self):
        query = self.search.text().strip().lower()
        options = self.options(self.picking)
        if not query:
            return options

        def rank(option):
            value, title, sub = option
            words = f"{title} {sub} {value}".lower().replace("(", " ").split()
            if title.lower().startswith(query) or value.lower() == query:
                return 0
            if any(word.startswith(query) for word in words):
                return 1
            return 2 if query in title.lower() or query in sub.lower() else 3
        ranked = sorted(((rank(o), i, o) for i, o in enumerate(options)), key=lambda r: r[:2])
        return [o for score, _, o in ranked if score < 3]

    def visible_options(self):
        return self.matches()[self.first:self.first + PICK_ROWS]

    def toggle_picker(self, key):
        if self.picking == key:
            self.close_picker()
            return
        self.picking = key
        self.search.clear()
        values = [o[0] for o in self.options(key)]
        self.active = values.index(self.value(key)) if self.value(key) in values else 0
        self.first = max(0, min(self.active - PICK_ROWS // 2, len(values) - PICK_ROWS))
        self.search.show()
        self.search.setFocus()
        self.relayout()

    def picking_target(self):
        return f"pick:{self.picking}" if self.picking else None

    def close_picker(self):
        if self.picking is None:
            return
        if self.search.hasFocus():
            self.focus_name = self.picking_target()
            self.setFocus()
        self.picking = None
        self.search.hide()
        self.relayout()

    def pick(self, value):
        key = self.picking
        self.close_picker()
        if key is not None:
            self.change(key, value)

    def scroll_list(self, step):
        self.first = max(0, min(self.first + step, len(self.matches()) - PICK_ROWS))
        self.refresh()

    def move_active(self, step):
        count = len(self.matches())
        if not count:
            return
        self.active = max(0, min(self.active + step, count - 1))
        if self.active < self.first:
            self.first = self.active
        elif self.active >= self.first + PICK_ROWS:
            self.first = self.active - PICK_ROWS + 1
        self.refresh()

    def _searched(self, _):
        self.active = self.first = 0
        self.relayout()

    def order(self):
        names = [n for n in self._targets if not n.startswith("choose:")]
        names.insert(names.index("file") if "file" in names else len(names), "contact")
        return names

    def navigate(self, step):
        names = self.order()
        if self.focus_name in names:
            name = names[(names.index(self.focus_name) + step) % len(names)]
        else:
            name = names[0 if step > 0 else -1]
        self.focus_on(name, True)

    def focus_on(self, name, ring):
        self.focus_name, self.ring = name, ring
        if name == "contact":
            self.contact.setFocus()
            self.contact.selectAll()
        elif not self.hasFocus():
            self.setFocus()
        self.reveal(name)
        self.refresh()

    def reveal(self, name):
        rect = self._targets.get(name, (None,))[0] if name != "contact" else self.view.fields.get("contact", (None,))[0]
        limit = max(0.0, self.view.content - self.height())
        if rect is None or limit <= 0:
            return
        shift = min(0.0, rect.top() - 12) or max(0.0, rect.bottom() + 12 - self.height())
        scroll = min(limit, max(0.0, self.view.scroll + shift))
        if scroll != self.view.scroll:
            self.view.scroll = scroll
            self.relayout()

    def sibling(self, step):
        prefix = self.focus_name.partition(":")[0] + ":" if self.focus_name else None
        if prefix not in ("units:", "ocr:"):
            return
        names = [n for n in self._targets if n.startswith(prefix)]
        i = names.index(self.focus_name) + step
        if 0 <= i < len(names):
            self.focus_on(names[i], True)

    def activate(self):
        entry = self._targets.get(self.focus_name)
        if entry is None:
            return
        self.firing = self.focus_name
        try:
            entry[1]()
        finally:
            self.firing = None

    def event(self, e):
        if e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            self.navigate(-1 if e.key() == Qt.Key.Key_Backtab or e.modifiers() & Qt.KeyboardModifier.ShiftModifier
                          else 1)
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        key = e.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.sibling(1 if key == Qt.Key.Key_Right else -1)
        elif key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter) and not e.isAutoRepeat():
            if self.focus_name is not None:
                self.ring = True
                self.activate()
        else:
            return super().keyPressEvent(e)
        e.accept()

    def eventFilter(self, obj, e):
        if obj is self.contact and e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Tab,
                                                                                    Qt.Key.Key_Backtab):
            self.navigate(-1 if e.key() == Qt.Key.Key_Backtab else 1)
            return True
        if obj is self.search and self.picking:
            if e.type() == QEvent.Type.KeyPress and e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                self.close_picker()
                return True
            if e.type() == QEvent.Type.ShortcutOverride and e.key() == Qt.Key.Key_Escape:
                e.accept()
                return True
            if e.type() == QEvent.Type.KeyPress:
                key = e.key()
                if key == Qt.Key.Key_Escape:
                    self.close_picker()
                    return True
                if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    self.move_active(1 if key == Qt.Key.Key_Down else -1)
                    return True
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    options = self.matches()
                    if options:
                        self.pick(options[self.active][0])
                    return True
        return super().eventFilter(obj, e)

    def mousePressEvent(self, e):
        if self.picking and not self.view.picker_area.contains(e.position()):
            self.close_picker()
        name = self._target_at(e.position())
        self.ring = False
        if name is not None and not name.startswith("choose:"):
            self.focus_name = name
        super().mousePressEvent(e)

    def clear_history(self):
        self.cleared = history.load()
        history.clear()
        self.saved = 0
        self.relayout()

    def undo_clear(self):
        history.restore(self.cleared or [])
        self.cleared = None
        self.saved = len(history.load())
        self.relayout()

    def installed(self):
        if self.engine is None:
            return []
        return sorted(self.engine.installed(), key=lambda c: language_name(c) or c)

    def languages(self):
        return self.value("ocr") or self.engine.default_languages()

    def toggle_language(self, code):
        chosen = self.languages()
        chosen = [c for c in chosen if c != code] if code in chosen else [*chosen, code]
        if chosen:
            self.change("ocr", [] if set(chosen) == set(self.engine.default_languages()) else chosen)

    def note(self):
        if self.error:
            return self.error, False
        if any(self.value(key) != self.launch[key] for key in NEXT_TIME):
            return "Applies next time", True
        return None

    def focused(self):
        return "contact" if self.contact.hasFocus() else None

    def commit(self):
        if self.contact.isModified():
            self.contact.commit()

    def refresh(self):
        self._layout(None)
        self.place_fields()
        self._wake()
        self.update()

    def reset(self):
        self.close_picker()
        self.cleared = None
        self.focus_name, self.ring = None, False
        self.saved = len(history.load())
        if self.view.scroll:
            self.view.scroll = 0.0
            self.relayout()

    def relayout(self):
        old = self.geometry()
        self.resize(self.WIDTH, self._layout(None))
        self.place_fields()
        if self.isVisible():
            self._wake()
        self.update()
        if self.parentWidget() is not None and self.height() != old.height():
            self.parentWidget().update(old.united(self.geometry()).adjusted(-48, -40, 48, 64))

    def place_fields(self):
        for key, edit in (("contact", self.contact), ("search", self.search)):
            box, placeholder = self.view.fields.get(key, (None, ""))
            if box is None:
                edit.hide()
                continue
            edit.setPlaceholderText(placeholder)
            edit.setGeometry(box.toRect())
            edit.setVisible(box.bottom() > 0 and box.top() < self.height())
