import time

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFontMetrics, QLinearGradient, QPainter, QPalette, QPen
from PyQt6.QtWidgets import QAbstractButton, QHBoxLayout, QLineEdit, QWidget

from circlesearch.ui.effects import draw_check, draw_glyph, draw_loader
from circlesearch.ui import tokens as T
from circlesearch.ui.motion import Spring, Tween, frame_timer, lerp, mix, with_alpha
from circlesearch.ui.theme import ON_PRIMARY, ON_SURFACE, ON_SURFACE_VARIANT, PRIMARY, SURFACE, SURFACE_HIGH, font


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


class SearchBar(QWidget):
    textSearch = pyqtSignal(str)
    imageSearch = pyqtSignal()
    copy = pyqtSignal(str)

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

        self.text_btn = PillButton("Search text", busy_text="Reading text…")
        self.image_btn = PillButton("Search image")
        self.copy_btn = PillButton("Copy", done_text="Copied")
        self.text_btn.clicked.connect(lambda: self.textSearch.emit(self.edit.text()))
        self.image_btn.clicked.connect(self.imageSearch.emit)
        self.copy_btn.clicked.connect(lambda: self.copy.emit(self.edit.text()))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(54, 10, 10, 10)
        layout.setSpacing(6)
        layout.addWidget(self.edit, 1)
        for b in (self.text_btn, self.image_btn, self.copy_btn):
            layout.addWidget(b)
        self.resize(820, self.HEIGHT)
        self.prefer_text = False

        self.edge_fade = EdgeFade(self)
        self.edit.textChanged.connect(self._update_fade)
        self.edit.cursorPositionChanged.connect(self._update_fade)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_fade()

    def _update_fade(self, *_):
        self.layout().activate()
        g = self.edit.geometry()
        self.edge_fade.setGeometry(g.right() - EdgeFade.WIDTH + 1, g.top(), EdgeFade.WIDTH, g.height())
        text = self.edit.text()
        overflows = QFontMetrics(self.edit.font()).horizontalAdvance(text) > g.width() - 6
        self.edge_fade.setVisible(overflows and self.edit.cursorPosition() < len(text))
        self.edge_fade.raise_()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(SURFACE)
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        draw_glyph(p, QPointF(31, r.center().y()), radius=9, width=3)

    def set_selection(self, text, prefer_text, reading=False):
        self.text_btn.set_spinning(reading)
        self.edit.setPlaceholderText("Search with Google Lens")
        self.edit.setText(text)
        self.edit.setCursorPosition(0)
        has_text = bool(text.strip())
        self.prefer_text = prefer_text and has_text
        self.text_btn.setEnabled(has_text)
        self.copy_btn.setEnabled(has_text)
        self.text_btn.set_primary(self.prefer_text)
        self.image_btn.set_primary(not self.prefer_text)

    def run_default(self):
        if self.prefer_text or (self.edit.isModified() and self.edit.text().strip()):
            self.textSearch.emit(self.edit.text())
        else:
            self.imageSearch.emit()


class EdgeFade(QWidget):
    WIDTH = 28

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0.0, with_alpha(SURFACE, 0.0))
        g.setColorAt(0.85, SURFACE)
        p.fillRect(self.rect(), QBrush(g))

