import math
import re
import time
from datetime import date, timedelta

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap

import card_tokens as T
from card_data import Action, money_str
from locale_profile import PROFILE
from card_shapes import STARS, draw_weather_icon, glyph, shape_path, star_path
from context_card import InfoCard, wrap

C = lambda h, a=255: QColor(*T.hx(h), a)
FLEX, FALLBACK = "Google Sans Flex", "Google Sans"


def font(px, weight=450, rond=100, wdth=100, opsz=None):
    f = QFont()
    f.setFamilies([FLEX, FALLBACK])
    f.setPixelSize(round(px))
    f.setWeight(QFont.Weight(min(900, max(100, round(weight / 100) * 100))))
    f.setVariableAxis(QFont.Tag.fromString("wght"), weight)
    f.setVariableAxis(QFont.Tag.fromString("ROND"), rond)
    f.setVariableAxis(QFont.Tag.fromString("wdth"), wdth)
    f.setVariableAxis(QFont.Tag.fromString("opsz"), opsz or min(144, max(6, px)))
    return f


def rrect(rect, tl, tr, br, bl):
    p = QPainterPath()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    p.moveTo(x + tl, y)
    p.lineTo(x + w - tr, y); p.quadTo(x + w, y, x + w, y + tr)
    p.lineTo(x + w, y + h - br); p.quadTo(x + w, y + h, x + w - br, y + h)
    p.lineTo(x + bl, y + h); p.quadTo(x, y + h, x, y + h - bl)
    p.lineTo(x, y + tl); p.quadTo(x, y, x + tl, y)
    p.closeSubpath()
    return p


GLYPHS = {"Population": "people", "Area": "area", "Elevation": "mountain", "Founded": "calendar", "Capital": "capital",
          "Currency": "coins", "Languages": "chat", "Calling code": "phone", "Developer": "person", "Latest version": "tag",
          "Licence": "tag", "Written in": "code", "First released": "calendar", "Born": "calendar", "Died": "calendar",
          "Occupation": "person", "Citizenship": "capital", "Country": "capital", "Headquarters": "capital",
          "Chief executive": "person", "Employees": "people", "Industry": "tag"}
AQI_STATUS = [(20, "Good", "#0ca30c"), (40, "Fair", "#0ca30c"), (60, "Moderate", "#fab219"),
              (80, "Poor", "#ec835a"), (10 ** 6, "Very poor", "#d03b3b")]


TRANSITION = 0.55


def spring(p, damping=0.8, stiffness=380.0, duration=TRANSITION):
    if p >= 1.0:
        return 1.0
    t, w = p * duration, math.sqrt(stiffness)
    wd = w * math.sqrt(1 - damping ** 2)
    return 1 - math.exp(-damping * w * t) * (math.cos(wd * t) + damping * w / wd * math.sin(wd * t))


def ramp(x, start, length):
    return min(1.0, max(0.0, (x - start) / length))


class ExpressiveCard(InfoCard):
    PAD = 20
    MARK = QColor("#4285F4")

    def __init__(self, parent, font_fn, palette, ambient=True, width=404, role="secondary"):
        super().__init__(parent, font_fn, palette, ambient)
        self.WIDTH = width
        self.role = role
        self._media_cache = {}
        self._trans_t0 = None
        screen = QGuiApplication.primaryScreen()
        rate = (screen.refreshRate() if screen else 60.0) or 60.0
        self._trans_timer = QTimer(self, interval=max(4, round(1000 / rate)), timeout=self._trans_step)
        self.resize(width, 120)

    def tint(self):
        k = self.info.kind if self.info else ""
        if k == "weather":
            return T.SKY_DAY if self.info.is_day else T.SKY_NIGHT
        fam = {"place": "blue", "entity": "blue", "term": "blue", "translation": "blue", "money": "green",
               "package": "green", "holidays": "red", "date": "red", "time": "blue"}.get(k, "neutral")
        return T.TINT[fam]

    def tile(self):
        return T.mixh(self.tint(), "#FFFFFF", 0.065)

    def radius(self):
        return 32 if self.role == "hero" else 24

    def paintEvent(self, e):
        if self._trans_t0 is not None:
            return self._paint_transition(QPainter(self))
        if self.loading or not self.info:
            return self._paint_now(QPainter(self))
        key = (self.size().width(), self.size().height(), self._hover,
               round(self._mouse.x()) if self._hover and self._hover.startswith("series") else None)
        if getattr(self, "_cache_key", None) != key:
            pm = QPixmap(self.size() * self.devicePixelRatioF()); pm.setDevicePixelRatio(self.devicePixelRatioF())
            pm.fill(Qt.GlobalColor.transparent)
            self._paint_now(QPainter(pm))
            self._cache, self._cache_key = pm, key
        QPainter(self).drawPixmap(0, 0, self._cache)

    def set_info(self, info):
        animate = self.loading and self.isVisible() and self.ambient
        h0, loader_t = self.height(), time.monotonic() - self._t0
        self._cache_key = None
        super().set_info(info)
        if not animate:
            return
        self._h0, self._h1 = h0, self.height()
        self._loader_t = loader_t
        pm = QPixmap(self.size() * self.devicePixelRatioF())
        pm.setDevicePixelRatio(self.devicePixelRatioF())
        pm.fill(Qt.GlobalColor.transparent)
        self._paint_now(QPainter(pm))
        self._final = pm
        self._trans_t0 = time.monotonic()
        self.resize(self.WIDTH, h0)
        self._trans_timer.start()

    def transitioning(self):
        return self._trans_t0 is not None

    def layout_height(self):
        return self._h1 if self._trans_t0 is not None else self.height()

    def _trans_step(self):
        raw = min(1.0, (time.monotonic() - self._trans_t0) / TRANSITION)
        self.resize(self.WIDTH, round(self._h0 + (self._h1 - self._h0) * spring(raw)))
        self.update()
        if raw >= 1.0:
            self._trans_timer.stop()
            self._trans_t0 = None
            self._final = None
            self.resize(self.WIDTH, self._h1)
            self.update()

    def _paint_transition(self, p):
        raw = min(1.0, (time.monotonic() - self._trans_t0) / TRANSITION)
        e = spring(raw)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        clip = QPainterPath()
        clip.addRoundedRect(r, self.radius(), self.radius())
        tint = C(self.tint())
        surface = self.c["surface"]
        k = ramp(raw, 0.0, 0.5)
        bg = QColor.fromRgbF(*(a + (b - a) * k for a, b in zip(surface.getRgbF()[:3], tint.getRgbF()[:3])))
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.setBrush(bg)
        p.drawPath(clip)
        p.save()
        p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        p.setOpacity(ramp(raw, 0.12, 0.45))
        p.drawPixmap(0, 0, self._final)
        p.restore()
        start = QRectF(self.PAD, 34, 56, 56)
        end = QRectF(self.PAD - 2, self.PAD, 92, 92) if self.info.kind in ("place", "entity") else start
        rect = QRectF(start.x() + (end.x() - start.x()) * e, start.y() + (end.y() - start.y()) * e,
                      start.width() + (end.width() - start.width()) * e, start.height() + (end.height() - start.height()) * e)
        alpha = 1.0 - ramp(raw, 0.35, 0.35)
        if alpha > 0:
            p.setOpacity(alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(C(T.PRIMARY_CONTAINER))
            p.drawPath(self._loader_path(self._loader_t, rect, settle=e))
        label_alpha = 1.0 - ramp(raw, 0.0, 0.22)
        if label_alpha > 0:
            p.setOpacity(label_alpha)
            self._paint_loader_label(p, start)
        p.setOpacity(1.0)

    def _paint_now(self, p):
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(C(self.tint()) if self.info else self.c["surface"])
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.drawRoundedRect(r, self.radius(), self.radius())
        if self.loading:
            self._paint_loader(p)
        elif self.info:
            self._layout(paint=p)

    LOADER_SEQ = ["cookie9", "soft_burst", "cookie4", "clover4", "sunny"]

    def _loader_path(self, t, rect, settle=0.0):
        seq = self.LOADER_SEQ
        i = int(t / 0.65) % len(seq)
        a, b = STARS[seq[i]], STARS[seq[(i + 1) % len(seq)]]
        k = min(1.0, (t / 0.65) % 1.0 / 0.6)
        k = 1 - (1 - k) ** 3
        cookie = STARS["cookie9"]
        spin = t * 2.2
        step = 2 * math.pi / cookie[0]
        spin += (round(spin / step) * step - spin) * settle
        cx, cy = rect.center().x(), rect.center().y()
        R = rect.width() / 2 * (26 / 28 + (1 - 26 / 28) * settle)

        def radius(shape, th):
            n, inner, sharp = shape
            return inner + (1 - inner) * ((1 + math.cos(n * (th - spin + math.pi / 2))) / 2) ** sharp

        path = QPainterPath()
        for j in range(181):
            th = 2 * math.pi * j / 180
            moving = radius(a, th) * (1 - k) + radius(b, th) * k
            r = R * (moving * (1 - settle) + radius(cookie, th) * settle)
            pt = QPointF(cx + r * math.cos(th), cy + r * math.sin(th))
            path.moveTo(pt) if j == 0 else path.lineTo(pt)
        path.closeSubpath()
        return path

    def _paint_loader(self, p):
        rect = QRectF(self.PAD, 34, 56, 56)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C(T.PRIMARY_CONTAINER))
        p.drawPath(self._loader_path(time.monotonic() - self._t0, rect))
        self._paint_loader_label(p, rect)

    def _paint_loader_label(self, p, rect):
        f = font(15, 560); p.setFont(f); p.setPen(self.c["on_surface"])
        p.drawText(QPointF(rect.right() + 18, 58), getattr(self, "loading_label", "Looking it up…"))
        f = font(12, 480); p.setFont(f); p.setPen(self.c["on_surface_variant"])
        p.drawText(QPointF(rect.right() + 18, 80), "Wikipedia · Wikidata · OpenStreetMap")

    def set_loading(self, label="Looking it up…"):
        super().set_loading()
        self.loading_label = label
        self.resize(self.WIDTH, 124)

    def _t(self, p, s, px, w, color, x, y, width=None, lines=1, rond=100, wdth=100, align="left", fit=False):
        width = width or (self.WIDTH - 2 * self.PAD)
        f = font(px, w, rond, wdth)
        fm = QFontMetrics(f)
        if fit and lines == 1:
            while fm.horizontalAdvance(s) > width and wdth > 80:
                wdth -= 5; f = font(px, w, rond, wdth); fm = QFontMetrics(f)
        ls = [fm.elidedText(s, Qt.TextElideMode.ElideRight, int(width))] if lines == 1 else wrap(fm, s, width, lines)
        if p:
            p.setFont(f); p.setPen(color)
            for i, line in enumerate(ls):
                lx = x
                if align == "right":
                    lx = x + width - fm.horizontalAdvance(line)
                elif align == "center":
                    lx = x + (width - fm.horizontalAdvance(line)) / 2
                p.drawText(QPointF(lx, y + fm.ascent() + i * fm.lineSpacing()), line)
        return len(ls) * fm.lineSpacing(), (max(fm.horizontalAdvance(l) for l in ls) if ls else 0)

    def _pill(self, p, label, x, y, bg, fg, h=30, icon=None, px=13, weight=560, dot=None, name=None, targets=None, payload=None):
        f = font(px, weight); fm = QFontMetrics(f)
        lead = (22 if icon or dot else 0)
        w = fm.horizontalAdvance(label) + 24 + lead
        r = QRectF(x, y, w, h)
        if targets is not None and name:
            targets[name] = (r, (lambda: self.copyRequested.emit(payload)) if payload else None)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(bg) if isinstance(bg, str) else bg)
            p.drawRoundedRect(r, 8 if h <= 32 else h / 2, 8 if h <= 32 else h / 2)
            if name and self._hover == name:
                p.setBrush(QColor(255, 255, 255, 18)); p.drawRoundedRect(r, 8, 8)
            if dot:
                p.setBrush(C(dot)); p.drawEllipse(QPointF(x + 16, y + h / 2), 5, 5)
            if icon:
                glyph(p, icon, QRectF(x + 9, y + (h - 15) / 2, 15, 15), fg)
            p.setFont(f); p.setPen(fg)
            p.drawText(QRectF(x + 12 + lead, y, w - 24 - lead, h), Qt.AlignmentFlag.AlignVCenter, label)
        return w

    def _buttons(self, p, actions, x, y, targets, width=None):
        if not actions:
            return y
        f = font(13, 600); fm = QFontMetrics(f)
        widths = [fm.horizontalAdvance(a.label) + 32 for a in actions]
        h, gap = 40, 2
        cx = x
        for i, (a, w) in enumerate(zip(actions, widths)):
            r = QRectF(cx, y, w, h)
            first, last = i == 0, i == len(actions) - 1
            name = f"action{i}"
            emit = (lambda a=a: self.openRequested.emit(a.payload)) if a.kind == "open" else (lambda a=a: self.copyRequested.emit(a.payload))
            targets[name] = (r, emit)
            if p:
                hover = self._hover == name
                big, small = h / 2, (h / 2 if hover else 8)
                path = rrect(r, big if first else small, big if last else small, big if last else small, big if first else small)
                bg = self.c["primary"] if first else C(self.tile())
                fg = self.c["on_primary"] if first else self.c["on_surface"]
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(bg); p.drawPath(path)
                p.setFont(f); p.setPen(fg); p.drawText(r, Qt.AlignmentFlag.AlignCenter, a.label)
            cx += w + gap
        return y + h

    def _source(self, p, y, targets, text=None):
        info = self.info
        label = text or info.source
        if not label:
            return y - 6
        f = font(11.5, 520); fm = QFontMetrics(f)
        r = QRectF(self.PAD, y, fm.horizontalAdvance(label) + 2, fm.lineSpacing())
        if info.url:
            targets["source"] = (r.adjusted(-6, -4, 6, 4), lambda: self.openRequested.emit(info.url))
        if p:
            p.setFont(f); p.setPen(self.c["on_surface"] if self._hover == "source" else self.c["on_surface_variant"])
            p.drawText(QPointF(r.left(), r.top() + fm.ascent()), label)
        return y + fm.lineSpacing()

    def _media(self, img, shape, size, cover=True):
        key = (id(img), shape, size)
        if key not in self._media_cache:
            out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied); out.fill(0)
            q = QPainter(out); q.setRenderHint(QPainter.RenderHint.Antialiasing); q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            q.setClipPath(shape_path(shape, QRectF(0, 0, size, size)))
            if cover:
                side = min(img.width(), img.height())
                src = QRectF((img.width() - side) / 2, (img.height() - side) / 2 * 0.6, side, side)
                q.drawImage(QRectF(0, 0, size, size), img, src)
            else:
                q.fillRect(QRectF(0, 0, size, size), QColor("#F1F3F4"))
                s = size * 0.68
                sc = min(s / img.width(), s / img.height())
                w, h = img.width() * sc, img.height() * sc
                q.drawImage(QRectF((size - w) / 2, (size - h) / 2, w, h), img)
            q.end()
            self._media_cache[key] = out
        return self._media_cache[key]

    def _layout(self, paint):
        k = self.info.kind
        fn = {"place": self._hero, "entity": self._hero, "facts": self._facts, "weather": self._weather,
              "money": self._money, "holidays": self._holidays, "time": self._time, "date": self._date,
              "color": self._color, "nearby": self._nearby, "trends": self._trends, "repo": self._repo,
              "package": self._package}.get(k)
        if fn is None:
            return super()._layout(paint)
        targets = {}
        h = fn(paint, targets)
        self._targets = targets
        return int(h)

    def _hero(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        y = pad
        img = info.image
        shape = info.image_shape or "cookie9"
        media = 92
        if img is not None and p:
            p.drawImage(QPointF(pad - 2, y), self._media(img, shape, media, cover=shape != "logo_squircle"))
        elif media and p:
            r = QRectF(pad - 2, y, media, media)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.PRIMARY_CONTAINER)); p.drawPath(star_path(r, *STARS["cookie9"]))
            self._t(p, info.title[:1].upper(), 40, 640, C(T.ON_PRIMARY_CONTAINER), r.left(), r.top() + 20, r.width(), align="center")
        tx = pad + (media + 16 if media else 0)
        tw = width - (media + 16 if media else 0)
        ty = y + (4 if media else 0)
        h, _ = self._t(p, info.title, 28, 640, c["on_surface"], tx, ty, tw, lines=2, wdth=100, fit=True)
        ty += h + 2
        if info.translation:
            h, tw_ = self._t(p, info.translation, 17, 560, c["primary"], tx, ty, tw)
            targets["copy"] = (QRectF(tx - 4, ty - 2, tw_ + 34, h + 4), lambda: self.copyRequested.emit(info.translation))
            if p and self._hover == "copy":
                self._paint_copy_icon(p, QRectF(tx + tw_ + 4, ty - 4, 28, 28), True)
            ty += h + 2
        if info.description:
            ty += self._t(p, info.description, 13, 480, c["on_surface_variant"], tx, ty, tw, lines=2)[0]
        y = max(y + media, ty) + 14
        if info.definition:
            y += self._t(p, info.definition, 14.5, 430, c["on_surface"], pad, y, width, lines=3 if info.map_image is None else 2)[0] + 14
        if info.map_image is not None:
            m = QRectF(pad, y, width, 132)
            if p:
                clip = QPainterPath(); clip.addRoundedRect(m, 20, 20)
                p.save(); p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                img_ = info.map_image
                src_h = img_.width() * m.height() / m.width()
                p.drawImage(m, img_, QRectF(0, (img_.height() - src_h) / 2, img_.width(), src_h))
                af = font(9.5, 520); p.setFont(af); fm = QFontMetrics(af)
                a = "© OpenStreetMap"; aw = fm.horizontalAdvance(a) + 12
                ar = QRectF(m.right() - aw - 8, m.bottom() - fm.height() - 8, aw, fm.height() + 2)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 110)); p.drawRoundedRect(ar, 6, 6)
                p.setPen(QColor(255, 255, 255, 170)); p.drawText(ar, Qt.AlignmentFlag.AlignCenter, a)
                p.restore()
            y = m.bottom() + 14
        if info.actions:
            y = self._buttons(p, info.actions, pad, y, targets) + 14
        return self._source(p, y, targets) + pad - 4

    def _facts(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        y = pad
        self._t(p, info.title, 16, 620, c["on_surface"], pad, y, width)
        self._t(p, info.source, 11.5, 520, c["on_surface_variant"], pad, y + 3, width, align="right")
        if info.url:
            targets["source"] = (QRectF(pad + width - 70, y, 70, 20), lambda: self.openRequested.emit(info.url))
        y += 32
        gap = 8
        half = (width - gap) / 2
        vf = QFontMetrics(font(19, 620))
        row_h = 70
        items = [(label, value, vf.horizontalAdvance(value) > half - 28) for label, value in info.rows]
        narrow = [it for it in items if not it[2]]
        if len(narrow) % 2:
            last = narrow[-1]; items[items.index(last)] = (last[0], last[1], True)
        tiles, pending = [], None
        for label, value, wide in items:
            if wide:
                tiles.append((QRectF(pad, y, width, row_h), label, value)); y += row_h + gap
            elif pending is None:
                pending = (label, value)
            else:
                tiles.append((QRectF(pad, y, half, row_h), *pending)); tiles.append((QRectF(pad + half + gap, y, half, row_h), label, value))
                pending = None; y += row_h + gap
        bottom = y - gap
        for i, (r, label, value) in enumerate(tiles):
            name = f"row{i}"
            targets[name] = (r, lambda v=value: self.copyRequested.emit(v))
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
                p.drawRoundedRect(r, 16, 16)
                if self._hover == name:
                    p.setBrush(QColor(255, 255, 255, 14)); p.drawRoundedRect(r, 16, 16)
                glyph(p, GLYPHS.get(label, "tag"), QRectF(r.left() + 14, r.top() + 13, 14, 14), c["on_surface_variant"])
            self._t(p, label, 12, 540, c["on_surface_variant"], r.left() + 34, r.top() + 12, r.width() - 48)
            self._t(p, value, 19, 620, c["on_surface"], r.left() + 14, r.top() + 34, r.width() - 28, fit=True)
        y = bottom + 14
        if info.actions:
            y = self._buttons(p, info.actions, pad, y, targets) + 6
        return y + pad - 6

    def _weather(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        now = info.now or {}
        day = info.is_day
        y = pad
        place = info.title.replace("Weather in ", "")
        self._t(p, place, 15, 620, c["on_surface"], pad, y, width)
        lt = next((s for s in info.chips if s.startswith("Local time")), "")
        if lt:
            fm = QFontMetrics(font(12.5, 520))
            tw = fm.horizontalAdvance(lt[11:] + " local")
            if p:
                glyph(p, "clock", QRectF(pad + width - tw - 19, y + 2, 14, 14), c["on_surface_variant"])
            self._t(p, lt[11:] + " local", 12.5, 520, c["on_surface_variant"], pad, y + 1, width, align="right")
        y += 28
        icon = QRectF(pad - 4, y, 104, 104)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 20))
            p.drawPath(star_path(icon, *STARS["cookie9"]))
            draw_weather_icon(p, now.get("code", 3), icon.adjusted(22, 22, -22, -22), day)
        tx = icon.right() + 18
        th, tw = self._t(p, info.value, 72, 430, c["on_surface"], tx, y - 8, 200, rond=100, wdth=105)
        self._t(p, info.description, 16, 580, c["on_surface"], tx, y + 70, width - (tx - pad))
        days = info.chart["days"]
        sub = f"Feels {round(now.get('feels', 0))}°  ·  H {round(days[0]['hi'])}°  L {round(days[0]['lo'])}°" if now else ""
        self._t(p, sub, 13, 500, c["on_surface_variant"], tx, y + 92, width - (tx - pad))
        y = icon.bottom() + 14
        y = self._forecast2(p, days, QRectF(pad, y, width, 0), targets) + 12
        x = pad
        for s in info.chips:
            if s.startswith("Air"):
                m = re.search(r"\((\d+)\)", s); v = int(m.group(1)) if m else 0
                limit, word, col = next(a for a in AQI_STATUS if v <= a[0])
                x += self._pill(p, f"Air {word} · {v}", x, y, self.tile(), c["on_surface"], dot=col) + 6
            elif s.startswith("Sunrise") or s.startswith("Sunset"):
                x += self._pill(p, s.split()[1], x, y, self.tile(), c["on_surface"], icon=s.split()[0].lower()) + 6
        y += 30 + 14
        return self._source(p, y, targets) + pad - 4

    def _forecast2(self, p, days, area, targets):
        c = self.c
        n = len(days); col = area.width() / n
        lo, hi = min(d["lo"] for d in days), max(d["hi"] for d in days)
        span = max(hi - lo, 1.0)
        day_h, icon_h, top_l, bars_h, bot_l = 18, 26, 18, 70, 18
        y0 = area.top() + day_h + 4 + icon_h + 4 + top_l
        y1 = y0 + bars_h
        ty = lambda t: y1 - (t - lo) / span * bars_h
        hot = max(range(n), key=lambda i: days[i]["hi"]); cold = min(range(n), key=lambda i: days[i]["lo"])
        bottom = y1 + bot_l
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 16))
            p.drawRoundedRect(QRectF(area.left() + 2, area.top() - 4, col - 4, bottom - area.top() + 6), 16, 16)
        for i, d in enumerate(days):
            cx = area.left() + col * (i + 0.5)
            name = f"day{i}"
            targets[name] = (QRectF(area.left() + col * i, area.top(), col, bottom - area.top()), None)
            if not p:
                continue
            p.setFont(font(12, 640 if i == 0 else 520)); p.setPen(c["on_surface"] if i == 0 else c["on_surface_variant"])
            p.drawText(QRectF(cx - col / 2, area.top(), col, day_h), Qt.AlignmentFlag.AlignCenter, d["label"] if i else "Now")
            draw_weather_icon(p, d.get("code"), QRectF(cx - icon_h / 2, area.top() + day_h + 4, icon_h, icon_h), True)
            bar = QRectF(cx - 5, ty(d["hi"]), 10, max(10.0, ty(d["lo"]) - ty(d["hi"])))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.MARK); p.drawRoundedRect(bar, 5, 5)
            p.setFont(font(12.5, 600)); p.setPen(c["on_surface"])
            if i == hot:
                p.drawText(QRectF(cx - col / 2, bar.top() - top_l, col, top_l - 2), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"{round(d['hi'])}°")
            if i == cold:
                p.drawText(QRectF(cx - col / 2, bar.bottom() + 2, col, bot_l), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{round(d['lo'])}°")
        return bottom

    def _money(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        y = pad
        series = info.chart["series"][0] if info.chart and info.chart.get("type") == "lines" else None
        if series:
            code = info.description.replace("1 ", "")
            self._t(p, info.title, 16, 620, c["on_surface"], pad, y, width)
            self._pill(p, f"1 {code}", pad + width - QFontMetrics(font(12, 600)).horizontalAdvance(f"1 {code}") - 24, y - 4, self.tile(), c["on_surface_variant"], h=26, px=12, weight=600)
            y += 26
        else:
            self._t(p, info.title, 16, 560, c["on_surface_variant"], pad, y, width)
            y += 24
        vh, vw = self._t(p, info.value, 52, 520, c["on_surface"], pad, y, width - 44, rond=100, wdth=100, fit=True)
        copy = QRectF(pad + width - 40, y + (vh - 40) / 2, 40, 40)
        targets["value"] = (copy, lambda: self.copyRequested.emit(info.value))
        if p:
            self._paint_copy_icon(p, copy, self._hover == "value")
        y += vh + 4
        if series:
            pts = series["points"]
            first, last = pts[0][1], pts[-1][1]
            delta = last - first
            pct = delta / first * 100
            arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
            label = f"{arrow} {money_str(abs(delta), PROFILE.currency)}  ({'+' if pct > 0 else ''}{PROFILE.money.toString(pct, 'f', 1)}%) in 30 days"
            self._pill(p, label, pad, y, self.tile(), c["on_surface"], h=28, px=12.5)
            y += 28 + 14
            plot = QRectF(pad + 2, y, width - 4, 64)
            if p:
                vs = [v for _, v in pts]; lo_, hi_ = min(vs), max(vs); pv = (hi_ - lo_) * 0.1 or 0.01
                lo_, hi_ = lo_ - pv, hi_ + pv
                pos = lambda i, v: QPointF(plot.left() + plot.width() * i / (len(pts) - 1), plot.bottom() - (v - lo_) / (hi_ - lo_) * plot.height())
                line = QPainterPath(pos(0, pts[0][1]))
                for i, (_, v) in enumerate(pts[1:], 1):
                    line.lineTo(pos(i, v))
                wash = QPainterPath(line); wash.lineTo(plot.bottomRight()); wash.lineTo(plot.bottomLeft()); wash.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(66, 133, 244, 26)); p.drawPath(wash)
                p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(self.MARK, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)); p.drawPath(line)
                end = pos(len(pts) - 1, pts[-1][1])
                p.setPen(QPen(C(self.tint()), 2)); p.setBrush(self.MARK); p.drawEllipse(end, 5, 5)
                p.setFont(font(11, 520)); p.setPen(c["on_surface_variant"])
                axis = QRectF(plot.left(), plot.bottom() + 4, plot.width(), 14)
                p.drawText(axis, Qt.AlignmentFlag.AlignLeft, str(pts[0][0])); p.drawText(axis, Qt.AlignmentFlag.AlignRight, str(pts[-1][0]))
            targets["series0"] = (plot, None)
            y = plot.bottom() + 26
        x = pad
        for i, (label, value) in enumerate(info.rows):
            text = f"{label} = {value}" if series else value
            w = QFontMetrics(font(13, 560)).horizontalAdvance(text) + 24
            if x + w > pad + width and x > pad:
                x, y = pad, y + 38
            x += self._pill(p, text, x, y, self.tile(), c["on_surface"], h=32, name=f"row{i}", targets=targets, payload=value) + 6
        if not series:
            rate = info.chips[0] if info.chips else ""
            if rate:
                w = QFontMetrics(font(13, 560)).horizontalAdvance(rate) + 24
                if x + w > pad + width:
                    x, y = pad, y + 38
                self._pill(p, rate, x, y, self.tile(), c["on_surface_variant"], h=32)
        y += 32 + 14
        return self._source(p, y, targets) + pad - 4

    def _holidays(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        y = pad
        self._t(p, info.title, 16, 620, c["on_surface"], pad, y, width)
        y += 32
        parsed = [(it["date"], it["name"], it["local"], it["when"]) for it in info.items]
        d, name, local, when = parsed[0]
        day, mon = d.split()
        badge = QRectF(pad - 2, y, 84, 84)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.ERROR_CONTAINER))
            p.drawPath(star_path(badge, *STARS["cookie9"]))
        self._t(p, day, 32, 680, C(T.ON_ERROR_CONTAINER), badge.left(), badge.top() + 12, badge.width(), align="center", wdth=110)
        self._t(p, mon.upper(), 11.5, 760, C(T.ON_ERROR_CONTAINER), badge.left(), badge.top() + 52, badge.width(), align="center")
        tx = badge.right() + 16; tw = width - (tx - pad)
        ty = y + 2
        ty += self._t(p, name, 18, 620, c["on_surface"], tx, ty, tw, lines=2)[0]
        if local:
            ty += self._t(p, local, 13, 470, c["on_surface_variant"], tx, ty, tw)[0]
        ty += 6
        n = re.search(r"\d+", when)
        self._pill(p, when if not n else f"in {n.group(0)} days", tx, ty, T.mixh(T.ERROR_CONTAINER, T.SURFACE, 0.35), C(T.ON_ERROR_CONTAINER), h=28, px=12.5, weight=620)
        y = max(badge.bottom(), ty + 28) + 14
        for i, (d, name, local, when) in enumerate(parsed[1:]):
            if p:
                f = font(12, 620)
                chip = QRectF(pad, y + 6, 62, 28)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile())); p.drawRoundedRect(chip, 8, 8)
                p.setFont(f); p.setPen(c["on_surface"]); p.drawText(chip, Qt.AlignmentFlag.AlignCenter, d)
            n = re.search(r"\d+", when)
            right = f"{n.group(0)} d" if n else when
            rw = QFontMetrics(font(12.5, 560)).horizontalAdvance(right)
            self._t(p, name, 14, 520, c["on_surface"], pad + 74, y + 10, width - 84 - rw - 10)
            self._t(p, right, 12.5, 560, c["on_surface_variant"], pad, y + 11, width, align="right")
            y += 40
        y += 10
        return self._source(p, y, targets) + pad - 4

    def _clock(self, p, rect, h, m, label, sub, accent=False):
        c = self.c
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.PRIMARY_CONTAINER) if accent else C(self.tile()))
            p.drawPath(star_path(rect, *STARS["cookie12"]))
            cx, cy, R = rect.center().x(), rect.center().y(), rect.width() / 2 * 0.86
            p.setBrush(QColor(255, 255, 255, 60 if accent else 40))
            for k in range(12):
                a = math.radians(k * 30)
                p.drawEllipse(QPointF(cx + math.sin(a) * R * 0.86, cy - math.cos(a) * R * 0.86), 2.2 if k % 3 == 0 else 1.2, 2.2 if k % 3 == 0 else 1.2)
            fg = C(T.ON_PRIMARY_CONTAINER) if accent else c["on_surface"]
            ha, ma = math.radians((h % 12 + m / 60) * 30), math.radians(m * 6)
            p.setPen(QPen(fg, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx, cy), QPointF(cx + math.sin(ha) * R * 0.48, cy - math.cos(ha) * R * 0.48))
            p.setPen(QPen(fg, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx, cy), QPointF(cx + math.sin(ma) * R * 0.72, cy - math.cos(ma) * R * 0.72))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(c["primary"] if not accent else QColor("white")); p.drawEllipse(QPointF(cx, cy), 4, 4)
        y = rect.bottom() + 10
        h1, _ = self._t(p, label, 26, 600, c["on_surface"], rect.left() - 20, y, rect.width() + 40, align="center", wdth=100)
        self._t(p, sub, 12.5, 520, c["on_surface_variant"], rect.left() - 30, y + h1, rect.width() + 60, align="center")

    def _time(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        y = pad
        self._t(p, info.title, 16, 560, c["on_surface_variant"], pad, y, width)
        rel = info.chips[1] if len(info.chips) > 1 else ""
        if rel:
            fm = QFontMetrics(font(12.5, 600)); self._pill(p, rel, pad + width - fm.horizontalAdvance(rel) - 24, y - 4, self.tile(), c["on_surface"], h=28, px=12.5, weight=600)
        y += 36
        there, here = dict(info.rows)["Their time"], dict(info.rows)["Your time"]
        def hm(s): h, m = s.split()[0].split(":"); return int(h), int(m)
        size = 128
        left = QRectF(pad + width * 0.25 - size / 2, y, size, size)
        right = QRectF(pad + width * 0.75 - size / 2, y, size, size)
        zone_there = info.zone_there or there.split()[1]
        city_here = info.city_here or "Your time"
        day_note = info.chips[0].split(" in ")[0] if info.chips else ""
        self._clock(p, left, *hm(there), there.split()[0], zone_there)
        self._clock(p, right, *hm(here), here.split()[0], f"{city_here} · {day_note.lower()}", accent=True)
        if p:
            cy = left.center().y()
            p.setPen(QPen(c["on_surface_variant"], 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            a, b = QPointF(left.right() + 14, cy), QPointF(right.left() - 14, cy)
            p.drawLine(a, b); p.drawPolyline([QPointF(b.x() - 6, cy - 6), b, QPointF(b.x() - 6, cy + 6)])
        targets["value"] = (right, lambda: self.copyRequested.emit(info.value))
        y = left.bottom() + 10 + 34 + 18 + 18
        return y + pad - 10

    def _date(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        d = info.date_value or date.fromisoformat(dict(info.rows)["ISO"])
        today = date.today()
        y = pad
        self._t(p, info.title, 16, 560, c["on_surface_variant"], pad, y, width)
        rel = info.chips[0] if info.chips else ""
        fm = QFontMetrics(font(12.5, 620))
        self._pill(p, rel, pad + width - fm.horizontalAdvance(rel) - 24, y - 4, T.mixh(T.ERROR_CONTAINER, T.SURFACE, 0.35), C(T.ON_ERROR_CONTAINER), h=28, px=12.5, weight=620)
        y += 30
        y += self._t(p, info.value, 44, 560, c["on_surface"], pad, y, width, wdth=100)[0]
        y += self._t(p, f"{d:%-d %B %Y}  ·  week {d.isocalendar()[1]}", 14, 500, c["on_surface_variant"], pad, y, width)[0] + 14
        cw, chh = width / 7, 34
        first = d.replace(day=1)
        start = first - timedelta(days=first.weekday())
        if p:
            p.setFont(font(11.5, 620)); p.setPen(c["on_surface_variant"])
            for i, wd in enumerate("MTWTFSS"):
                p.drawText(QRectF(pad + i * cw, y, cw, 18), Qt.AlignmentFlag.AlignCenter, wd)
        y += 22
        cur = start
        rows = 0
        while cur <= (first.replace(month=first.month % 12 + 1, year=first.year + (first.month == 12)) - timedelta(days=1)) or cur.weekday() != 0:
            r = rows; col = cur.weekday()
            cell = QRectF(pad + col * cw, y + r * chh, cw, chh)
            if p:
                inside = cur.month == d.month
                if cur == d:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.ERROR_CONTAINER))
                    p.drawPath(star_path(QRectF(cell.center().x() - 17, cell.center().y() - 17, 34, 34), *STARS["cookie9"]))
                elif cur == today:
                    p.setPen(QPen(c["primary"], 1.6)); p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(cell.center(), 14, 14)
                p.setFont(font(13, 680 if cur == d else 480))
                p.setPen(C(T.ON_ERROR_CONTAINER) if cur == d else (c["on_surface"] if inside else QColor(255, 255, 255, 50)))
                p.drawText(cell, Qt.AlignmentFlag.AlignCenter, str(cur.day))
            cur += timedelta(days=1)
            if cur.weekday() == 0:
                rows += 1
        y += rows * chh + 12
        if info.actions:
            acts = list(info.actions) + [Action("Copy date", "copy", d.isoformat())]
            y = self._buttons(p, acts, pad, y, targets) + 6
        return y + pad - 4

    def _color(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        base = QColor(info.swatch[:7])
        y = pad
        sw = QRectF(pad, y, width, 112)
        lum = T.lum(info.swatch[:7])
        ink = QColor("#111") if lum > 0.35 else QColor("white")
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(base); p.drawRoundedRect(sw, 24, 24)
        self._t(p, info.title, 30, 640, ink, sw.left() + 20, sw.top() + 18, sw.width() - 40, wdth=100)
        self._t(p, info.chips[0] if info.chips else "", 12.5, 600, ink, sw.left() + 20, sw.top() + 60, sw.width() - 40)
        self._t(p, "Aa", 30, 700, QColor("white"), sw.left(), sw.top() + 56, sw.width() - 20, align="right")
        self._t(p, "Aa", 30, 700, QColor("#111"), sw.left(), sw.top() + 56, sw.width() - 72, align="right")
        targets["value"] = (sw, lambda: self.copyRequested.emit(info.title))
        y = sw.bottom() + 12
        h, s, l, _ = base.getHslF()
        steps = [QColor.fromHslF(h if h >= 0 else 0, s, lt) for lt in (0.92, 0.82, 0.70, 0.58, l, 0.38, 0.28, 0.18, 0.10)]
        steps[4] = base
        n = len(steps); gap = 2; segw = (width - gap * (n - 1)) / n
        for i, col in enumerate(steps):
            r = QRectF(pad + i * (segw + gap), y, segw, 34)
            name = f"tone{i}"
            targets[name] = (r, lambda col=col: self.copyRequested.emit(col.name().upper()))
            if p:
                tl = 12 if i == 0 else 4; tr = 12 if i == n - 1 else 4
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
                p.drawPath(rrect(r, tl, tr, tr, tl))
                if i == 4:
                    p.setBrush(QColor("#111") if col.lightnessF() > 0.5 else QColor("white"))
                    p.drawEllipse(r.center(), 3, 3)
        y += 34 + 14
        hue = (h if h >= 0 else 0) * 360
        groups = [("Complement", [180]), ("Analogous", [-30, 30]), ("Triadic", [120, 240])]
        gx = pad
        for label, offs in groups:
            self._t(p, label, 11.5, 560, c["on_surface_variant"], gx, y, 120)
            for j, o in enumerate(offs):
                col = QColor.fromHslF(((hue + o) % 360) / 360, s, l)
                cr = QRectF(gx + j * 40, y + 20, 34, 34)
                name = f"harm{label}{j}"
                targets[name] = (cr, lambda col=col: self.copyRequested.emit(col.name().upper()))
                if p:
                    p.setPen(Qt.PenStyle.NoPen); p.setBrush(col); p.drawPath(star_path(cr, *STARS["cookie6"]) if label == "Complement" else shape_path("circle", cr))
            gx += 128 if label != "Complement" else 104
        y += 20 + 34 + 16
        acts = [Action(lbl, "copy", val) for lbl, val in info.rows]
        y = self._buttons(p, acts, pad, y, targets)
        return y + pad

    def _nearby(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        y = pad
        self._t(p, info.title, 16, 620, c["on_surface"], pad, y, width)
        y += 28
        if info.definition:
            y += self._t(p, info.definition, 13.5, 440, c["on_surface_variant"], pad, y, width, lines=2)[0] + 12
        items = [it for it in info.items if it.get("image") is not None]
        widths = [172, 118, 54]
        gap, h = 8, 168
        x = pad
        for i, (it, w) in enumerate(zip(items, widths + [0] * 9)):
            if w == 0 or x >= pad + width:
                break
            w = min(w, pad + width - x)
            r = QRectF(x, y, w, h)
            name = f"item{i}"
            targets[name] = (r.adjusted(0, 0, 0, 44), (lambda u=it["url"]: self.openRequested.emit(u)) if it.get("url") else None)
            if p:
                img = it["image"]
                clip = QPainterPath(); clip.addRoundedRect(r, 24 if w > 60 else w / 2, 24 if w > 60 else w / 2)
                p.save(); p.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                sc = max(w / img.width(), h / img.height())
                sw, sh = w / sc, h / sc
                p.drawImage(r, img, QRectF((img.width() - sw) / 2, (img.height() - sh) / 2, sw, sh))
                if self._hover == name:
                    p.fillRect(r, QColor(255, 255, 255, 30))
                p.restore()
            if w >= 100:
                self._t(p, it["title"], 13.5, 600, c["on_surface"], x + 2, y + h + 8, w - 4, lines=1)
                dist = it.get("subtitle", "").split(",")[0]
                self._t(p, dist, 12, 500, c["on_surface_variant"], x + 2, y + h + 26, w - 4)
            x += w + gap
        y += h + 26 + 18 + 14
        return self._source(p, y, targets) + pad - 4

    def _trends(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        y = pad
        self._t(p, info.title, 16, 620, c["on_surface"], pad, y, width)
        y += 30
        for k, s in enumerate(info.chart["series"]):
            pts = s["points"]
            v0, v1 = pts[0][1], pts[-1][1]
            pct = (v1 - v0) / v0 * 100
            self._t(p, s["label"], 12.5, 560, c["on_surface_variant"], pad, y, width)
            y += 18
            vh, vw = self._t(p, self._format(v1, s), 26, 620, c["on_surface"], pad, y, width)
            delta = f"{'↑' if pct > 0 else '↓'} {abs(pct):.0f}% since {pts[0][0]}"
            self._pill(p, delta, pad + vw + 12, y + 3, self.tile(), c["on_surface"], h=26, px=12, weight=600)
            y += vh + 6
            plot = QRectF(pad + 2, y, width - 4, 46)
            targets[f"series{k}"] = (plot, None)
            if p:
                vs = [v for _, v in pts]; lo, hi = min(vs), max(vs); pv = (hi - lo) * 0.1 or 1
                lo, hi = lo - pv, hi + pv
                pos = lambda i, v: QPointF(plot.left() + plot.width() * i / (len(pts) - 1), plot.bottom() - (v - lo) / (hi - lo) * plot.height())
                line = QPainterPath(pos(0, pts[0][1]))
                for i, (_, v) in enumerate(pts[1:], 1):
                    line.lineTo(pos(i, v))
                wash = QPainterPath(line); wash.lineTo(plot.bottomRight()); wash.lineTo(plot.bottomLeft()); wash.closeSubpath()
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(66, 133, 244, 26)); p.drawPath(wash)
                p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(self.MARK, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)); p.drawPath(line)
                p.setPen(QPen(C(self.tint()), 2)); p.setBrush(self.MARK); p.drawEllipse(pos(len(pts) - 1, v1), 5, 5)
                p.setFont(font(11, 520)); p.setPen(c["on_surface_variant"])
                axis = QRectF(plot.left(), plot.bottom() + 4, plot.width(), 14)
                p.drawText(axis, Qt.AlignmentFlag.AlignLeft, str(pts[0][0])); p.drawText(axis, Qt.AlignmentFlag.AlignRight, str(pts[-1][0]))
            y = plot.bottom() + 26
        return self._source(p, y, targets) + pad - 4

    def _repo(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        rows = dict(info.rows)
        y = pad
        badge = QRectF(pad - 2, y, 56, 56)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile())); p.drawPath(star_path(badge, *STARS["clover4"]))
        self._t(p, info.title.split("/")[-1][:1].upper(), 24, 700, c["on_surface"], badge.left(), badge.top() + 13, badge.width(), align="center")
        tx = badge.right() + 14
        self._t(p, info.title, 17, 620, c["on_surface"], tx, y + 6, width - (tx - pad), fit=True)
        self._t(p, info.source + " repository", 12.5, 500, c["on_surface_variant"], tx, y + 30, width - (tx - pad))
        y = badge.bottom() + 14
        if info.definition:
            y += self._t(p, info.definition, 14, 440, c["on_surface"], pad, y, width, lines=2)[0] + 14
        stars = rows.get("Stars", "")
        if stars:
            n = float(stars.replace(",", ""))
            shown = f"{n / 1000:.1f}K".replace(".0K", "K") if n >= 1000 else stars
            sh, sw = self._t(p, shown, 52, 560, c["on_surface"], pad + 40, y - 4, width, wdth=105)
            if p:
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#FBBC05"))
                p.drawPath(star_path(QRectF(pad, y + 14, 30, 30), 5, 0.5, 0.9))
            self._t(p, "stars", 14, 520, c["on_surface_variant"], pad + 40 + sw + 8, y + 28, 100)
            y += sh + 6
        x = pad
        chips = []
        if rows.get("Language"):
            chips.append((rows["Language"], {"Go": "#00ADD8", "Python": "#3572A5", "Rust": "#DEA584", "C": "#A8B9CC"}.get(rows["Language"], "#A6A9B4"), None))
        if rows.get("Latest release"):
            chips.append((rows["Latest release"].replace(", ", " · "), None, "tag"))
        if rows.get("Last push"):
            chips.append(("pushed " + rows["Last push"], None, "clock"))
        if rows.get("Open issues"):
            chips.append((rows["Open issues"] + " open issues", None, None))
        for label, dot, icon in chips:
            w = QFontMetrics(font(13, 560)).horizontalAdvance(label) + 24 + (22 if dot or icon else 0)
            if x + w > pad + width and x > pad:
                x, y = pad, y + 38
            x += self._pill(p, label, x, y, self.tile(), c["on_surface"], h=32, dot=dot, icon=icon) + 6
        y += 32 + 16
        if info.actions:
            y = self._buttons(p, info.actions, pad, y, targets) + 14
        return self._source(p, y, targets) + pad - 4

    def _package(self, p, targets):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        rows = dict(info.rows)
        y = pad
        self._t(p, info.source, 15, 620, c["on_surface"], pad, y, width)
        if rows.get("Released"):
            self._t(p, "released " + rows["Released"], 12.5, 520, c["on_surface_variant"], pad, y + 2, width, align="right")
        y += 26
        vh, _ = self._t(p, info.value, 56, 540, c["on_surface"], pad, y, width, wdth=105)
        y += vh + 2
        if info.definition:
            y += self._t(p, info.definition, 14, 440, c["on_surface_variant"], pad, y, width, lines=2)[0] + 14
        cmd = info.title
        r = QRectF(pad, y, width, 48)
        targets["cmd"] = (r, lambda: self.copyRequested.emit(cmd))
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(0, 0, 0, 90)); p.drawRoundedRect(r, 16, 16)
            if self._hover == "cmd":
                p.setBrush(QColor(255, 255, 255, 14)); p.drawRoundedRect(r, 16, 16)
            mono = QFont("monospace"); mono.setPixelSize(15); p.setFont(mono); p.setPen(c["on_surface"])
            p.setPen(c["primary"]); p.drawText(QRectF(r.left() + 16, r.top(), 20, r.height()), Qt.AlignmentFlag.AlignVCenter, "$")
            p.setPen(c["on_surface"]); p.drawText(QRectF(r.left() + 34, r.top(), r.width() - 80, r.height()), Qt.AlignmentFlag.AlignVCenter, cmd)
            self._paint_copy_icon(p, QRectF(r.right() - 44, r.top() + 6, 36, 36), self._hover == "cmd")
        y = r.bottom() + 12
        if rows.get("Python"):
            self._pill(p, "Python " + rows["Python"], pad, y, self.tile(), c["on_surface"], h=30, icon="code")
            y += 30 + 14
        return self._source(p, y, targets) + pad - 4
