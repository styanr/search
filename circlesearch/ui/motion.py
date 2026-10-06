import configparser
import math
import os
import time

from PyQt6.QtCore import QEasingCurve, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication


def motion_factor():
    parser = configparser.RawConfigParser(strict=False)
    try:
        parser.read(os.path.expanduser("~/.config/kdeglobals"))
        return max(0.0, parser.getfloat("KDE", "AnimationDurationFactor", fallback=1.0))
    except (configparser.Error, ValueError):
        return 1.0


MOTION = motion_factor()
AMBIENT = MOTION > 0

OUT_CUBIC = QEasingCurve(QEasingCurve.Type.OutCubic)
SWEEP_EASE = QEasingCurve(QEasingCurve.Type.InOutSine)
SPRING = QEasingCurve(QEasingCurve.Type.OutBack)
SPRING.setOvershoot(1.7)
WORD_SPRING = QEasingCurve(QEasingCurve.Type.OutBack)
WORD_SPRING.setOvershoot(1.2)


class SpringCurve:
    def __init__(self, damping=0.8, stiffness=380.0, duration=0.5):
        self.z, self.w, self.d = damping, math.sqrt(stiffness), duration

    def valueForProgress(self, p):
        t = p * self.d
        if p >= 1.0:
            return 1.0
        wd = self.w * math.sqrt(1 - self.z ** 2)
        decay = math.exp(-self.z * self.w * t)
        return 1 - decay * (math.cos(wd * t) + self.z * self.w / wd * math.sin(wd * t))


CARD_SPRING = SpringCurve()


def lerp(a, b, p):
    return a + (b - a) * p


def lerp_rect(a, b, p):
    return QRectF(lerp(a.x(), b.x(), p), lerp(a.y(), b.y(), p),
                  lerp(a.width(), b.width(), p), lerp(a.height(), b.height(), p))


def ramp(x, start, length):
    return min(1.0, max(0.0, (x - start) / length))


def mix(a, b, p, alpha=1.0):
    return QColor.fromRgbF(lerp(a.redF(), b.redF(), p), lerp(a.greenF(), b.greenF(), p),
                           lerp(a.blueF(), b.blueF(), p), lerp(a.alphaF(), b.alphaF(), p) * alpha)


def with_alpha(color, alpha):
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def frame_timer(parent, callback):
    screen = QGuiApplication.primaryScreen()
    rate = screen.refreshRate() if screen is not None else 60.0
    timer = QTimer(parent, interval=max(4, round(1000 / (rate or 60.0))), timeout=callback)
    timer.setTimerType(Qt.TimerType.PreciseTimer)
    return timer


class Tween:
    def __init__(self, duration, curve=OUT_CUBIC):
        self.start = time.monotonic()
        self.duration = duration * MOTION
        self.curve = curve

    def raw(self, now):
        if self.duration <= 0:
            return 1.0
        return min(1.0, max(0.0, (now - self.start) / self.duration))

    def value(self, now):
        return self.curve.valueForProgress(self.raw(now))

    def done(self, now):
        return self.raw(now) >= 1.0


class Animated:
    def __init__(self, value, duration=0.25, curve=OUT_CUBIC):
        self._from = self._to = value
        self.duration, self.curve = duration, curve
        self._tween = None

    def set(self, target, duration=None, curve=None):
        if target == self._to:
            return
        now = time.monotonic()
        self._from, self._to = self.get(now), target
        self._tween = Tween(self.duration if duration is None else duration, curve or self.curve)

    def get(self, now):
        if self._tween is None:
            return self._to
        return lerp(self._from, self._to, self._tween.value(now))

    def active(self, now):
        return self._tween is not None and not self._tween.done(now)
