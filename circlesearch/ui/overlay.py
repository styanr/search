import math
import os
import re
import tempfile
import threading
import time

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSizeF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QGuiApplication, QImage, QKeySequence, QPainter, QPen, QShortcut
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from circlesearch.core import actions, history, settings
from circlesearch.core.ocr import join_words
from circlesearch.core.textindex import TextIndex
from circlesearch.ui.backdrop import Renderer
from circlesearch.ui.board import CardBoard, shadow_rect
from circlesearch.ui.effects import InkStroke, draw_glyph, draw_loader, lightness_at
from circlesearch.ui.motion import (AMBIENT, MOTION, OUT_CUBIC, SPRING, SWEEP_EASE, WORD_SPRING, Animated, Tween,
                                    frame_timer, lerp, lerp_rect, mix, with_alpha)
from circlesearch.ui.reader import TextReader, to_point, to_qrect, to_rect
from circlesearch.ui.searchbar import SearchBar
from circlesearch.ui.theme import (HIGHLIGHT_DARK, HIGHLIGHT_LIGHT, ON_SURFACE, ON_SURFACE_VARIANT, PRIMARY, SURFACE,
                                   SURFACE_HIGH, font)

TAP_BAND = QSizeF(900, 96)
TAP_DISTANCE = 6
SELECTION_PADDING = 6
TEXT_COVERAGE = 0.12

SCRIM_TOP, SCRIM_BOTTOM = 0.40, 0.60
SCRIM_LIGHT = 0.30, 0.48
SCRIM_SELECTED = 0.14
SWEEP_EDGE = 260
AURORA_HEIGHT = 200
SHIMMER_SWEEP, SHIMMER_PERIOD = 1.1, 1.6
WORD_REVEAL, WORD_CASCADE = 0.22, 0.28
FRAME_SETTLE = 0.5


def copy_text(text):
    if not actions.copy_text(text):
        QGuiApplication.clipboard().setText(text)


SENSITIVE = ("jwt", "wifi", "otp")


class Overlay(QOpenGLWidget):
    closed = pyqtSignal()
    selecting = pyqtSignal(object)
    finished = pyqtSignal(object)

    def __init__(self, screenshot: QImage, screen, instant=False, scale=None):
        super().__init__()
        self.setWindowTitle("Circle to Search")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.instant = instant

        self.dpr = scale or screen.devicePixelRatio()
        geo = screen.geometry()
        self.origin = geo.topLeft()
        phys = QRect(round(geo.x() * self.dpr), round(geo.y() * self.dpr),
                     round(geo.width() * self.dpr), round(geo.height() * self.dpr))
        if scale is None and screenshot.size() != phys.size():
            screenshot = screenshot.copy(phys)
        self.shot = screenshot
        self.shot.setDevicePixelRatio(self.dpr)
        self.logical_size = geo.size()
        self.thumb = screenshot.scaled(128, 72, Qt.AspectRatioMode.IgnoreAspectRatio,
                                       Qt.TransformationMode.FastTransformation)
        bright = self._mean_lightness(QRectF(0, 0, geo.width(), geo.height()))
        k = min(1.0, max(0.0, (bright - 0.45) / 0.35))
        k = k * k * (3 - 2 * k)
        self.scrim_top = lerp(SCRIM_TOP, SCRIM_LIGHT[0], k)
        self.scrim_bottom = lerp(SCRIM_BOTTOM, SCRIM_LIGHT[1], k)

        self.ink = None
        self.selection = None
        self.selected_words = []
        self.index = TextIndex()
        self.reading = False
        self._pending = None
        self.status = ""
        self.debug_dir = None
        if settings.DEBUG:
            self.debug_dir = os.path.join(settings.CACHE_DIR, "debug", time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(self.debug_dir, exist_ok=True)
        self.reader = TextReader(self.shot, self.dpr, self.debug_dir, self)
        self.reader.screen_read.connect(self._ocr_done)
        self.reader.region_read.connect(self._region_done)
        self.reader.image_read.connect(self._image_done)
        self._reading_screen = False
        self._scan = None
        self.code_route = None
        self.colors = []
        self._logged = []
        self._pinned = None
        self.typed = False
        self.ocr_gate = None
        self.board = CardBoard(self, self._card_copy, self._card_open, self._card_pin, self._card_save, self._card_run)

        self.t0 = time.monotonic()
        self.intro = Tween(0.8)
        self.exit = None
        self.aurora = Animated(0.0, 0.6)
        self.chip = Animated(0.0, 0.3, SPRING)
        self.scrim_selected = Animated(0.0, 0.3)
        self.words_t0 = None
        self._word_groups = []
        self._word_light = {}
        self.selection_light = False
        self.shape_from = None
        self.shape_tween = None
        self.frame_tween = None
        self.ghost = None
        self._snaps = []
        self._leaving = False
        self.bar_from = self.bar_to = None
        self.bar_tween = None
        self.gpu = None
        self.ambient = AMBIENT
        self._chip = None
        self._word_batch = None
        self.ticker = frame_timer(self, self._tick)

        self.bar = SearchBar(self)
        self.bar.hide()
        self.bar.textSearch.connect(self.do_text_search)
        self.bar.imageSearch.connect(self.do_image_search)
        self.bar.copy.connect(self.do_copy)
        self.bar.pin.connect(self.do_pin)
        self.bar.recall.connect(self._recall)
        self.bar.edited.connect(self._typed_text)

        QShortcut(QKeySequence("Escape"), self, self.dismiss)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.do_image_search)
        QShortcut(QKeySequence("Ctrl+C"), self, self._copy_shortcut)
        QShortcut(QKeySequence("Ctrl+P"), self, self.do_pin)

    def card_anchor(self):
        bar = QRectF(self.bar_to if self.bar_to is not None else QPointF(self.bar.pos()), QSizeF(self.bar.size()))
        return bar, self.selection if self.selection is not None else bar

    def cards_wanted(self):
        return (self.selection is not None or self.typed) and self.exit is None

    def global_point(self, local):
        return self.origin + QPoint(round(local.x()), round(local.y()))

    def _flash(self, text, ms=1400):
        self.status = text
        self.chip.set(1.0)
        self.update()
        QTimer.singleShot(round(ms * max(MOTION, 0.4)), lambda: self._end_flash(text))

    def _end_flash(self, text):
        if self.status == text:
            self.status = ""
            self.update()

    def _request_cards(self, text, words):
        if self.code_route is not None:
            return
        if not text.strip():
            if self.colors and self.index.ready:
                self.board.request("", route=self._palette_route())
            return
        if not self._prefers_text(words) and len(words) <= 2 and self.colors and len(text.strip()) <= 3:
            self.board.request("", route=self._palette_route())
            return
        self.board.request(text, words)
        self._remember(text)

    def _palette_route(self):
        from circlesearch.core.routing import Route
        return Route("palette", text=",".join(self.colors), value=self.colors)

    def _remember(self, text):
        text = " ".join(text.split())
        if text and text not in self._logged and not re.search(r"eyJ[\w-]{8,}\.|otpauth://|WIFI:", text):
            self._logged.append(text)

    def _image_done(self, token, codes, colors):
        if token != self._scan or self.selection is None:
            return
        self.colors = colors
        if codes:
            from circlesearch.plugins.codes import is_sensitive, route_for
            self.code_route = route_for(codes[0])
            self.board.request("", route=self.code_route)
            if not is_sensitive(codes[0].data) and not self.bar.edit.isModified():
                self.bar.set_selection(codes[0].data, True)
            return
        if self.index.ready and not self.reading and not self.selected_words:
            self._request_cards("", [])

    def _start_ocr(self):
        if not self.reader.available():
            self.index.set_screen([])
            if self.ocr_gate is not None:
                self.ocr_gate(self)
            return
        self.reader.read_screen()

    def _read_region(self, area, purpose):
        if not self.reader.available():
            return None
        token = self.reader.read_region(area, QRectF(self.rect()))
        self._pending = (purpose, token) if purpose == "select" else (purpose, token, area.center())
        return token

    def _ocr_done(self, words):
        self.index.set_screen(words)
        if self.ocr_gate is not None:
            self.ocr_gate(self)
        if self.selection is not None and self.reading:
            self.reading = False
            self._apply_selection_words(provisional=True)
        elif self._pending and self._pending[0] == "tap" and self.index.word_at(to_point(self._pending[2])):
            pos, self._pending = self._pending[2], None
            self._select_word_at(pos)

    def _region_done(self, token, area, words):
        self.index.add_region(area, words)
        pending = self._pending
        if not pending or pending[1] != token:
            return
        self._pending = None
        if pending[0] == "tap":
            self._select_word_at(pending[2])
            return
        if self.selection is None:
            return
        if self.reading:
            self.reading = False
            self._apply_selection_words(provisional=False)
            return
        new = self.index.words_in(to_rect(self.selection))
        old_text, new_text = join_words(self.selected_words), join_words(new)
        if new and new_text != old_text and not self.bar.edit.isModified():
            self.selected_words = new
            self._start_word_reveal()
            self.words_t0 -= 10
            if self.code_route is None:
                self.bar.set_selection(new_text, self._prefers_text(new))
            self._request_cards(new_text, new)
            self.update(self.selection.adjusted(-24, -24, 24, 24).toAlignedRect())
        if self.instant:
            self.bar.run_default()

    def showEvent(self, event):
        self.intro = Tween(0.8)
        self.chip.set(1.0)
        self.ticker.start()
        if not self._reading_screen:
            self._reading_screen = True
            if self.ocr_gate is None:
                QTimer.singleShot(30, self._start_ocr)
            if settings.CARDS:
                threading.Thread(target=self._load_cards, daemon=True).start()

        super().showEvent(event)

    @staticmethod
    def _load_cards():
        from circlesearch.ui.cards import load_views
        load_views()

    def _tick(self):
        try:
            self._frame()
        except Exception:
            import traceback
            traceback.print_exc()

    def _frame(self):
        now = time.monotonic()
        working = self.reading
        if self.exit is None:
            self.aurora.set(0.85 if working else 0.5)
            self.chip.set(1.0 if ((self.selection is None and not self.typed) or self.status) else 0.0)
            self.scrim_selected.set(1.0 if self.selection is not None else 0.0)

        if self.bar_tween is not None:
            self._step_bar(now)
        self.board.step(now)
        if self.ghost is not None and self.ghost[1].done(now):
            self.ghost = None
            self.update()
        if self.exit is not None and self.exit.done(now):
            self.ticker.stop()
            self.close()
            return
        if self._moving(now):
            self.update()

    def _moving(self, now):
        if self.ambient or self.exit is not None or self.ghost is not None or not self.intro.done(now):
            return True
        if any(a.active(now) for a in (self.aurora, self.chip, self.scrim_selected)):
            return True
        if self.chip.get(now) > 0.001 and self._chip_working():
            return True
        if self.selection is None:
            return False
        return self._words_active(now) or any(t is not None and not t.done(now)
                                              for t in (self.shape_tween, self.frame_tween))

    def _chip_working(self):
        return self.reading or bool(self._pending and self._pending[0] == "tap")

    def _mean_lightness(self, rect):
        sx = self.thumb.width() / self.logical_size.width()
        sy = self.thumb.height() / self.logical_size.height()
        r = QRect(int(rect.left() * sx), int(rect.top() * sy),
                  max(1, math.ceil(rect.width() * sx)), max(1, math.ceil(rect.height() * sy)))
        r = r.intersected(self.thumb.rect())
        if r.isEmpty():
            return 0.0
        mean = self.thumb.copy(r).scaled(1, 1, Qt.AspectRatioMode.IgnoreAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation)
        return QColor(mean.pixel(0, 0)).lightnessF()

    def _step_bar(self, now):
        t = self.bar_tween
        pos = QPointF(lerp(self.bar_from.x(), self.bar_to.x(), t.value(now)),
                      lerp(self.bar_from.y(), self.bar_to.y(), t.value(now)))
        old = shadow_rect(self.bar)
        self.bar.move(pos.toPoint())
        effect = self.bar.graphicsEffect()
        if effect is not None:
            effect.setOpacity(min(1.0, t.raw(now) * 3))
        self.update(old.united(shadow_rect(self.bar)))
        if t.done(now):
            self.bar_tween = None
            self.bar.setGraphicsEffect(None)

    def _snapshot(self, widget, radius):
        effect = widget.graphicsEffect()
        opacity = effect.opacity() if effect is not None else 1.0
        widget.setGraphicsEffect(None)
        image = QImage(widget.size() * self.devicePixelRatioF(), QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(self.devicePixelRatioF())
        image.fill(Qt.GlobalColor.transparent)
        widget.render(image, flags=QWidget.RenderFlag.DrawChildren)
        self._snaps.append((image, QRectF(widget.geometry()), opacity, radius))
        widget.hide()

    def dismiss(self):
        if self.exit is not None:
            return
        self.exit = Tween(0.16)
        self.finished.emit(self)
        self.bar.close_recent()
        if self.bar.isVisible():
            self._snapshot(self.bar, SearchBar.HEIGHT / 2)
        for card in self.board.cards:
            if card is self._pinned:
                card.hide()
            elif card.isVisible():
                self._snapshot(card, card.radius())
        self.bar.hide()
        self.ink = None
        if self.exit.duration <= 0:
            self.close()

    def closeEvent(self, e):
        for text in self._logged[-3:]:
            history.add("selection", text)
        self._logged = []
        self.closed.emit()
        super().closeEvent(e)

    def mousePressEvent(self, e):
        if self.exit is not None or self._leaving:
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._clear_selection()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.selecting.emit(self)
            self.ink = InkStroke(self.size(), self.dpr, e.position())
            self.update(self.ink.bounds.toAlignedRect())

    def mouseMoveEvent(self, e):
        if self.ink is not None:
            self.update(self.ink.add(e.position()).toAlignedRect())

    def mouseReleaseEvent(self, e):
        if self.ink is None or e.button() != Qt.MouseButton.LeftButton:
            return
        ink, self.ink = self.ink, None
        ink.add(e.position())
        bounds = ink.raw
        if max(bounds.width(), bounds.height()) < TAP_DISTANCE:
            self.update(ink.bounds.toAlignedRect())
            self._select_word_at(e.position())
        else:
            pad = SELECTION_PADDING
            target = bounds.adjusted(-pad, -pad, pad, pad).intersected(QRectF(self.rect()))
            ink.finish()
            self.ghost = (ink, Tween(0.22))
            self._set_selection(target, bounds, min(bounds.width(), bounds.height()) / 2)
            self._scan = self.reader.scan(target, QRectF(self.rect()))
            self._finish_selection()
        self.update()

    def keyPressEvent(self, e):
        blocked = e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier |
                                   Qt.KeyboardModifier.MetaModifier)
        if self.selection is None and not self.typed and self.exit is None and not blocked:
            ch = e.text()
            if ch and ch.isprintable() and not ch.isspace():
                self._start_typing(ch)
                return
            if e.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Down, Qt.Key.Key_Space):
                self._start_typing("")
                return
        super().keyPressEvent(e)

    def _start_typing(self, text):
        self.typed = True
        self.code_route = None
        self.board.clear()
        self.bar.set_typing()
        w = min(820, self.width() - 32)
        self.bar.resize(w, SearchBar.HEIGHT)
        self._place_bar(QPointF((self.width() - w) / 2, self.height() * 0.22))
        self.bar.edit.setText(text)
        self.bar.edit.setModified(True)
        self.bar.edit.setCursorPosition(len(text))
        self.bar._text_edited(text)
        if not text:
            QTimer.singleShot(round(160 * MOTION), self.bar.open_recent)
        self.update()

    def _recall(self, text):
        self.code_route = None
        self.board.request(text)

    def _typed_text(self, text):
        if self.exit is not None or (self.selection is None and not self.typed):
            return
        self.code_route = None
        if text.strip():
            self.board.request(text)
        else:
            self.board.clear()

    def _copy_shortcut(self):
        if self.bar.edit.hasSelectedText():
            self.bar.edit.copy()
        elif self.bar.isVisible():
            self.do_copy(self.bar.edit.text())

    def _set_selection(self, target, start_rect, start_radius):
        self.shape_from = (QRectF(start_rect), start_radius)
        self.shape_tween = Tween(0.5, SPRING)
        self.frame_tween = None
        self.selection = target
        self.typed = False
        self.code_route = None
        self.colors = []
        self._scan = None
        self.board.clear()
        self.selection_light = self._mean_lightness(target) > 0.5

    def _shape(self, now):
        target = self.selection
        radius = min(18.0, target.height() * 0.32, target.width() * 0.32)
        if self.shape_tween is None:
            return target, radius
        p = self.shape_tween.value(now)
        start, start_radius = self.shape_from
        rect = lerp_rect(start, target, p)
        return rect, max(2.0, min(lerp(start_radius, radius, p), rect.height() / 2, rect.width() / 2))

    def _clear_selection(self):
        self.selection = None
        self.typed = False
        self.code_route = None
        self.selected_words = []
        self._pending = None
        self.reading = False
        self.bar.hide()
        self.board.clear()
        self.update()

    def _select_word_at(self, pos):
        hit = self.index.word_at(to_point(pos))
        if hit is None and not self.index.in_region(to_point(pos)):
            band = QRectF(pos.x() - TAP_BAND.width() / 2, pos.y() - TAP_BAND.height() / 2,
                          TAP_BAND.width(), TAP_BAND.height())
            if self._read_region(band, "tap") is not None:
                self.status = "Reading text…"
                self.update()
                return
        if self.status == "Reading text…":
            self.status = ""
        if hit is None:
            self._clear_selection()
            return
        self._set_selection(to_qrect(hit.rect).adjusted(-5, -4, 5, 4), QRectF(pos.x() - 12, pos.y() - 12, 24, 24), 12)
        self._finish_selection()

    def _finish_selection(self):
        covered = self.index.covered(to_rect(self.selection))
        if not covered:
            self._read_region(self.selection, "select")
        self.status = ""
        if not self.index.ready:
            self.reading = True
            self._show_bar("", False, reading=True)
            return
        self.reading = False
        self._apply_selection_words(provisional=not covered)

    def _prefers_text(self, words):
        sel = self.selection
        word_area = sum(w.rect.w * w.rect.h for w in words)
        return word_area / max(1.0, sel.width() * sel.height()) >= TEXT_COVERAGE

    def _apply_selection_words(self, provisional):
        self.selected_words = self.index.words_in(to_rect(self.selection))
        self.frame_tween = Tween(FRAME_SETTLE)
        self._start_word_reveal()
        text = join_words(self.selected_words)
        if self.code_route is None:
            self._show_bar(text, self._prefers_text(self.selected_words))
        else:
            self._show_bar(self.bar.edit.text(), True)
        self._request_cards(text, self.selected_words)
        if self.instant and not provisional:
            self.bar.run_default()

    def _card_copy(self, text):
        if self._leaving or self.exit is not None:
            return
        copy_text(text)
        self._flash("Copied")

    def _card_open(self, url):
        if self._leaving or self.exit is not None:
            return
        actions.open_url(url)
        self.dismiss()

    def _card_save(self, path):
        if self._leaving or self.exit is not None:
            return
        actions.open_url("file://" + path)
        self.dismiss()

    def _card_run(self, payload):
        if self._leaving or self.exit is not None:
            return
        ok = actions.run_command(payload["command"], payload.get("stdin"))
        self._flash(payload.get("status", "Connecting") if ok else "Could not start " + payload["command"][0])

    def _card_pin(self, widget):
        if self._leaving or self.exit is not None or widget.card is None:
            return
        from circlesearch.ui.pin import pin_card
        pin_card(widget.card, widget.assets, widget.WIDTH, widget.role, self.global_point(widget.pos()))
        self._pinned = widget
        self.dismiss()

    def do_pin(self):
        if self.selection is None or self._leaving or self.exit is not None:
            return
        from circlesearch.ui.pin import pin_image
        r = self.selection
        crop = self.shot.copy(QRect(round(r.x() * self.dpr), round(r.y() * self.dpr),
                                    round(r.width() * self.dpr), round(r.height() * self.dpr)))
        crop.setDevicePixelRatio(self.dpr)
        pin_image(crop, self.global_point(r.topLeft()), join_words(self.selected_words))
        self.dismiss()

    def _start_word_reveal(self):
        words = self.selected_words
        if len(words) <= 150:
            self._word_groups = list(range(len(words)))
        else:
            lines = {}
            self._word_groups = [lines.setdefault(w.line, len(lines)) for w in words]
        self.words_t0 = time.monotonic()

    def _word_timing(self):
        slots = (max(self._word_groups) + 1) if self._word_groups else 1
        return min(0.018, WORD_CASCADE / slots) * MOTION, WORD_REVEAL * MOTION, slots

    def _word_progress(self, i, now):
        stagger, duration, _ = self._word_timing()
        if self.words_t0 is None or duration <= 0:
            return 1.0
        return min(1.0, max(0.0, (now - self.words_t0 - self._word_groups[i] * stagger) / duration))

    def _words_active(self, now):
        if self.words_t0 is None or not self.selected_words:
            return False
        stagger, duration, slots = self._word_timing()
        return now < self.words_t0 + slots * stagger + duration

    def _word_is_light(self, w):
        light = self._word_light.get(w.order)
        if light is None:
            r = to_qrect(w.rect).adjusted(-2, -2, 2, 2)
            xs = [r.left() + r.width() * (i + 0.5) / 4 for i in range(4)]
            light = lightness_at(self.shot, [(x, y) for x in xs for y in (r.top(), r.bottom())]) > 0.5
            self._word_light[w.order] = light
        return light

    def _show_bar(self, text, prefer_text, reading=False):
        self.bar.set_selection(text, prefer_text, reading)
        sel = self.selection
        h = SearchBar.HEIGHT
        w = min(820, self.width() - 32)
        self.bar.resize(w, h)
        x = min(max(16, sel.center().x() - w / 2), self.width() - w - 16)
        y = sel.bottom() + 22
        if y + h > self.height() - 16:
            y = max(16, sel.top() - h - 22)
        self._place_bar(QPointF(x, y))

    def _place_bar(self, target):
        if self.bar.isVisible():
            if (target - QPointF(self.bar.pos())).manhattanLength() > 1:
                self.bar_from = QPointF(self.bar.pos())
                self.bar_to = target
                self.bar_tween = Tween(0.45, SPRING)
        else:
            self.bar_from, self.bar_to = target + QPointF(0, 22), target
            self.bar_tween = Tween(0.5, SPRING)
            effect = QGraphicsOpacityEffect(self.bar)
            effect.setOpacity(0.0)
            self.bar.setGraphicsEffect(effect)
            self.bar.move(self.bar_from.toPoint())
            self.bar.show()
        self.bar.edit.setFocus()
        self.update()

    def _crop_png(self):
        r = self.selection
        phys = QRect(round(r.x() * self.dpr), round(r.y() * self.dpr),
                     round(r.width() * self.dpr), round(r.height() * self.dpr))
        crop = self.shot.copy(phys)
        crop.setDevicePixelRatio(1.0)
        path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        crop.save(path)
        with open(path, "rb") as f:
            data = f.read()
        os.unlink(path)
        return data

    def do_text_search(self, text):
        if text.strip() and not self._leaving:
            history.add("search", text)
            actions.search_text(text)
            self.dismiss()

    def do_copy(self, text):
        if text.strip() and not self._leaving:
            copy_text(text)
            self._leaving = True
            self.bar.copy_btn.confirm()
            QTimer.singleShot(round(1000 * min(0.35, max(0.25, 0.3 * MOTION))), self.dismiss)

    def do_image_search(self):
        if self.selection is None or self.exit is not None or self._leaving:
            return
        actions.search_image(self._crop_png())
        self.dismiss()

    def initializeGL(self):
        self.gpu = Renderer(self.shot)
        self.ambient = AMBIENT and not self.gpu.lite

    def paintGL(self):
        now = time.monotonic()
        t = (now - self.t0) if self.ambient else 0.0
        fade = 1.0 - (self.exit.value(now) if self.exit is not None else 0.0)
        intro = self.intro.value(now)
        g = self.gpu
        g.begin(self.width(), self.height(), self.devicePixelRatioF())
        front = self._sweep_front(intro)
        band = SWEEP_EDGE * 1.6
        glow = self.aurora.get(now) * fade * min(1.0, intro * 1.6)
        wave = (1.0 - intro) ** 0.7 * fade if intro < 1.0 else 0.0
        g.background(shade=(self.scrim_top, self.scrim_bottom, SCRIM_SELECTED * self.scrim_selected.get(now), fade),
                     sweep=(front, SWEEP_EDGE),
                     hole=self._shape(now) if self.selection is not None else None,
                     glow=(glow if glow > 0.01 else 0.0, t, self.height() - AURORA_HEIGHT, AURORA_HEIGHT),
                     wave=(wave, t + 3.0, front - band * 0.55, band))
        if self.selection is not None:
            self._paint_selection(g, now, t, fade)
        if self.ghost is not None:
            ink, tween = self.ghost
            g.ink(ink, (1 - tween.value(now)) * fade, tip=False)
        if self.ink is not None:
            g.ink(self.ink)
        for widget, radius in ((self.bar, SearchBar.HEIGHT / 2), *((c, c.radius()) for c in self.board.cards)):
            if widget is not None and widget.isVisible():
                effect = widget.graphicsEffect()
                g.shadow(QRectF(widget.geometry()), effect.opacity() if effect is not None else 1.0, radius)
        for image, geometry, opacity, radius in self._snaps:
            g.shadow(geometry, opacity * fade, radius)
            g.image(("snap", id(image)), image, geometry, opacity * fade)
        self._paint_chip(g, now, fade)
        g.end()

    def _sweep_front(self, intro):
        return lerp(self.height() + 60, -SWEEP_EDGE - 60, intro)

    def _spin(self, now):
        return (now - self.t0) * 160 if self.ambient else 0.0

    def _paint_selection(self, g, now, t, fade):
        rect, radius = self._shape(now)
        if self.selected_words:
            self._paint_words(g, now, rect, radius, fade)

        if self.reading or self.frame_tween is None:
            if self.ambient:
                h = rect.height()
                reach = 80 + h * h / 160
                cycle = (t % SHIMMER_PERIOD) / SHIMMER_SWEEP
                x = lerp(rect.left() - reach, rect.right() + reach,
                         SWEEP_EASE.valueForProgress(min(1.0, cycle)))
                start, end = QPointF(x - 80, rect.top()), QPointF(x + 80, rect.bottom())
                if self.selection_light:
                    g.shimmer(rect, radius, start, end, HIGHLIGHT_LIGHT, 0.9 * fade, True)
                else:
                    g.shimmer(rect, radius, start, end, QColor("white"), 0.16 * fade, False)
            g.border(rect, radius, 3.5, self._spin(now), fade)
            return

        u = self.frame_tween.raw(now)
        k = OUT_CUBIC.valueForProgress(min(1.0, max(0.0, (u - 0.1) / 0.9)))
        white = min(1.0, max(0.0, (u - 0.4) / 0.6))
        white = white * white * (3 - 2 * white)
        grow = lerp(0.0, 4.0, k)
        r = rect.adjusted(-grow, -grow, grow, grow)
        rad = radius + grow
        pen = min(5.0, max(2.5, min(r.width(), r.height()) / 12))
        s_end = min(rad + 26, r.width() * 0.4, r.height() * 0.4)
        s = lerp(max(r.width(), r.height()) / 2 + 8, s_end, k)
        g.frame(r, rad, s, lerp(3.5, pen, k), pen, white, fade, self._spin(now), rect.center())

    def _paint_words(self, g, now, rect, radius, fade):
        key = (self.words_t0, len(self.selected_words), rect.getRect(), radius, fade)
        if self._word_batch is None or self._word_batch[0] != key or self._words_active(now):
            light, dark = [], []
            for i, w in enumerate(self.selected_words):
                u = self._word_progress(i, now)
                if u <= 0.0:
                    continue
                a = min(1.0, u * 2.5) * fade
                r = to_qrect(w.rect).adjusted(-3, -2, 3, 2)
                r.setWidth(r.width() * WORD_SPRING.valueForProgress(u))
                if self._word_is_light(w):
                    light.append((r, mix(QColor("white"), HIGHLIGHT_LIGHT, a)))
                else:
                    dark.append((r, mix(QColor("black"), HIGHLIGHT_DARK, a)))
            self._word_batch = (key, g.word_batch(light, dark))
        g.words(self._word_batch[1], rect.adjusted(-10, -10, 10, 10), radius + 10)

    def _paint_chip(self, g, now, fade):
        a = max(0.0, self.chip.get(now)) * fade
        if a <= 0.01:
            return
        working = self._chip_working()
        text = self.status or "Circle, tap or type to search"
        label_font = font(15, 480)
        fm = QFontMetrics(label_font)
        key_font = font(12, 600)
        kfm = QFontMetrics(key_font)
        show_key = not self.status
        kw = kfm.horizontalAdvance("Esc") + 16 if show_key else 0
        tw = fm.horizontalAdvance(text)
        h = 46
        w = 18 + 20 + 12 + tw + (14 + kw if show_key else 0) + 16
        box = QRectF((self.width() - w) / 2, lerp(4, 26, min(1.0, a)), w, h)
        key = (text, show_key, working and now)
        fresh = self._chip is None or self._chip[0] != key
        if fresh:
            dpr = self.devicePixelRatioF()
            image = QImage(round((w + 2) * dpr), round((h + 2) * dpr), QImage.Format.Format_ARGB32_Premultiplied)
            image.setDevicePixelRatio(dpr)
            image.fill(Qt.GlobalColor.transparent)
            p = QPainter(image)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.translate(1, 1)
            local = QRectF(0, 0, w, h)
            p.setPen(QPen(QColor(255, 255, 255, 16), 1))
            p.setBrush(with_alpha(SURFACE, 0.94))
            p.drawRoundedRect(local, h / 2, h / 2)
            icon = QPointF(28, h / 2)
            if working:
                draw_loader(p, icon, now - self.t0, PRIMARY, radius=10)
            else:
                draw_glyph(p, icon)
            p.setFont(label_font)
            p.setPen(ON_SURFACE)
            p.drawText(QRectF(50, 0, tw + 2, h), Qt.AlignmentFlag.AlignVCenter, text)
            if show_key:
                k = QRectF(w - 16 - kw, h / 2 - 12, kw, 24)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(SURFACE_HIGH)
                p.drawRoundedRect(k, 8, 8)
                p.setFont(key_font)
                p.setPen(ON_SURFACE_VARIANT)
                p.drawText(k, Qt.AlignmentFlag.AlignCenter, "Esc")
            p.end()
            self._chip = (key, image)
        g.image("chip", self._chip[1], box.adjusted(-1, -1, 1, 1), min(1.0, a), reload=fresh)
