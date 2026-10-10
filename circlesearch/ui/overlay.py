import bisect
import math
import os
import re
import tempfile
import threading
import time

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSizeF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QColor, QFontMetrics, QGuiApplication, QImage, QKeySequence, QPainter, QPen,
                         QShortcut)
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from circlesearch.core import actions, history, settings
from circlesearch.core.ocr import join_words
from circlesearch.core.textindex import TextIndex
from circlesearch.ui.backdrop import Backdrop, BackdropWidget
from circlesearch.ui.board import CardBoard, shadow_rect
from circlesearch.ui.capture import on_kde
from circlesearch.ui.effects import InkStroke, draw_glyph, draw_loader, lightness_at
from circlesearch.ui.motion import (AMBIENT, CARD_SPRING, MOTION, OUT_CUBIC, SPRING, SWEEP_EASE, WORD_SPRING, Animated,
                                    SpringCurve, Tween, frame_timer, lerp, lerp_rect, mix, with_alpha)
from circlesearch.ui.reader import TextReader, to_point, to_qrect, to_rect
from circlesearch.ui.searchbar import GearButton, SearchBar
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
LIFT_GROW, LIFT_MAX = 10, 0.04
FLOW = 240
FROST_ALPHA = 170 / 255
PEN_SPEED = 1600
INK_LIGHT = 0.45
MORPH = 0.34
MORPH_EASE = SpringCurve(0.9, 300.0, MORPH)
CHIP_TOP = 26


def copy_text(text):
    if not actions.copy_text(text):
        QGuiApplication.clipboard().setText(text)


SENSITIVE = ("jwt", "wifi", "otp")


# KWin draws the separate backdrop window under the overlay fine. On GNOME (mutter) it stops drawing that window as
# soon as the fullscreen overlay is clicked, and the screen goes black. So everywhere except KDE the backdrop is drawn
# inside the overlay window itself.
SINGLE_WINDOW = not on_kde()


class Canvas(QWidget):
    """Transparent layer above the GL backdrop for what the overlay paints with QPainter."""

    def __init__(self, overlay):
        super().__init__(overlay)
        self.overlay = overlay
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        self.overlay.paint_canvas(self)


class Overlay(QWidget):
    closed = pyqtSignal()
    selecting = pyqtSignal(object)
    finished = pyqtSignal(object)

    def __init__(self, screenshot: QImage, screen, instant=False, scale=None):
        super().__init__()
        self.setWindowTitle("Circle to Search")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        if SINGLE_WINDOW:
            self.backdrop = BackdropWidget(self, self)
            self.canvas = Canvas(self)
        else:
            self.backdrop = Backdrop(self)
            self.canvas = None
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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
        self.index.set_screen([])
        self.reading = False
        self.refining = False
        self._pending = None
        self.status = ""
        self.debug_dir = None
        if settings.DEBUG:
            self.debug_dir = os.path.join(settings.CACHE_DIR, "debug", time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(self.debug_dir, exist_ok=True)
        self.reader = TextReader(self.shot, self.dpr, self.debug_dir, self)
        self.reader.region_read.connect(self._region_done)
        self.reader.image_read.connect(self._image_done)
        self._started = False
        self._scan = None
        self.code_route = None
        self.colors = []
        self._logged = []
        self._pinned = None
        self.typed = False
        self.board = CardBoard(self, self._card_copy, self._card_open, self._card_pin, self._card_save, self._card_run,
                               self._card_arrived)

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
        self.morph = None
        self._snaps = []
        self._leaving = False
        self.bar_from = self.bar_to = None
        self.bar_tween = None
        self.ambient = AMBIENT
        self.pane_alpha = 1.0
        self._frosted = False
        self.energy = 0.0
        self._travel = 0.0
        self._energy_at = time.monotonic()
        self._pen_x = None
        self._speed = 0.0
        self._near = 0.0
        self._busy = 0.0
        self._phase = 0.0
        self._bounce = None
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
        self.gear = GearButton(self)
        self.gear.hide()
        self.gear.setGraphicsEffect(QGraphicsOpacityEffect(self.gear))
        self.gear.clicked.connect(self.open_settings)
        self.gear.hovered.connect(self._prerender_settings)
        self.gear_shown = Animated(0.0, 0.3, SPRING)
        self.prefs = None
        self.prefs_anim = None
        self._spare_prefs = None

        QShortcut(QKeySequence("Escape"), self, self._escape)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.do_image_search)
        QShortcut(QKeySequence("Ctrl+C"), self, self._copy_shortcut)
        QShortcut(QKeySequence("Ctrl+P"), self, self.do_pin)

    def place(self, screen):
        self.setGeometry(screen.geometry())
        if not SINGLE_WINDOW:
            self.backdrop.setScreen(screen)
            self.backdrop.setGeometry(screen.geometry())
        self.create()
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(screen)
            if not SINGLE_WINDOW:
                handle.setTransientParent(self.backdrop)
        if SINGLE_WINDOW:
            self._fit_layers()

    def _fit_layers(self):
        # the GL backdrop at the bottom, the QPainter canvas above it, every other child widget above both
        self.backdrop.setGeometry(self.rect())
        self.canvas.setGeometry(self.rect())
        self.backdrop.lower()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if SINGLE_WINDOW:
            self._fit_layers()

    def present(self):
        if SINGLE_WINDOW:
            self.showFullScreen()
            return
        self.backdrop.showFullScreen()
        self.showFullScreen()

    def update(self, *args):
        super().update(*args)
        self.backdrop.update()
        if self.canvas is not None:
            self.canvas.update(*args)

    def card_anchor(self):
        bar = QRectF(self.bar_to if self.bar_to is not None else QPointF(self.bar.pos()), QSizeF(self.bar.size()))
        return bar, self.selection if self.selection is not None else bar

    def stack_card(self, card):
        card.stackUnder(self.bar.recent)

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
        if text and len(text) <= history.SHORT and text not in self._logged and \
                not re.search(r"eyJ[\w-]{8,}\.|otpauth://|WIFI:", text):
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

    def _read_region(self, area, purpose):
        if not self.reader.available():
            return None
        token = self.reader.read_region(area, QRectF(self.rect()))
        self._pending = (purpose, token) if purpose == "select" else (purpose, token, area.center())
        return token

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
            started = self.words_t0
            self.selected_words = new
            self._start_word_reveal()
            if started is not None and not self.refining:
                self.words_t0 = started
            if self.code_route is None:
                self.bar.set_selection(new_text, self._prefers_text(new))
            self._request_cards(new_text, new)
        if self.refining:
            self.refining = False
            self._settle()
        self.update()
        if self.instant:
            self.bar.run_default()

    def showEvent(self, event):
        self.intro = Tween(0.8)
        self.chip.set(1.0)
        self.gear_shown.set(1.0)
        self.ticker.start()
        if not self._started:
            self._started = True
            QTimer.singleShot(0, self.bar._update_fade)
            self.reader.save_screenshot()
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
        self._step_energy(now)
        if self.exit is None:
            self.aurora.set(0.85 if working or self._working() else 0.5)
            idle = self.selection is None and not self.typed and self.prefs is None
            self.chip.set(1.0 if idle or self.status else 0.0)
            self.gear_shown.set(1.0 if idle else 0.0)
            self.scrim_selected.set(1.0 if self.selection is not None else 0.0)

        if self.bar_tween is not None:
            self._step_bar(now)
        self._step_gear(now)
        if self.prefs_anim is not None:
            self._step_prefs(now)
        self.board.step(now)
        if self.morph is not None and self.morph[3].done(now):
            self.morph = None
            self.update()
        if self.exit is not None and self.exit.done(now):
            self.ticker.stop()
            self.close()
            return
        if self.exit is not None:
            for _, geometry, _, _ in self._snaps:
                QWidget.update(self, geometry.adjusted(-48, -48, 48, 48).toAlignedRect())
        if self._moving(now):
            self.backdrop.update()

    def _working(self):
        return self.reading or self.refining or self.board.busy

    def _card_arrived(self, card):
        if self.ambient and self.exit is None:
            self._bounce = (time.monotonic(), card.x() + card.width() / 2)

    def _bounce_at(self, now):
        if self._bounce is None:
            return 0.0, 0.0
        t = now - self._bounce[0]
        if t > 1.2:
            self._bounce = None
            return 0.0, 0.0
        return 1.4 * math.exp(-t / 0.25) * math.sin(2 * math.pi * t / 0.55), self._bounce[1]

    def _step_energy(self, now):
        dt = max(1e-3, now - self._energy_at)
        self._energy_at = now
        busy = 1.0 if self._working() and self.ambient else 0.0
        self._busy += (busy - self._busy) * (1 - math.exp(-dt / 0.4))
        if self.ambient:
            self._phase += dt * (1 + 1.6 * self._busy)
        drawing = self.ink is not None and self.ambient
        self._speed += ((self._travel / dt if drawing else 0.0) - self._speed) * (1 - math.exp(-dt / 0.15))
        self._travel = 0.0
        if drawing:
            pos = self.ink.cursor
            near = min(1.0, max(0.0, 1 - (self.height() - pos.y()) / (self.height() * 0.6)))
            self._near += (near * near * (3 - 2 * near) - self._near) * (1 - math.exp(-dt / 0.3))
            lag = 0.5 - 0.35 * self._near
            self._pen_x = pos.x() if self._pen_x is None else self._pen_x + (pos.x() - self._pen_x) * (1 - math.exp(-dt / lag))
        target = max(min(1.0, self._speed / PEN_SPEED), 0.35 * self._near) if drawing else 0.0
        self.energy += (target - self.energy) * (1 - math.exp(-dt / (0.45 if target > self.energy else 1.2)))

    def _moving(self, now):
        if self.energy > 0.002 or self._busy > 0.002 or self._bounce is not None:
            return True
        if self.ambient or self.exit is not None or self.morph is not None or not self.intro.done(now):
            return True
        if any(a.active(now) for a in (self.aurora, self.chip, self.gear_shown, self.scrim_selected)):
            return True
        if self.prefs_anim is not None:
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

    def _step_gear(self, now):
        a = max(0.0, self.gear_shown.get(now)) if self.exit is None else 0.0
        if a <= 0.01:
            if self.gear.isVisible():
                self.gear.hide()
                self.update(shadow_rect(self.gear))
            return
        pos = QPoint(self.width() - GearButton.SIZE - CHIP_TOP, round(lerp(4, CHIP_TOP, min(1.0, a))))
        effect = self.gear.graphicsEffect()
        if pos == self.gear.pos() and self.gear.isVisible() and effect.opacity() == min(1.0, a):
            return
        old = shadow_rect(self.gear)
        self.gear.move(pos)
        effect.setOpacity(min(1.0, a))
        self.gear.show()
        self.update(old.united(shadow_rect(self.gear)))

    def _prepare_settings(self):
        if self.prefs is None and self._spare_prefs is None and self.exit is None:
            from circlesearch.ui.preferences import SettingsPanel
            panel = SettingsPanel(self, min(820, self.width() - 32), self.height() - CHIP_TOP - 16)
            panel.closeRequested.connect(self.close_settings)
            panel.openRequested.connect(self._card_open)
            self._spare_prefs = panel

    def _prerender_settings(self):
        if self.prefs is None and self._spare_prefs is None and self.exit is None:
            self._prepare_settings()
            self._spare_prefs.grab()

    def open_settings(self):
        if self.prefs is not None or self.exit is not None or self._leaving:
            return
        self._prepare_settings()
        panel, self._spare_prefs = self._spare_prefs, None
        panel.reset()
        target = QPointF((self.width() - panel.width()) / 2, CHIP_TOP)
        start = target + QPointF(0, -18)
        effect = QGraphicsOpacityEffect(panel)
        effect.setOpacity(0.0)
        panel.setGraphicsEffect(effect)
        panel.move(start.toPoint())
        panel.show()
        panel.raise_()
        self.prefs = panel
        panel.setFocus()
        self.prefs_anim = (start, target, Tween(0.5, CARD_SPRING), False)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def close_settings(self):
        panel = self.prefs
        if panel is None or (self.prefs_anim is not None and self.prefs_anim[3]):
            return
        panel.commit()
        self.setFocus()
        effect = panel.graphicsEffect()
        if effect is None:
            effect = QGraphicsOpacityEffect(panel)
            panel.setGraphicsEffect(effect)
        here = QPointF(panel.pos())
        self.prefs_anim = (here, here, Tween(0.16), effect.opacity())
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _step_prefs(self, now):
        start, end, tween, closing = self.prefs_anim
        panel = self.prefs
        old = shadow_rect(panel)
        effect = panel.graphicsEffect()
        if closing:
            effect.setOpacity(closing * (1.0 - tween.value(now)))
        else:
            k = tween.value(now)
            panel.move(QPointF(lerp(start.x(), end.x(), k), lerp(start.y(), end.y(), k)).toPoint())
            effect.setOpacity(min(1.0, tween.raw(now) * 3))
        self.update(old.united(shadow_rect(panel)))
        if not tween.done(now):
            return
        self.prefs_anim = None
        if closing:
            panel.hide()
            panel.setGraphicsEffect(None)
            self.prefs, self._spare_prefs = None, panel
        else:
            panel.setGraphicsEffect(None)

    def _escape(self):
        if self.prefs is not None and self.exit is None:
            self.close_settings()
        else:
            self.dismiss()

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
        if self.gear.isVisible():
            self._snapshot(self.gear, GearButton.SIZE / 2)
        if self.prefs is not None:
            self.prefs.commit()
            self.prefs_anim = None
            if self.prefs.isVisible():
                self._snapshot(self.prefs, self.prefs.radius())
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
        if not SINGLE_WINDOW:
            self.backdrop.close()
        super().closeEvent(e)

    def mousePressEvent(self, e):
        if self.exit is not None or self._leaving:
            return
        if self.prefs is not None:
            self.close_settings()
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._clear_selection()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            self.selecting.emit(self)
            self.ink = InkStroke(e.position())
            if self.energy < 0.02:
                self._pen_x = None
            self.backdrop.update()

    def mouseMoveEvent(self, e):
        if self.ink is not None:
            last = self.ink.cursor
            self.ink.add(e.position())
            self._travel += math.hypot(e.position().x() - last.x(), e.position().y() - last.y())
            self.backdrop.update()

    def mouseReleaseEvent(self, e):
        if self.ink is None or e.button() != Qt.MouseButton.LeftButton:
            return
        ink, self.ink = self.ink, None
        ink.add(e.position())
        bounds = ink.raw
        if max(bounds.width(), bounds.height()) < TAP_DISTANCE:
            self.backdrop.update()
            self._select_word_at(e.position())
        else:
            pad = SELECTION_PADDING
            target = bounds.adjusted(-pad, -pad, pad, pad).intersected(QRectF(self.rect()))
            ink.finish()
            self._set_selection(target, target, self._radius(target))
            self.morph = (ink, *self._morph_path(ink.line, target, self._radius(target)), Tween(MORPH, MORPH_EASE))
            self._scan = self.reader.scan(target, QRectF(self.rect()))
            self._finish_selection()
        self.update()

    def keyPressEvent(self, e):
        blocked = e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier |
                                   Qt.KeyboardModifier.MetaModifier)
        if self.selection is None and not self.typed and self.exit is None and self.prefs is None and not blocked:
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
        self.bar._text_edited(text, suggest=False)
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
        self.morph = None
        self.frame_tween = None
        self.selection = target
        self.selected_words = []
        self.refining = False
        self.typed = False
        self.code_route = None
        self.colors = []
        self._scan = None
        self.board.clear()
        self.selection_light = self._mean_lightness(target) > 0.5

    @staticmethod
    def _radius(rect):
        return min(18.0, rect.height() * 0.32, rect.width() * 0.32)

    @staticmethod
    def _ring(rect, radius):
        r = min(radius, rect.width() / 2, rect.height() / 2)
        x0, y0, x1, y1 = rect.left() + r, rect.top() + r, rect.right() - r, rect.bottom() - r
        points = []
        for cx, cy, a in ((x1, y0, -90), (x1, y1, 0), (x0, y1, 90), (x0, y0, 180)):
            for i in range(9):
                t = math.radians(a + i * 90 / 8)
                points.append((cx + r * math.cos(t), cy + r * math.sin(t)))
        points.append(points[0])
        lengths = [0.0]
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            lengths.append(lengths[-1] + math.hypot(bx - ax, by - ay))
        return points, lengths

    @staticmethod
    def _ring_at(ring, s):
        points, lengths = ring
        s %= lengths[-1]
        i = min(len(points) - 2, bisect.bisect_right(lengths, s) - 1)
        (ax, ay), (bx, by) = points[i], points[i + 1]
        k = (s - lengths[i]) / max(lengths[i + 1] - lengths[i], 1e-9)
        return ax + (bx - ax) * k, ay + (by - ay) * k

    @staticmethod
    def _ring_find(ring, x, y):
        points, lengths = ring
        best = None
        for i, ((ax, ay), (bx, by)) in enumerate(zip(points, points[1:])):
            dx, dy = bx - ax, by - ay
            k = min(1.0, max(0.0, ((x - ax) * dx + (y - ay) * dy) / max(dx * dx + dy * dy, 1e-9)))
            d = math.hypot(ax + dx * k - x, ay + dy * k - y)
            if best is None or d < best[0]:
                best = (d, lengths[i] + (lengths[i + 1] - lengths[i]) * k)
        return best[1]

    def _morph_path(self, line, rect, radius):
        ring = self._ring(rect, radius)
        total = ring[1][-1]
        c = rect.center()
        sweep, prev = 0.0, None
        for x, y, _ in line:
            angle = math.degrees(math.atan2(y - c.y(), x - c.x()))
            if prev is not None:
                sweep += (angle - prev + 180) % 360 - 180
            prev = angle
        length = max(line[-1][2], 1e-6)
        start, end = self._ring_find(ring, *line[0][:2]), self._ring_find(ring, *line[-1][:2])
        options = []
        for d in (1, -1):
            arc = (end - start) * d % total
            arc += total * max(0, round((sweep * d / 360 * total - arc) / total))
            gap = max(0.0, total - arc) / 2
            options.append([(line[0], start - d * gap)] + [(p, start + d * p[2] / length * arc) for p in line] +
                           [(line[-1], start + d * (arc + gap))])

        def cost(option):
            sample = option[1:-1:4] or option
            return sum((x - gx) ** 2 + (y - gy) ** 2 for (x, y, _), (gx, gy) in
                       ((p, self._ring_at(ring, s)) for p, s in sample)) / len(sample)

        best = min(options, key=cost)
        points, goals, prev = [], [], None
        for ((x0, y0, s0), g0), ((x1, y1, s1), g1) in zip(best, best[1:] + best[-1:]):
            n = max(1, math.ceil(abs(g1 - g0) / 4))
            for i in range(n if (x0, y0, s0, g0) != (x1, y1, s1, g1) else 1):
                k = i / n
                gx, gy = self._ring_at(ring, g0 + (g1 - g0) * k)
                angle = math.degrees(math.atan2(c.y() - gy, gx - c.x()))
                if prev is not None:
                    angle = prev + (angle - prev + 180) % 360 - 180
                prev = angle
                points.append((x0 + (x1 - x0) * k, y0 + (y1 - y0) * k, s0 + (s1 - s0) * k))
                goals.append((gx, gy, angle))
        return points, goals

    def _shape(self, now):
        target = self.selection
        radius = self._radius(target)
        if self.shape_tween is None:
            return target, radius
        p = self.shape_tween.value(now)
        start, start_radius = self.shape_from
        rect = lerp_rect(start, target, p)
        return rect, max(2.0, min(lerp(start_radius, radius, p), rect.height() / 2, rect.width() / 2))

    def _clear_selection(self):
        self.selection = None
        self.morph = None
        self.typed = False
        self.code_route = None
        self.selected_words = []
        self._pending = None
        self.reading = False
        self.refining = False
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
        area = to_rect(self.selection)
        token = None if self.index.covered(area) else self._read_region(self.selection, "select")
        self.status = ""
        if token is not None and not self.index.words_in(area):
            self.reading = True
            self._show_bar("", False, reading=True)
            return
        self.reading = False
        self._apply_selection_words(provisional=token is not None)

    def _prefers_text(self, words):
        sel = self.selection
        word_area = sum(w.rect.w * w.rect.h for w in words)
        return word_area / max(1.0, sel.width() * sel.height()) >= TEXT_COVERAGE

    def _settle(self):
        self.frame_tween = Tween(FRAME_SETTLE)
        if self.morph is not None:
            self.frame_tween.start = max(self.frame_tween.start, self.morph[3].start + self.morph[3].duration)
        self._start_word_reveal()

    def _apply_selection_words(self, provisional):
        self.selected_words = self.index.words_in(to_rect(self.selection))
        self.refining = provisional and bool(self._pending and self._pending[0] == "select")
        if self.refining:
            self.frame_tween = None
            self._start_word_reveal()
        else:
            self._settle()
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

    def backdrop_ready(self, gpu):
        self.ambient = AMBIENT and not gpu.lite
        self.pane_alpha = 1.0 if gpu.lite else FROST_ALPHA
        self.bar.pane_alpha = self.gear.pane_alpha = self.pane_alpha

    def paintEvent(self, e):
        if not SINGLE_WINDOW:
            self.paint_canvas(self)

    def paint_canvas(self, device):
        now = time.monotonic()
        fade = 1.0 - (self.exit.value(now) if self.exit is not None else 0.0)
        p = QPainter(device)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for image, geometry, opacity, _ in self._snaps:
            p.setOpacity(opacity * fade)
            p.drawImage(geometry.topLeft(), image)

    def paint_backdrop(self, g):
        now = time.monotonic()
        t = (now - self.t0) if self.ambient else 0.0
        fade = 1.0 - (self.exit.value(now) if self.exit is not None else 0.0)
        intro = self.intro.value(now)
        g.begin(self.width(), self.height(), self.backdrop.devicePixelRatio())
        if self.pane_alpha < 1.0 and not self._frosted and self.intro.done(now):
            g.frost()
            self._frosted = True
        front = self._sweep_front(intro)
        band = SWEEP_EDGE * 1.6
        glow = (self.aurora.get(now) + 0.15 * self.energy) * fade * min(1.0, intro * 1.6)
        flow, spin = self._flow(now), self._spin(now)
        wave = (1.0 - intro) ** 0.7 * fade if intro < 1.0 else 0.0
        hole = lift = None
        if self.selection is not None:
            rect, radius = self._shape(now)
            amount = self._lift(now)
            lifted, lifted_radius, _ = self._lifted(rect, radius, amount)
            hole, lift = (lifted, lifted_radius, self._opening(now)), (rect, amount)
        g.background(shade=(self.scrim_top, self.scrim_bottom, SCRIM_SELECTED * self.scrim_selected.get(now), fade),
                     sweep=(front, SWEEP_EDGE), hole=hole, lift=lift,
                     glow=(glow if glow > 0.01 else 0.0, self._phase, self.height() - AURORA_HEIGHT, AURORA_HEIGHT),
                     wave=(wave, t + 3.0, front - band * 0.55, band),
                     pen=(self._pen_x or 0.0, self.energy, self._near),
                     activity=(self._busy, *self._bounce_at(now)), light=self._light(now), panes=self._panes(fade),
                     frosted=self.pane_alpha < 1.0)
        if self.selection is not None:
            self._paint_selection(g, now, t, fade)
        if self.morph is not None:
            ink, line, goals, tween = self.morph
            g.ink(ink, fade, flow, spin, tip=False, line=line, goals=goals, morph=tween.value(now),
                  shine=self._shine(tween.raw(now)))
        if self.ink is not None:
            g.ink(self.ink, 1.0, flow, spin, light=True)
        self._paint_chip(g, now, fade)
        g.end()

    def _sweep_front(self, intro):
        return lerp(self.height() + 60, -SWEEP_EDGE - 60, intro)

    def _lift(self, now):
        if self.reading or self.frame_tween is None:
            return 0.0
        u = self.frame_tween.raw(now)
        return OUT_CUBIC.valueForProgress(min(1.0, max(0.0, (u - 0.1) / 0.9)))

    @staticmethod
    def _lifted(rect, radius, amount):
        s = 1.0 + amount * min(LIFT_MAX, LIFT_GROW / max(rect.width(), rect.height(), 1.0))
        c = rect.center()
        w, h = rect.width() * s, rect.height() * s
        return QRectF(c.x() - w / 2, c.y() - h / 2, w, h), radius * s, s

    def _flow(self, now):
        return (now - self.t0) * FLOW if self.ambient else 0.0

    def _appear(self, now):
        return 1.0 if self.morph is None or self.morph[3].done(now) else 0.0

    def _panes(self, fade):
        panes = []
        widgets = [(self.bar, SearchBar.HEIGHT / 2), (self.gear, GearButton.SIZE / 2),
                   *((c, c.radius()) for c in self.board.cards)]
        if self.prefs is not None:
            widgets.append((self.prefs, self.prefs.radius()))
        for widget, radius in widgets:
            if widget is not None and widget.isVisible():
                effect = widget.graphicsEffect()
                opacity = effect.opacity() if effect is not None else 1.0
                panes.append((QRectF(widget.geometry()), radius, opacity, 0.0 if widget is self.gear else opacity))
        panes += [(geometry, radius, opacity * fade, opacity * fade) for _, geometry, opacity, radius in self._snaps]
        return panes

    def _light(self, now):
        if self.ink is not None:
            return INK_LIGHT, self.ink
        if self.morph is not None:
            return INK_LIGHT * self._shine(self.morph[3].raw(now)), self.morph[0]
        return None

    def _opening(self, now):
        return 1.0 if self.morph is None else self.morph[3].value(now)

    @staticmethod
    def _shine(u):
        u = min(1.0, max(0.0, (u - 0.2) / 0.8))
        return 1.0 - u * u * (3 - 2 * u)

    def _spin(self, now):
        return (now - self.t0) * 160 if self.ambient else 0.0

    def _paint_selection(self, g, now, t, fade):
        source, radius = self._shape(now)
        rect, radius, scale = self._lifted(source, radius, self._lift(now))
        if self.selected_words and not self.refining:
            self._paint_words(g, now, rect, radius, fade, source.center(), scale)
        fade *= self._appear(now)

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

    def _paint_words(self, g, now, rect, radius, fade, center, scale):
        key = (id(self.selected_words), self.words_t0, rect.getRect(), radius, fade)
        if self._word_batch is None or self._word_batch[0] != key or self._words_active(now):
            light, dark = [], []
            for i, w in enumerate(self.selected_words):
                u = self._word_progress(i, now)
                if u <= 0.0:
                    continue
                a = min(1.0, u * 2.5) * fade
                r = to_qrect(w.rect).adjusted(-3, -2, 3, 2)
                r.setWidth(r.width() * WORD_SPRING.valueForProgress(u))
                r = QRectF(center.x() + (r.x() - center.x()) * scale, center.y() + (r.y() - center.y()) * scale,
                           r.width() * scale, r.height() * scale)
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
        box = QRectF((self.width() - w) / 2, lerp(4, CHIP_TOP, min(1.0, a)), w, h)
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
