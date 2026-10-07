import itertools
import os
import tempfile
import time

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtDBus import QDBusConnection, QDBusInterface
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from circlesearch.core import actions
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardWidget
from circlesearch.ui.effects import draw_check
from circlesearch.ui.motion import AMBIENT, MOTION, Spring, frame_timer, mix, with_alpha
from circlesearch.ui.shapes import glyph
from circlesearch.ui.theme import ON_SURFACE, ON_SURFACE_VARIANT, PALETTE, PRIMARY, SURFACE, SURFACE_HIGH

MARGIN = 32
_ids = itertools.count(1)
_open = []

KWIN_SCRIPT = """
const windows = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (const w of windows) {
    if (w.caption === %(caption)r) {
        w.keepAbove = true;
        w.skipTaskbar = true;
        w.skipPager = true;
        w.skipSwitcher = true;
        w.onAllDesktops = true;
        w.frameGeometry = {x: %(x)d, y: %(y)d, width: w.frameGeometry.width, height: w.frameGeometry.height};
    }
}
"""


def on_kde():
    return "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()


def kwin_place(caption, pos):
    if not on_kde() or QGuiApplication.platformName() != "wayland":
        return
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return
    fd, path = tempfile.mkstemp(suffix=".js", prefix="circle-search-pin-")
    with os.fdopen(fd, "w") as f:
        f.write(KWIN_SCRIPT % {"caption": caption, "x": pos.x(), "y": pos.y()})
    name = os.path.basename(path)
    scripting = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", bus)
    reply = scripting.call("loadScript", path, name)
    args = reply.arguments()
    if args and isinstance(args[0], int) and args[0] >= 0:
        for object_path in (f"/Scripting/Script{args[0]}", f"/{args[0]}"):
            run = QDBusInterface("org.kde.KWin", object_path, "org.kde.kwin.Script", bus).call("run")
            if not run.errorName():
                break

    def cleanup():
        scripting.call("unloadScript", name)
        try:
            os.unlink(path)
        except OSError:
            pass
    QTimer.singleShot(1500, cleanup)


class Pin(QWidget):
    on_close = None

    def __init__(self, content_size, radius):
        super().__init__(None)
        self.id = next(_ids)
        self.radius = radius
        self.setWindowTitle(f"Circle to Search pin {self.id}")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(content_size + QSize(2 * MARGIN, 2 * MARGIN))
        self.appear = Spring(*T.SPRING_SPATIAL)
        self.appear.value = 0.0 if AMBIENT else 1.0
        self.appear.set(1.0)
        self.leaving = None
        self._last = time.monotonic()
        self.timer = frame_timer(self, self._step)
        QShortcut(QKeySequence("Escape"), self, self.leave)
        _open.append(self)

    def show_at(self, global_pos):
        target = global_pos - QPoint(MARGIN, MARGIN)
        self.move(target)
        self.show()
        self.raise_()
        self.activateWindow()
        self._last = time.monotonic()
        self.timer.start()
        QTimer.singleShot(60, lambda: kwin_place(self.windowTitle(), target))

    def content_rect(self):
        return QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)

    def _step(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        moving = self.appear.step(dt) if MOTION > 0 else False
        if MOTION <= 0:
            self.appear.value = self.appear.target
        self.animate(self.appear.value)
        self.update()
        if self.leaving is not None and self.appear.value <= 0.02:
            self.timer.stop()
            self.close()
            return
        if not moving and not self.busy():
            self.timer.stop()

    def busy(self):
        return False

    def wake(self):
        if not self.timer.isActive():
            self._last = time.monotonic()
            self.timer.start()

    def animate(self, k):
        pass

    def leave(self):
        if self.leaving is not None:
            return
        self.leaving = time.monotonic()
        self.appear = Spring(900, 1.0, self.appear.value)
        self.appear.set(0.0)
        if MOTION <= 0:
            self.close()
            return
        self.wake()

    def closeEvent(self, e):
        if self in _open:
            _open.remove(self)
        super().closeEvent(e)
        if Pin.on_close is not None:
            QTimer.singleShot(0, Pin.on_close)

    def paint_shadow(self, p, rect, k):
        p.save()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(8):
            spread = 2 + i * 3
            p.setBrush(QColor(0, 0, 0, round(10 * k)))
            p.drawRoundedRect(rect.adjusted(-spread + 4, -spread + 8, spread - 4, spread + 2), self.radius + spread,
                              self.radius + spread)
        p.restore()


class CardPin(Pin):
    def __init__(self, card, assets, width, role):
        probe = CardWidget(None, PALETTE, ambient=False, width=width, role=role, pinned=True)
        probe.set_card(card, assets)
        size = probe.size()
        probe.deleteLater()
        super().__init__(size, T.RADIUS["hero"] if role == "hero" else T.RADIUS["card"])
        self.card_widget = CardWidget(self, PALETTE, ambient=AMBIENT, width=width, role=role, pinned=True)
        self.card_widget.set_card(card, assets)
        self.card_widget.move(MARGIN, MARGIN)
        self.card_widget.copyRequested.connect(self.copy)
        self.card_widget.openRequested.connect(actions.open_url)
        self.card_widget.saveRequested.connect(lambda path: actions.open_url("file://" + path))
        self.card_widget.runRequested.connect(lambda payload: actions.run_command(payload["command"], payload.get("stdin")))
        self.card_widget.closeRequested.connect(self.leave)
        self.effect = QGraphicsOpacityEffect(self.card_widget)
        self.card_widget.setGraphicsEffect(self.effect)
        self.animate(self.appear.value)

    def copy(self, text):
        if not actions.copy_text(text):
            QGuiApplication.clipboard().setText(text)

    def animate(self, k):
        self.effect.setOpacity(max(0.0, min(1.0, k)))
        size = self.card_widget.size()
        if self.card_widget.layout_height() + 2 * MARGIN > self.height():
            self.resize(self.width(), self.card_widget.layout_height() + 2 * MARGIN)
        lift = round((1 - min(1.0, k)) * 14)
        self.card_widget.move(MARGIN, MARGIN + lift)
        if size.height() != self.card_widget.height():
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = max(0.0, min(1.0, self.appear.value))
        r = QRectF(self.card_widget.geometry())
        self.paint_shadow(p, r, k)


class ImagePin(Pin):
    def __init__(self, image, text=""):
        dpr = image.devicePixelRatio()
        size = QSize(round(image.width() / dpr), round(image.height() / dpr))
        super().__init__(size, 14)
        self.image, self.text, self.base = image, text, size
        self.zoom = 1.0
        self.hover = Spring(*T.SPRING_EFFECTS)
        self.buttons = {}
        self.hot = None
        self.confirmed = {}
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        QShortcut(QKeySequence("Ctrl+C"), self, self.copy_image)

    def busy(self):
        return self.hover.active or any(time.monotonic() - t < 1.4 for t in self.confirmed.values())

    def _step(self):
        now = time.monotonic()
        self.hover.step(now - self._last)
        super()._step()

    def copy_image(self):
        QGuiApplication.clipboard().setImage(self.image)
        self.confirm("copy")

    def copy_text(self):
        if self.text and not actions.copy_text(self.text):
            QGuiApplication.clipboard().setText(self.text)
        self.confirm("text")

    def lens(self):
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        plain = QImage(self.image)
        plain.setDevicePixelRatio(1.0)
        plain.save(buf, "PNG")
        actions.search_image(bytes(data))
        self.confirm("lens")

    def confirm(self, name):
        self.confirmed[name] = time.monotonic()
        self.wake()

    def layout_buttons(self):
        r = self.content_rect()
        names = [("close", self.leave), ("copy", self.copy_image), ("lens", self.lens)]
        if self.text:
            names.insert(2, ("text", self.copy_text))
        s, gap = 30, 6
        x = r.right() - 8 - s
        top = r.top() + 8 if r.height() >= 90 else r.top() - s - 4
        self.buttons = {}
        for name, fn in names:
            self.buttons[name] = (QRectF(x, top, s, s), fn)
            x -= s + gap

    def enterEvent(self, e):
        self.hover.set(1.0)
        self.wake()

    def leaveEvent(self, e):
        self.hover.set(0.0)
        self.hot = None
        self.wake()

    def mouseMoveEvent(self, e):
        hot = next((n for n, (r, _) in self.buttons.items() if r.contains(e.position())), None)
        if hot != self.hot:
            self.hot = hot
            self.setCursor(Qt.CursorShape.PointingHandCursor if hot else Qt.CursorShape.SizeAllCursor)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            hit = next((fn for r, fn in self.buttons.values() if r.contains(e.position())), None)
            if hit:
                hit()
            elif self.windowHandle() is not None:
                self.windowHandle().startSystemMove()
        elif e.button() == Qt.MouseButton.RightButton:
            self.leave()

    def mouseDoubleClickEvent(self, e):
        self.leave()

    def wheelEvent(self, e):
        step = 1.1 if e.angleDelta().y() > 0 else 1 / 1.1
        zoom = min(4.0, max(0.25, self.zoom * step))
        if zoom == self.zoom:
            return
        self.zoom = zoom
        size = QSize(round(self.base.width() * zoom), round(self.base.height() * zoom))
        self.resize(size + QSize(2 * MARGIN, 2 * MARGIN))
        self.update()

    def paintEvent(self, e):
        self.layout_buttons()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        k = max(0.0, min(1.0, self.appear.value))
        r = self.content_rect()
        c = r.center()
        s = 0.94 + 0.06 * self.appear.value
        p.translate(c); p.scale(s, s); p.translate(-c)
        p.setOpacity(k)
        self.paint_shadow(p, r, k)
        clip = QPainterPath(); clip.addRoundedRect(r, self.radius, self.radius)
        p.save()
        p.setClipPath(clip)
        p.drawImage(r, self.image)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 40), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self.radius, self.radius)
        h = max(0.0, min(1.0, self.hover.value))
        if h > 0.01:
            now = time.monotonic()
            for i, (name, (b, _)) in enumerate(self.buttons.items()):
                reveal = max(0.0, min(1.0, h * 1.6 - i * 0.15))
                if reveal <= 0:
                    continue
                done = max(0.0, 1 - (now - self.confirmed.get(name, 0)) / 1.4)
                p.save()
                p.setOpacity(k * reveal)
                cb = b.center()
                grow = (0.7 + 0.3 * reveal) * (1.08 if self.hot == name else 1.0)
                p.translate(cb); p.scale(grow, grow); p.translate(-cb)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(mix(with_alpha(SURFACE, 0.92), PRIMARY, done) if done else
                           (SURFACE_HIGH if self.hot == name else with_alpha(SURFACE, 0.92)))
                p.drawEllipse(b)
                ink = mix(ON_SURFACE, QColor("#062E6F"), done) if done else (ON_SURFACE if self.hot == name else ON_SURFACE_VARIANT)
                if done:
                    draw_check(p, cb, 1.0, ink, size=5.5)
                elif name == "copy":
                    p.setPen(QPen(ink, 1.6)); p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawRoundedRect(QRectF(cb.x() - 5, cb.y() - 3, 9, 10), 2.5, 2.5)
                    p.drawRoundedRect(QRectF(cb.x() - 2, cb.y() - 7, 9, 10), 2.5, 2.5)
                elif name == "lens":
                    p.setPen(QPen(ink, 1.8)); p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QPointF(cb.x() - 1.5, cb.y() - 1.5), 5.5, 5.5)
                    p.drawLine(QPointF(cb.x() + 2.5, cb.y() + 2.5), QPointF(cb.x() + 7, cb.y() + 7))
                elif name == "text":
                    p.setPen(QPen(ink, 1.8))
                    for dy, w in ((-5, 12), (0, 12), (5, 7)):
                        p.drawLine(QPointF(cb.x() - 6, cb.y() + dy), QPointF(cb.x() - 6 + w, cb.y() + dy))
                else:
                    glyph(p, name, b.adjusted(8, 8, -8, -8), ink)
                p.restore()


def pin_card(card, assets, width, role, global_pos):
    pin = CardPin(card, assets, width, role)
    pin.show_at(global_pos)
    return pin


def pin_image(image, global_pos, text=""):
    pin = ImagePin(image, text)
    pin.show_at(global_pos)
    return pin


def open_pins():
    return list(_open)
