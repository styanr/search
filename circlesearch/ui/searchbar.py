import time

from PyQt6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFontMetrics, QLinearGradient, QPainter, QPalette, QPen
from PyQt6.QtWidgets import QAbstractButton, QGraphicsOpacityEffect, QHBoxLayout, QLineEdit, QWidget

from circlesearch.core import history
from circlesearch.ui.effects import draw_check, draw_glyph, draw_loader
from circlesearch.ui import tokens as T
from circlesearch.ui.motion import MOTION, Spring, Tween, frame_timer, lerp, mix, ramp, with_alpha
from circlesearch.ui.shapes import glyph
from circlesearch.ui.theme import ON_PRIMARY, ON_SURFACE, ON_SURFACE_VARIANT, PRIMARY, SURFACE, SURFACE_HIGH, font


FADE = 28

class PillButton(QAbstractButton):
    CHECK = 22

    def __init__(self, text, busy_text=None, done_text=None):
        super().__init__()
        self.setText(text)
        self._label, self._busy_text, self._done_text = text, busy_text, done_text
        self.setFont(font(14, 560))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.spinning = False
        self._hover, self._press, self._primary = (Spring(*T.SPRING_EFFECTS) for _ in range(3))
        self._squish, self._confirm = Spring(*T.SPRING_SPATIAL), Spring(*T.SPRING_SPATIAL)
        self._check = None
        self._clock = self._last = time.monotonic()
        self._timer = frame_timer(self, self._step)
        self.pressed.connect(lambda: self._animate(1.0, self._press, self._squish))
        self.released.connect(lambda: self._animate(0.0, self._press, self._squish))

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        widths = [fm.horizontalAdvance(self._label)]
        if self._busy_text:
            widths.append(fm.horizontalAdvance(self._busy_text) + 26)
        if self._done_text:
            widths.append(fm.horizontalAdvance(self._done_text) + self.CHECK)
        return QSize(max(widths) + 44, 46)

    def set_primary(self, on):
        self._animate(1.0 if on else 0.0, self._primary)

    def confirm(self):
        if self._done_text:
            self.setText(self._done_text)
        self._check = Tween(0.2)
        self._animate(1.0, self._primary, self._confirm)

    def set_spinning(self, on):
        self.spinning = on
        self.setText(self._busy_text if on and self._busy_text else self._label)
        self._start()

    def _start(self):
        if not self._timer.isActive():
            self._last = time.monotonic()
            self._timer.start()

    def _animate(self, target, *springs):
        for spring in springs:
            spring.set(target)
        self._start()

    def enterEvent(self, e):
        self._animate(1.0, self._hover)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._animate(0.0, self._hover)
        super().leaveEvent(e)

    def _step(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        animating = any([s.step(dt) for s in (self._hover, self._press, self._primary, self._squish, self._confirm)])
        self.update()
        if not (self.spinning or animating or (self._check is not None and not self._check.done(now))):
            self._timer.stop()

    def paintEvent(self, _):
        now = time.monotonic()
        press, hover, prim = self._press.value, self._hover.value, self._primary.value
        squish = max(0.0, self._squish.value)
        enabled = self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        scale = 1 - 0.05 * squish
        p.translate(r.center())
        p.scale(scale, scale)
        p.translate(-r.center())
        radius = max(4.0, min(r.height() / 2, lerp(lerp(r.height() / 2, 14, self._confirm.value), 11, squish)))

        bg = mix(SURFACE_HIGH, PRIMARY, prim, 1.0 if enabled else 0.55)
        fg = mix(ON_SURFACE, ON_PRIMARY, prim, 1.0 if enabled else 0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, radius, radius)
        if enabled:
            p.setBrush(with_alpha(fg, (T.HOVER_ALPHA * hover + T.PRESS_ALPHA * press) * 1.4 / 255))
            p.drawRoundedRect(r, radius, radius)

        fm = QFontMetrics(self.font())
        tw = fm.horizontalAdvance(self.text())
        sw = 26 if self.spinning else (self.CHECK if self._check is not None else 0)
        x = r.center().x() - (tw + sw) / 2
        if self.spinning:
            draw_loader(p, QPointF(x + 9, r.center().y()), now - self._clock, with_alpha(fg, 0.9), radius=8)
        elif self._check is not None:
            draw_check(p, QPointF(x + 7, r.center().y()), self._check.value(now), fg)
        p.setFont(self.font())
        p.setPen(fg)
        p.drawText(QRectF(x + sw, r.top(), tw + 2, r.height()), Qt.AlignmentFlag.AlignVCenter, self.text())


class IconButton(PillButton):
    def __init__(self, icon, tip):
        super().__init__("")
        self.icon = icon
        self.setToolTip(tip)

    def sizeHint(self):
        return QSize(46, 46)

    def paintEvent(self, _):
        hover, press = self._hover.value, self._press.value
        squish = max(0.0, self._squish.value)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        scale = 1 - 0.06 * squish
        p.translate(r.center()); p.scale(scale, scale); p.translate(-r.center())
        radius = lerp(r.height() / 2, 12, squish)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(SURFACE_HIGH)
        p.drawRoundedRect(r, radius, radius)
        p.setBrush(with_alpha(ON_SURFACE, (T.HOVER_ALPHA * hover + T.PRESS_ALPHA * press) * 1.4 / 255))
        p.drawRoundedRect(r, radius, radius)
        inset = 13 - 1.5 * hover
        glyph(p, self.icon, r.adjusted(inset, inset, -inset, -inset), mix(ON_SURFACE_VARIANT, ON_SURFACE, hover))


class RecentList(QWidget):
    picked = pyqtSignal(str)
    ROW = 44
    LIMIT = 6

    def __init__(self, parent):
        super().__init__(parent)
        self.entries = []
        self.active = -1
        self.hot = -1
        self.open = Spring(520, 0.86)
        self.t0 = time.monotonic()
        self._last = time.monotonic()
        self.timer = frame_timer(self, self._step)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hide()

    def show_for(self, bar, query=""):
        self.entries = history.recent(self.LIMIT, query)
        if not self.entries:
            self.close_list()
            return False
        self.active, self.hot = -1, -1
        width = bar.width()
        height = len(self.entries) * self.ROW + 16
        below = bar.y() + bar.height() + 10
        y = below if below + height < self.parent().height() - 16 else bar.y() - height - 10
        self.setGeometry(bar.x(), y, width, height)
        if not self.isVisible():
            self.open.value, self.t0 = 0.0, time.monotonic()
        self.open.set(1.0)
        self.show()
        self.raise_()
        self._wake()
        return True

    def close_list(self):
        if self.isVisible():
            self.open.set(0.0)
            self._wake()

    def move_active(self, step):
        if not self.entries:
            return
        self.active = (self.active + step) % len(self.entries)
        self.update()

    def current(self):
        return self.entries[self.active]["text"] if 0 <= self.active < len(self.entries) else None

    def _wake(self):
        if not self.timer.isActive():
            self._last = time.monotonic()
            self.timer.start()

    def _step(self):
        now = time.monotonic()
        moving = self.open.step(now - self._last)
        self._last = now
        if self.open.target == 0.0 and self.open.value < 0.02:
            self.hide()
            self.timer.stop()
            return
        self.update()
        if not moving and (now - self.t0) / max(MOTION, 0.01) > 0.6:
            self.timer.stop()

    def _row_at(self, pos):
        i = int((pos.y() - 8) // self.ROW)
        return i if 0 <= i < len(self.entries) else -1

    def mouseMoveEvent(self, e):
        hot = self._row_at(e.position())
        if hot != self.hot:
            self.hot = hot
            self.update()

    def leaveEvent(self, e):
        self.hot = -1
        self.update()

    def mousePressEvent(self, e):
        i = self._row_at(e.position())
        if i >= 0:
            self.picked.emit(self.entries[i]["text"])

    def paintEvent(self, _):
        k = max(0.0, min(1.0, self.open.value))
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        h = r.height() * (0.4 + 0.6 * k)
        box = QRectF(r.left(), r.top(), r.width(), h)
        p.setOpacity(min(1.0, k * 1.4))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.setBrush(SURFACE)
        p.drawRoundedRect(box, 26, 26)
        p.setClipRect(box)
        since = (time.monotonic() - self.t0) / max(MOTION, 0.01)
        f = font(15, 450)
        fm = QFontMetrics(f)
        for i, e in enumerate(self.entries):
            reveal = ramp(since, 0.04 * i, 0.25)
            reveal = 1 - (1 - reveal) ** 3
            row = QRectF(8, 8 + i * self.ROW + (1 - reveal) * 8, r.width() - 16, self.ROW)
            p.setOpacity(min(1.0, k * 1.4) * reveal)
            if i in (self.active, self.hot):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(SURFACE_HIGH if i == self.active else with_alpha(ON_SURFACE, 0.06))
                p.drawRoundedRect(row, 18, 18)
            glyph(p, "history" if e["kind"] == "selection" else "clock", QRectF(row.left() + 14, row.center().y() - 9, 18, 18),
                  ON_SURFACE_VARIANT)
            p.setFont(f)
            p.setPen(ON_SURFACE)
            text = fm.elidedText(e["text"], Qt.TextElideMode.ElideRight, int(row.width() - 60))
            p.drawText(QRectF(row.left() + 46, row.top(), row.width() - 60, row.height()), Qt.AlignmentFlag.AlignVCenter, text)


class SearchBar(QWidget):
    textSearch = pyqtSignal(str)
    imageSearch = pyqtSignal()
    copy = pyqtSignal(str)
    pin = pyqtSignal()
    recall = pyqtSignal(str)
    edited = pyqtSignal(str)

    HEIGHT = 66

    def __init__(self, parent):
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setFont(font(17, 430))
        self.edit.setFrame(False)
        self.edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; color: {ON_SURFACE.name()};"
            f" selection-background-color: {PRIMARY.name()}; selection-color: {ON_PRIMARY.name()}; }}")
        pal = self.edit.palette()
        pal.setColor(QPalette.ColorRole.PlaceholderText, ON_SURFACE_VARIANT)
        self.edit.setPalette(pal)
        self.edit.returnPressed.connect(self.run_default)
        self.edit.installEventFilter(self)

        self.text_btn = PillButton("Search text", busy_text="Reading text…")
        self.image_btn = PillButton("Search image")
        self.copy_btn = PillButton("Copy", done_text="Copied")
        self.text_btn.clicked.connect(lambda: self.textSearch.emit(self.edit.text()))
        self.image_btn.clicked.connect(self.imageSearch.emit)
        self.copy_btn.clicked.connect(lambda: self.copy.emit(self.edit.text()))
        self.pin_btn = IconButton("pin", "Pin to screen (Ctrl+P)")
        self.pin_btn.clicked.connect(self.pin.emit)
        self.recent = RecentList(parent)
        self.recent.picked.connect(self._pick)
        self._debounce = QTimer(self, singleShot=True, interval=450,
                                timeout=lambda: self.edited.emit(self.edit.text()))
        self.edit.textEdited.connect(self._text_edited)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(54, 10, 10, 10)
        layout.setSpacing(6)
        layout.addWidget(self.edit, 1)
        for b in (self.text_btn, self.image_btn, self.copy_btn, self.pin_btn):
            layout.addWidget(b)
        self.resize(820, self.HEIGHT)
        self.prefer_text = False

        self.pane_alpha = 1.0
        self.fade = QGraphicsOpacityEffect(self.edit)
        self.fade.setEnabled(False)
        self.edit.setGraphicsEffect(self.fade)
        self.edit.textChanged.connect(self._update_fade)
        self.edit.cursorPositionChanged.connect(self._update_fade)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_fade()

    def _update_fade(self, *_):
        self.layout().activate()
        g = self.edit.geometry()
        text = self.edit.text()
        overflows = QFontMetrics(self.edit.font()).horizontalAdvance(text) > g.width() - 6
        w = max(1, g.width())
        mask = QLinearGradient(0, 0, w, 0)
        mask.setColorAt(max(0.0, 1 - FADE / w), QColor(0, 0, 0, 255))
        mask.setColorAt(max(0.0, 1 - 4 / w), QColor(0, 0, 0, 0))
        self.fade.setOpacityMask(QBrush(mask))
        self.fade.setEnabled(overflows and self.edit.cursorPosition() < len(text))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(with_alpha(SURFACE, self.pane_alpha))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        draw_glyph(p, QPointF(31, r.center().y()), radius=9, width=3)

    def _text_edited(self, text):
        has_text = bool(text.strip())
        self.text_btn.setEnabled(has_text)
        self.copy_btn.setEnabled(has_text)
        if self.recent.isVisible():
            if not self.recent.show_for(self, text):
                self.recent.close_list()
        self._debounce.start()

    def _pick(self, text):
        self.recent.close_list()
        self.edit.setText(text)
        self.edit.setCursorPosition(len(text))
        self.prefer_text = True
        self.text_btn.setEnabled(True)
        self.copy_btn.setEnabled(True)
        self.text_btn.set_primary(True)
        self.image_btn.set_primary(False)
        self.recall.emit(text)

    def open_recent(self):
        return self.recent.show_for(self, self.edit.text() if self.edit.isModified() else "")

    def close_recent(self):
        self.recent.close_list()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.recent.isVisible():
            self.recent.show_for(self, self.edit.text() if self.edit.isModified() else "")

    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() == QEvent.Type.KeyPress:
            key = e.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                if not self.recent.isVisible() or self.recent.open.target == 0.0:
                    if key == Qt.Key.Key_Down:
                        self.open_recent()
                    return True
                self.recent.move_active(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.recent.isVisible() and self.recent.current():
                self._pick(self.recent.current())
                return True
        if obj is self.edit and e.type() == QEvent.Type.ShortcutOverride and e.key() == Qt.Key.Key_Escape \
                and self.recent.isVisible() and self.recent.open.target > 0:
            self.recent.close_list()
            e.accept()
            return True
        return super().eventFilter(obj, e)

    def set_selection(self, text, prefer_text, reading=False):
        self.text_btn.set_spinning(reading)
        self.edit.setPlaceholderText("Search with Google Lens")
        self.edit.setText(text)
        self.edit.setCursorPosition(0)
        has_text = bool(text.strip())
        self.prefer_text = prefer_text and has_text
        self.text_btn.setEnabled(has_text)
        self.copy_btn.setEnabled(has_text)
        self.image_btn.setEnabled(True)
        self.pin_btn.setEnabled(True)
        self.text_btn.set_primary(self.prefer_text)
        self.image_btn.set_primary(not self.prefer_text and not reading)

    def set_typing(self):
        self.set_selection("", True)
        self.edit.setPlaceholderText("Search or paste")
        self.prefer_text = True
        self.image_btn.setEnabled(False)
        self.pin_btn.setEnabled(False)
        self.text_btn.set_primary(True)
        self.image_btn.set_primary(False)

    def run_default(self):
        if self.prefer_text or (self.edit.isModified() and self.edit.text().strip()):
            self.textSearch.emit(self.edit.text())
        else:
            self.imageSearch.emit()
