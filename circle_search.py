#!/usr/bin/env python3

import argparse
import base64
import configparser
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass

from PyQt6.QtCore import (QEasingCurve, QLocale, QLockFile, QObject,
                          QPointF, QRect, QRectF, QSize, QSizeF, Qt, QTimer, pyqtSignal)
from PyQt6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QFontDatabase,
                         QFontMetrics, QGuiApplication, QImage, QKeySequence,
                         QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap,
                         QRadialGradient, QShortcut)
from PyQt6 import sip
from PyQt6.QtWidgets import (QAbstractButton, QApplication, QGraphicsOpacityEffect,
                             QHBoxLayout, QLineEdit, QWidget)

from locale_profile import PROFILE

HELP = """Circle to Search for the desktop.

Freezes the screen, lets you circle (or tap) anything, then searches the
selected text on Google or the selected pixels on Google Lens.

  circle / scribble   select a region
  tap                 select the word under the cursor
  Enter               run the suggested search
  Ctrl+Enter          force an image (Lens) search
  Ctrl+C              copy the recognised text
  right-click         clear the selection
  Esc                 close

Short selections can show info cards (definitions, translations, places, money,
times, colours). Set CIRCLE_SEARCH_CARDS=0 to turn them off.
CIRCLE_SEARCH_DEBUG=1 saves each screenshot and OCR result to ~/.cache/circle-search/debug/.
"""

TEXT_SEARCH_URL = "https://www.google.com/search?q={}"
LENS_UPLOAD_URL = "https://lens.google.com/v3/upload?hl=en&re=df&ep=gsbubb"
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "circle-search")

OCR_SCALE = 2
OCR_MARGIN = 28
TAP_BAND = QSizeF(900, 96)
CARDS = os.environ.get("CIRCLE_SEARCH_CARDS", "1") != "0"
MAX_CARDS = 5
CARD_PRIORITY = {"weather": 1, "facts": 2, "repo": 2, "money": 3, "package": 3, "holidays": 4, "trends": 5, "nearby": 6}
CARD_IDENTITY = {"facts", "holidays"}
CARD_BALANCE = 160
CARD_BATCH_MS = 250
CARD_GAP = 12
DEBUG = os.environ.get("CIRCLE_SEARCH_DEBUG", "0") == "1"
TAP_DISTANCE = 6
SELECTION_PADDING = 6
TEXT_COVERAGE = 0.12


KWIN_GRAB = os.path.join(os.path.dirname(os.path.realpath(__file__)), "kwin-grab")


def start_kwin_grab():
    if not os.access(KWIN_GRAB, os.X_OK):
        return None
    try:
        return subprocess.Popen([KWIN_GRAB], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return None


def finish_kwin_grab(proc):
    if proc is None:
        return None
    try:
        out, _ = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        return None
    if proc.returncode != 0:
        return None
    header, _, pixels = out.partition(b"\n")
    width, height, stride, fmt, _scale = header.split()
    image = QImage(pixels, int(width), int(height), int(stride), QImage.Format(int(fmt)))
    return image.copy()


def grab_with_tool():
    commands = [
        ["spectacle", "-b", "-n", "-f", "-o"],
        ["grim"],
        ["gnome-screenshot", "-f"],
    ]
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        for cmd in commands:
            if shutil.which(cmd[0]) is None:
                continue
            try:
                subprocess.run(cmd + [path], check=True, timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (subprocess.SubprocessError, OSError):
                continue
            image = QImage(path)
            if not image.isNull():
                return image
        return None
    finally:
        os.unlink(path)


def capture_screen():
    return finish_kwin_grab(start_kwin_grab()) or grab_with_tool()


@dataclass
class Word:
    text: str
    rect: QRectF
    line: tuple
    order: int


def parse_tsv(tsv, scale, offset=QPointF(0, 0), pass_id=0):
    words = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = cols[11].strip()
        if not text or float(cols[10]) < 30:
            continue
        x, y, w, h = (int(c) / scale for c in cols[6:10])
        words.append(Word(text, QRectF(offset.x() + x, offset.y() + y, w, h),
                          (pass_id, int(cols[2]), int(cols[3]), int(cols[4])), pass_id * 1_000_000 + len(words)))
    return words


_ocr_langs = None


def ocr_langs():
    global _ocr_langs
    if _ocr_langs is None:
        try:
            out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=5).stdout
            have = set(out.split()[1:]) if out else set()
        except (OSError, subprocess.SubprocessError):
            have = set()
        own = QLocale.languageToCode(QLocale(PROFILE.language).language(), QLocale.LanguageCodeType.ISO639Part2T)
        extra = re.split(r"[+,\s]+", os.environ.get("CIRCLE_SEARCH_OCR_LANGUAGES", ""))
        wanted = dict.fromkeys(["eng", own, *extra])
        _ocr_langs = "+".join(lang for lang in wanted if lang and lang in have) or "eng"
    return _ocr_langs


def run_ocr(image, scale, offset, pass_id, background=False, debug_dir=None):
    big = image.scaled(image.size() * OCR_SCALE, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    fd, path = tempfile.mkstemp(suffix=".bmp", dir="/dev/shm" if os.path.isdir("/dev/shm") else None)
    os.close(fd)
    cmd = ["tesseract", path, "-", "-l", ocr_langs(), "--psm", "3", "tsv"]
    if background and shutil.which("nice"):
        cmd = ["nice", "-n", "10"] + cmd
    try:
        big.save(path, "BMP")
        tsv = subprocess.run(cmd, capture_output=True).stdout.decode(errors="replace")
    except OSError:
        tsv = ""
    finally:
        os.unlink(path)
    if debug_dir:
        image.save(os.path.join(debug_dir, f"ocr-{pass_id:02d}.png"))
        with open(os.path.join(debug_dir, f"ocr-{pass_id:02d}.tsv"), "w") as f:
            f.write(tsv)
    return parse_tsv(tsv, scale, offset, pass_id)


def join_words(words):
    lines, current, last_key = [], [], None
    for w in sorted(words, key=lambda w: w.order):
        if last_key is not None and w.line != last_key:
            lines.append(" ".join(current))
            current = []
        current.append(w.text)
        last_key = w.line
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def open_url(url):
    subprocess.Popen(["xdg-open", url], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def search_text(query):
    query = " ".join(query.split())
    open_url(TEXT_SEARCH_URL.format(urllib.parse.quote_plus(query)))


LENS_PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Google Lens</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; height: 100vh; display: grid; place-items: center;
         background: #131418; color: #a6a9b4; font: 15px system-ui, sans-serif; }
</style>
<p id="msg">Sending your selection to Google Lens…</p>
<form id="lens" method="post" enctype="multipart/form-data" action="{action}">
  <input type="file" name="encoded_image" hidden>
</form>
<script>
  if (sessionStorage.getItem("sent")) {
    // came back here with the Back button: don't upload again
    document.getElementById("msg").textContent = "Your selection was sent to Google Lens.";
  } else {
    sessionStorage.setItem("sent", "1");
    const bytes = Uint8Array.from(atob("{image}"), c => c.charCodeAt(0));
    const files = new DataTransfer();
    files.items.add(new File([bytes], "selection.png", { type: "image/png" }));
    const form = document.getElementById("lens");
    form.encoded_image.files = files.files;
    form.action += "&st=" + Date.now();
    form.submit();
  }
</script>
</html>
"""


def search_image(png_bytes):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cutoff = time.time() - 600
    for name in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, name)
        if name.startswith("lens-") and os.path.getmtime(path) < cutoff:
            os.unlink(path)
    fd, path = tempfile.mkstemp(prefix="lens-", suffix=".html", dir=CACHE_DIR)
    with os.fdopen(fd, "w") as f:
        f.write(LENS_PAGE.replace("{action}", LENS_UPLOAD_URL)
                         .replace("{image}", base64.b64encode(png_bytes).decode()))
    open_url(pathlib.Path(path).as_uri())


def copy_text(text):
    if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text.encode(), check=False)
    else:
        QGuiApplication.clipboard().setText(text)


FONT_FILE = os.path.join(os.path.dirname(os.path.realpath(__file__)), "fonts", "GoogleSansFlex.ttf")
FONT_FAMILY = "Google Sans Flex"
FALLBACK_FONT_FILE = os.path.join(os.path.dirname(FONT_FILE), "GoogleSans.ttf")
FALLBACK_FONT_FAMILY = "Google Sans"

SURFACE = QColor("#1B1C21")
SURFACE_HIGH = QColor("#2B2D35")
ON_SURFACE = QColor("#ECEDF3")
ON_SURFACE_VARIANT = QColor("#A6A9B4")
PRIMARY = QColor("#A8C7FA")
ON_PRIMARY = QColor("#062E6F")
SCRIM = QColor(6, 8, 14)
GOOGLE = [QColor("#4285F4"), QColor("#EA4335"), QColor("#FBBC05"), QColor("#34A853")]

SCRIM_TOP, SCRIM_BOTTOM = 0.40, 0.60
SCRIM_LIGHT = 0.30, 0.48
SCRIM_SELECTED = 0.14
HIGHLIGHT_LIGHT = QColor("#C2D7FB")
HIGHLIGHT_DARK = QColor("#24406E")
SWEEP_EDGE = 260
AURORA_HEIGHT = 200


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
SHIMMER_SWEEP, SHIMMER_PERIOD = 1.1, 1.6
SPRING = QEasingCurve(QEasingCurve.Type.OutBack)
SPRING.setOvershoot(1.7)
WORD_SPRING = QEasingCurve(QEasingCurve.Type.OutBack)
WORD_SPRING.setOvershoot(1.2)
WORD_REVEAL, WORD_CASCADE = 0.22, 0.28
FRAME_SETTLE = 0.5


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


def mix(a, b, p, alpha=1.0):
    return QColor.fromRgbF(lerp(a.redF(), b.redF(), p), lerp(a.greenF(), b.greenF(), p),
                           lerp(a.blueF(), b.blueF(), p), lerp(a.alphaF(), b.alphaF(), p) * alpha)


def with_alpha(color, alpha):
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


def ui_font(px, weight=450, roundness=100):
    f = QFont()
    f.setFamilies([FONT_FAMILY, FALLBACK_FONT_FAMILY])
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(min(900, max(100, round(weight / 100) * 100))))
    f.setVariableAxis(QFont.Tag.fromString("wght"), weight)
    f.setVariableAxis(QFont.Tag.fromString("ROND"), roundness)
    return f


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


def draw_spinner(p, center, t, color, radius=8, width=2.6):
    span = 30 + 230 * (0.5 - 0.5 * math.cos(t * 4.4))
    start = -(t * 320 + 0.5 * span) % 360
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius),
              int(start * 16), int(span * 16))


def draw_glyph(p, center, radius=8, width=2.8, alpha=1.0):
    box = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
    for i, hue in enumerate(GOOGLE):
        p.setPen(QPen(with_alpha(hue, alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(box, int((90 - i * 90 - 14) * 16), int(-62 * 16))


def draw_check(p, center, progress, color, size=7.0):
    a = QPointF(center.x() - size * 0.75, center.y())
    b = QPointF(center.x() - size * 0.2, center.y() + size * 0.55)
    c = QPointF(center.x() + size * 0.85, center.y() - size * 0.6)
    first = math.hypot(b.x() - a.x(), b.y() - a.y())
    second = math.hypot(c.x() - b.x(), c.y() - b.y())
    done = progress * (first + second)
    path = QPainterPath(a)
    if done <= first:
        path.lineTo(a + (b - a) * (done / first))
    else:
        path.lineTo(b)
        path.lineTo(b + (c - b) * ((done - first) / second))
    p.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def google_gradient(center, angle, alpha=1.0):
    g = QConicalGradient(center, angle)
    for i, hue in enumerate(GOOGLE + GOOGLE[:1]):
        g.setColorAt(i / len(GOOGLE), with_alpha(hue, alpha))
    return g


def aurora_image(width, height, t, strength, anchor=0.95, seed=0.0, feather=False):
    w, h = max(8, int(width / 10)), max(6, int(height / 10))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    n = len(GOOGLE)
    for i, hue in enumerate(GOOGLE):
        k = i * 1.7 + seed
        cx = w * ((i + 0.5) / n + 0.07 * math.sin(t * 0.31 + k))
        cy = h * (anchor + 0.08 * math.sin(t * 0.47 + k * 1.3))
        rx = w * (0.32 + 0.06 * math.sin(t * 0.39 + k * 0.7))
        ry = h * (0.80 + 0.12 * math.sin(t * 0.57 + k * 2.1))
        g = QRadialGradient(QPointF(0, 0), 1.0)
        g.setColorAt(0.0, with_alpha(hue, 0.85 * strength))
        g.setColorAt(0.45, with_alpha(hue, 0.35 * strength))
        g.setColorAt(1.0, with_alpha(hue, 0.0))
        p.save()
        p.translate(cx, cy)
        p.scale(rx, ry)
        p.fillRect(QRectF(-1, -1, 2, 2), g)
        p.restore()
    if feather:
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        mask = QLinearGradient(0, 0, 0, h)
        for stop, a in ((0.0, 0), (0.3, 255), (0.7, 255), (1.0, 0)):
            mask.setColorAt(stop, QColor(0, 0, 0, a))
        p.fillRect(QRectF(0, 0, w, h), QBrush(mask))
    p.end()
    return img


def lightness_at(image, points):
    d = image.devicePixelRatio()
    w, h = image.width() - 1, image.height() - 1
    vals = sorted(QColor(image.pixel(int(min(max(x * d, 0), w)), int(min(max(y * d, 0), h)))).lightnessF()
                  for x, y in points)
    return vals[len(vals) // 2] if vals else 0.0


def hue_at(distance):
    x = (distance / 220.0) % len(GOOGLE)
    i = int(x)
    return mix(GOOGLE[i], GOOGLE[(i + 1) % len(GOOGLE)], x - i)


class InkStroke:
    GLOW_SCALE = 8
    MIN_STEP = 4.0
    SMOOTHING = 0.25
    CORE_WIDTH, GLOW_WIDTH = 6, 20
    GLOW_SPREAD = 5
    TAPER = 60
    TIP_RADIUS = 22
    PAD = 36

    def __init__(self, size, dpr, start):
        self.core = QImage(size * dpr, QImage.Format.Format_ARGB32_Premultiplied)
        self.core.setDevicePixelRatio(dpr)
        self.core.fill(0)
        self.glow = QImage(size.width() // self.GLOW_SCALE + 2, size.height() // self.GLOW_SCALE + 2,
                           QImage.Format.Format_ARGB32_Premultiplied)
        self.glow.fill(0)
        self.points = [start]
        self._extent = [start.x(), start.y(), start.x(), start.y()]
        self.mid = start
        self.cursor = start
        self.length = 0.0
        self._last_highlight = None
        self.bounds = QRectF(start, start).adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)

    @property
    def raw(self):
        x0, y0, x1, y1 = self._extent
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def _tail_rect(self):
        return QRectF(self.mid, self.cursor).normalized().adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD)

    def add(self, pos):
        dirty = self._tail_rect()
        self.cursor = pos
        e = self._extent
        e[:] = min(e[0], pos.x()), min(e[1], pos.y()), max(e[2], pos.x()), max(e[3], pos.y())
        last = self.points[-1]
        smoothed = last + (pos - last) * self.SMOOTHING
        if (smoothed - last).manhattanLength() >= self.MIN_STEP:
            self.points.append(smoothed)
            new_mid = (last + smoothed) / 2
            path = QPainterPath(self.mid)
            path.quadTo(last, new_mid)
            self._commit(path)
            dirty = dirty.united(path.boundingRect().adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD))
            self.mid = new_mid
        dirty = dirty.united(self._tail_rect())
        self.bounds = self.bounds.united(dirty)
        return dirty

    def finish(self):
        path = QPainterPath(self.mid)
        path.lineTo(self.cursor if self.cursor != self.mid else self.mid + QPointF(0.1, 0))
        self._commit(path)
        self.mid = self.cursor
        return self.bounds

    def _taper(self, distance):
        return min(1.0, 0.45 + 0.55 * distance / self.TAPER)

    def _pens(self, color, taper=1.0):
        cap, join = Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin
        return (QPen(color, self.CORE_WIDTH * taper, Qt.PenStyle.SolidLine, cap, join),
                QPen(mix(color, QColor("white"), 0.8), 2 * taper, Qt.PenStyle.SolidLine, cap, join))

    def _commit(self, path):
        seg = path.length()
        color = hue_at(self.length + seg / 2)
        taper = self._taper(self.length + seg / 2)
        self.length += seg
        core, highlight = self._pens(color, taper)
        p = QPainter(self.core)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.strokePath(path, core)
        if self._last_highlight is not None:
            p.strokePath(*self._last_highlight)
        p.strokePath(path, highlight)
        self._last_highlight = (path, highlight)
        p.end()
        p = QPainter(self.glow)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(1 / self.GLOW_SCALE, 1 / self.GLOW_SCALE)
        p.strokePath(path, QPen(color, self.GLOW_WIDTH * taper, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.end()

    def paint(self, p, clip, alpha=1.0, tip=True, fading=False):
        area = QRectF(clip).intersected(self.bounds)
        if alpha <= 0.01 or area.isEmpty():
            return
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        s, k = self.GLOW_SCALE, self.GLOW_SPREAD
        offsets = ((0, 0),) if fading else ((0, 0), (-k, -k), (k, -k), (-k, k), (k, k))
        p.setOpacity(min(1.0, (0.6 if fading else 0.22) * alpha))
        for dx, dy in offsets:
            src = area.translated(dx, dy)
            p.drawImage(area, self.glow, QRectF(src.x() / s, src.y() / s, src.width() / s, src.height() / s))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setOpacity(alpha)
        d = self.core.devicePixelRatio()
        p.drawImage(area, self.core, QRectF(area.x() * d, area.y() * d, area.width() * d, area.height() * d))
        color = hue_at(self.length)
        if self.cursor != self.mid:
            tail = QPainterPath(self.mid)
            tail.lineTo(self.cursor)
            for pen in self._pens(color, self._taper(self.length)):
                p.setPen(pen)
                p.drawPath(tail)
        if tip:
            g = QRadialGradient(self.cursor, self.TIP_RADIUS)
            g.setColorAt(0.0, with_alpha(mix(color, QColor("white"), 0.35), 0.5 * alpha))
            g.setColorAt(0.4, with_alpha(color, 0.22 * alpha))
            g.setColorAt(1.0, with_alpha(color, 0.0))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(self.cursor, self.TIP_RADIUS, self.TIP_RADIUS)
        p.restore()


class PillButton(QAbstractButton):
    CHECK = 22

    def __init__(self, text, busy_text=None, done_text=None):
        super().__init__()
        self.setText(text)
        self._label, self._busy_text, self._done_text = text, busy_text, done_text
        self.setFont(ui_font(14, 560))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.spinning = False
        self._press = Animated(0.0)
        self._hover = Animated(0.0, 0.15)
        self._primary = Animated(0.0, 0.3)
        self._confirm = Animated(0.0, 0.3, SPRING)
        self._check = None
        self._clock = time.monotonic()
        self._timer = frame_timer(self, self._step)
        self.pressed.connect(lambda: self._animate(self._press, 1.0, 0.12, OUT_CUBIC))
        self.released.connect(lambda: self._animate(self._press, 0.0, 0.45, SPRING))

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        widths = [fm.horizontalAdvance(self._label)]
        if self._busy_text:
            widths.append(fm.horizontalAdvance(self._busy_text) + 26)
        if self._done_text:
            widths.append(fm.horizontalAdvance(self._done_text) + self.CHECK)
        return QSize(max(widths) + 44, 46)

    def set_primary(self, on):
        self._animate(self._primary, 1.0 if on else 0.0)

    def confirm(self):
        if self._done_text:
            self.setText(self._done_text)
        self._check = Tween(0.2)
        self._primary.set(1.0, 0.2)
        self._animate(self._confirm, 1.0)

    def set_spinning(self, on):
        self.spinning = on
        self.setText(self._busy_text if on and self._busy_text else self._label)
        self._timer.start()

    def _animate(self, value, target, duration=None, curve=None):
        value.set(target, duration, curve)
        self._timer.start()

    def enterEvent(self, e):
        self._animate(self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._animate(self._hover, 0.0)
        super().leaveEvent(e)

    def _step(self):
        now = time.monotonic()
        self.update()
        animating = any(a.active(now) for a in (self._press, self._hover, self._primary, self._confirm))
        if not (self.spinning or animating or (self._check is not None and not self._check.done(now))):
            self._timer.stop()

    def paintEvent(self, _):
        now = time.monotonic()
        press, hover, prim = self._press.get(now), self._hover.get(now), self._primary.get(now)
        enabled = self.isEnabled()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        scale = 1 - 0.035 * press
        p.translate(r.center())
        p.scale(scale, scale)
        p.translate(-r.center())
        radius = lerp(lerp(r.height() / 2, 14, self._confirm.get(now)), 11, max(0.0, press))

        bg = mix(SURFACE_HIGH, PRIMARY, prim, 1.0 if enabled else 0.55)
        fg = mix(ON_SURFACE, ON_PRIMARY, prim, 1.0 if enabled else 0.45)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, radius, radius)
        if enabled:
            p.setBrush(with_alpha(fg, 0.08 * hover + 0.10 * press))
            p.drawRoundedRect(r, radius, radius)

        fm = QFontMetrics(self.font())
        tw = fm.horizontalAdvance(self.text())
        sw = 26 if self.spinning else (self.CHECK if self._check is not None else 0)
        x = r.center().x() - (tw + sw) / 2
        if self.spinning:
            draw_spinner(p, QPointF(x + 9, r.center().y()), now - self._clock,
                         with_alpha(fg, 0.9), radius=7, width=2.2)
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
        self.edit.setFont(ui_font(17, 430))
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


class OcrResult(QObject):
    done = pyqtSignal(list)
    region = pyqtSignal(int, object, list)


class Overlay(QWidget):
    def __init__(self, screenshot: QImage, screen, instant=False):
        super().__init__()
        self.setWindowTitle("Circle to Search")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.instant = instant

        self.dpr = screen.devicePixelRatio()
        geo = screen.geometry()
        phys = QRect(round(geo.x() * self.dpr), round(geo.y() * self.dpr),
                     round(geo.width() * self.dpr), round(geo.height() * self.dpr))
        if screenshot.size() != phys.size():
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
        self.screen_words = None
        self.regions = []
        self.words = None
        self.reading = False
        self._pending = None
        self._ocr_token = 0
        self._pass_id = 0
        self.status = ""
        self.ocr = None
        self.ocr_result = OcrResult()
        self.ocr_result.done.connect(self._ocr_done)
        self.ocr_result.region.connect(self._region_done)
        self.debug_dir = None
        if DEBUG:
            self.debug_dir = os.path.join(CACHE_DIR, "debug", time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(self.debug_dir, exist_ok=True)
        self.cards = []
        self._card_col = {}
        self._board_cols = None
        self._pending_cards = []
        self._card_anims = {}
        self.fetcher = None
        self._card_text = None
        self._card_token = None

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
        self._last_shape = None
        self.ghost = None
        self._snaps = []
        self._leaving = False
        self.bar_from = self.bar_to = None
        self.bar_tween = None
        self._chip_rect = QRectF()
        self._last_front = None
        self._shadows = {}
        self.ticker = frame_timer(self, self._tick)

        self.bar = SearchBar(self)
        self.bar.hide()
        self.bar.textSearch.connect(self.do_text_search)
        self.bar.imageSearch.connect(self.do_image_search)
        self.bar.copy.connect(self.do_copy)

        QShortcut(QKeySequence("Escape"), self, self.dismiss)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.do_image_search)
        QShortcut(QKeySequence("Ctrl+C"), self, self._copy_shortcut)


    def _start_ocr(self):
        if shutil.which("tesseract") is None:
            self.words = []
            return
        shot, scale, result = self.shot.copy(), OCR_SCALE * self.dpr, self.ocr_result
        debug_dir = self.debug_dir
        self._pass_id += 1
        pass_id = self._pass_id

        def work():
            if debug_dir:
                shot.save(os.path.join(debug_dir, "screenshot.png"))
            result.done.emit(run_ocr(shot, scale, QPointF(0, 0), pass_id, background=True, debug_dir=debug_dir))

        self.ocr = threading.Thread(target=work, daemon=True)
        self.ocr.start()

    def _read_region(self, area, purpose):
        if shutil.which("tesseract") is None:
            return None
        self._ocr_token += 1
        token = self._ocr_token
        self._pass_id += 1
        pass_id = self._pass_id
        bounds = QRectF(self.rect())
        crop = area.adjusted(-OCR_MARGIN, -OCR_MARGIN, OCR_MARGIN, OCR_MARGIN).intersected(bounds)
        inner = area.intersected(bounds)
        d = self.dpr
        image = self.shot.copy(QRect(round(crop.x() * d), round(crop.y() * d),
                                     round(crop.width() * d), round(crop.height() * d)))
        image.setDevicePixelRatio(1.0)
        scale, result, debug_dir = OCR_SCALE * d, self.ocr_result, self.debug_dir

        def work():
            words = run_ocr(image, scale, crop.topLeft(), pass_id, debug_dir=debug_dir)
            result.region.emit(token, inner, [w for w in words if inner.contains(w.rect.center())])

        threading.Thread(target=work, daemon=True).start()
        self._pending = (purpose, token) if purpose == "select" else (purpose, token, area.center())
        return token

    def _known_words(self):
        if not self.regions and self.screen_words is None:
            return None
        covered, out = [], []
        for area, words in reversed(self.regions):
            out += [w for w in words if not any(c.contains(w.rect.center()) for c in covered)]
            covered.append(area)
        for w in self.screen_words or []:
            if not any(c.contains(w.rect.center()) for c in covered):
                out.append(w)
        return sorted(out, key=lambda w: w.order)

    def _covered(self, area):
        return any(r.contains(area) for r, _ in self.regions)

    def _ocr_done(self, words):
        self.screen_words = words
        self.words = self._known_words()
        if self.selection is not None and self.reading:
            self.reading = False
            self._apply_selection_words(provisional=True)
        elif self._pending and self._pending[0] == "tap" and self._word_at(self._pending[2]):
            pos, self._pending = self._pending[2], None
            self._select_word_at(pos)

    def _region_done(self, token, area, words):
        self.regions.append((area, words))
        self.words = self._known_words()
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
        new = [w for w in self.words if self.selection.contains(w.rect.center())]
        old_text, new_text = join_words(self.selected_words), join_words(new)
        if new and new_text != old_text and not self.bar.edit.isModified():
            self.selected_words = new
            self._start_word_reveal()
            self.words_t0 -= 10
            self.bar.set_selection(new_text, self._prefers_text(new))
            self._start_card(new_text)
            self.update(self.selection.adjusted(-24, -24, 24, 24).toAlignedRect())
        if self.instant:
            self.bar.run_default()


    def showEvent(self, event):
        self.intro = Tween(0.8)
        self._last_front = self._sweep_front(0.0)
        self.chip.set(1.0)
        self.ticker.start()
        if self.ocr is None:
            QTimer.singleShot(30, self._start_ocr)
            if CARDS:
                threading.Thread(target=lambda: (__import__("context_card"), __import__("card_views")), daemon=True).start()
        super().showEvent(event)

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
            self.chip.set(1.0 if (self.selection is None or self.status) else 0.0)
            self.scrim_selected.set(1.0 if self.selection is not None else 0.0)

        if self.bar_tween is not None:
            self._step_bar(now)
        if self._card_anims:
            self._step_cards(now)
        for card in self.cards:
            if card.transitioning():
                grown = QRect(card.x(), card.y(), card.width(), card.layout_height())
                self.update(grown.adjusted(-48, -40, 48, 64))
        if self.ghost is not None and self.ghost[1].done(now):
            self.update(self.ghost[0].bounds.toAlignedRect())
            self.ghost = None
        if self.exit is not None and self.exit.done(now):
            self.ticker.stop()
            self.close()
            return

        springing = self.shape_tween is not None and not self.shape_tween.done(now)
        shape = None
        if springing and self.selection is not None:
            shape = self._shape(now)[0].adjusted(-24, -24, 24, 24).toAlignedRect()
        if self.exit is not None or self.scrim_selected.active(now):
            self._last_shape = shape
            self.update()
            return
        if shape is not None:
            self.update(shape.united(self._last_shape) if self._last_shape is not None else shape)
            self._last_shape = shape
        elif self._last_shape is not None:
            self.update(self._last_shape)
            self._last_shape = None
        if self._last_front is not None:
            front = self._sweep_front(self.intro.value(now))
            band = SWEEP_EDGE * 1.6
            top = min(front, self._last_front) - max(band * 0.55, SWEEP_EDGE) - 80
            bottom = max(front, self._last_front) + band * 0.45 + 80
            self.update(QRect(0, int(top), self.width(), int(bottom - top) + 1))
            self._last_front = front if not self.intro.done(now) else None
        if AMBIENT or self.aurora.active(now):
            self.update(QRect(0, self.height() - AURORA_HEIGHT, self.width(), AURORA_HEIGHT))
        if self.chip.get(now) > 0.001 or self.chip.active(now):
            if self._chip_rect.isEmpty():
                self.update(QRect(0, 0, self.width(), 80))
            else:
                self.update(self._chip_rect.adjusted(-8, -20, 8, 8).toAlignedRect())
        if self.selection is not None and (working or self._words_active(now) or
                                           (self.frame_tween is not None and not self.frame_tween.done(now))):
            self.update(self.selection.adjusted(-24, -24, 24, 24).toAlignedRect())
        if self.ghost is not None:
            self.update(self.ghost[0].bounds.toAlignedRect())

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
        old = self._bar_shadow_rect()
        self.bar.move(pos.toPoint())
        effect = self.bar.graphicsEffect()
        if effect is not None:
            effect.setOpacity(min(1.0, t.raw(now) * 3))
        self.update(old.united(self._bar_shadow_rect()))
        if t.done(now):
            self.bar_tween = None
            self.bar.setGraphicsEffect(None)

    def _step_cards(self, now):
        for card, (start, end, t) in list(self._card_anims.items()):
            if sip.isdeleted(card):
                del self._card_anims[card]
                continue
            old = self._shadow_rect(card)
            card.move(QPointF(lerp(start.x(), end.x(), t.value(now)), lerp(start.y(), end.y(), t.value(now))).toPoint())
            effect = card.graphicsEffect()
            if effect is not None:
                effect.setOpacity(min(1.0, t.raw(now) * 3))
            self.update(old.united(self._shadow_rect(card)))
            if t.done(now):
                del self._card_anims[card]
                card.setGraphicsEffect(None)

    def _snapshot(self, widget, radius):
        effect = widget.graphicsEffect()
        opacity = effect.opacity() if effect is not None else 1.0
        widget.setGraphicsEffect(None)
        pixmap = QPixmap(widget.size() * self.devicePixelRatioF())
        pixmap.setDevicePixelRatio(self.devicePixelRatioF())
        pixmap.fill(Qt.GlobalColor.transparent)
        widget.render(pixmap, flags=QWidget.RenderFlag.DrawChildren)
        self._snaps.append((pixmap, QRectF(widget.geometry()), opacity, radius))
        widget.hide()

    def dismiss(self):
        if self.exit is not None:
            return
        self.exit = Tween(0.16)
        if self.bar.isVisible():
            self._snapshot(self.bar, SearchBar.HEIGHT / 2)
        for card in self.cards:
            if card.isVisible():
                self._snapshot(card, card.radius())
        self.bar.hide()
        self.ink = None
        if self.exit.duration <= 0:
            self.close()


    def mousePressEvent(self, e):
        if self.exit is not None or self._leaving:
            return
        if e.button() == Qt.MouseButton.RightButton:
            self._clear_selection()
            return
        if e.button() == Qt.MouseButton.LeftButton:
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
            self._finish_selection()
        self.update()

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
        self._hide_cards()
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
        self.selected_words = []
        self._pending = None
        self.reading = False
        self.bar.hide()
        self._hide_cards()
        self.update()

    def _word_at(self, pos):
        return next((w for w in self.words or [] if w.rect.adjusted(-3, -3, 3, 3).contains(pos)), None)

    def _select_word_at(self, pos):
        hit = self._word_at(pos)
        if hit is None and not any(r.contains(pos) for r, _ in self.regions):
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
        self._set_selection(hit.rect.adjusted(-5, -4, 5, 4), QRectF(pos.x() - 12, pos.y() - 12, 24, 24), 12)
        self._finish_selection()

    def _finish_selection(self):
        covered = self._covered(self.selection)
        if not covered:
            self._read_region(self.selection, "select")
        self.status = ""
        if self.words is None:
            self.reading = True
            self._show_bar("", False, reading=True)
            return
        self.reading = False
        self._apply_selection_words(provisional=not covered)

    def _prefers_text(self, words):
        sel = self.selection
        word_area = sum(w.rect.width() * w.rect.height() for w in words)
        return word_area / max(1.0, sel.width() * sel.height()) >= TEXT_COVERAGE

    def _apply_selection_words(self, provisional):
        sel = self.selection
        self.selected_words = [w for w in self.words if sel.contains(w.rect.center())]
        self.frame_tween = Tween(FRAME_SETTLE)
        self._start_word_reveal()
        text = join_words(self.selected_words)
        self._show_bar(text, self._prefers_text(self.selected_words))
        self._start_card(text)
        if self.instant and not provisional:
            self.bar.run_default()


    def _board_columns(self):
        bar_w = self.bar.width()
        cols = 2 if bar_w >= 2 * 360 + CARD_GAP else 1
        return cols, (bar_w - CARD_GAP * (cols - 1)) / cols

    def _new_card(self, role="secondary"):
        from card_views import ExpressiveCard
        palette = dict(surface=SURFACE, surface_high=SURFACE_HIGH, on_surface=ON_SURFACE,
                       on_surface_variant=ON_SURFACE_VARIANT, primary=PRIMARY, on_primary=ON_PRIMARY)
        _, width = self._board_columns()
        card = ExpressiveCard(self, ui_font, palette, ambient=AMBIENT, width=round(width), role=role)
        card.hide()
        card.copyRequested.connect(self._card_copy)
        card.openRequested.connect(self._card_open)
        return card

    def _start_card(self, text):
        text = text.strip()
        if text == self._card_text:
            return
        self._hide_cards()
        self._card_text = text
        if not CARDS or not text or len(text) > 600:
            return
        if self.fetcher is None:
            from context_card import CardFetcher
            self.fetcher = CardFetcher()
            self.fetcher.routed.connect(self._card_routed)
            self.fetcher.ready.connect(self._card_ready)
            self.fetcher.extra.connect(self._card_extra)
        self._card_token = self.fetcher.start(text)

    def _card_routed(self, token, route):
        if token == self._card_token and self.exit is None and route.kind in ("term", "entity", "address"):
            card = self._new_card("hero")
            card.set_loading()
            self.cards = [card]
            self._card_col = {card: 0}
            self._layout_cards()

    def _card_ready(self, token, info):
        if token != self._card_token or self.selection is None or self.exit is not None:
            return
        if info is None:
            self._hide_cards(keep_request=True)
            return
        if not self.cards:
            self.cards = [self._new_card("hero")]
            self._card_col = {self.cards[0]: 0}
        self.cards[0].set_info(info)
        self._layout_cards()

    def _card_extra(self, token, info):
        if token != self._card_token or self.selection is None or self.exit is not None or not self.cards:
            return
        self._pending_cards.append(info)
        if len(self._pending_cards) == 1:
            QTimer.singleShot(CARD_BATCH_MS, lambda t=token: self._flush_extras(t))

    def _flush_extras(self, token):
        pending = sorted(self._pending_cards, key=lambda i: CARD_PRIORITY.get(i.kind, 9))
        self._pending_cards = []
        if token != self._card_token or not self.cards or self.exit is not None:
            return
        for k, info in enumerate(pending):
            if len(self.cards) >= MAX_CARDS:
                break
            card = self._new_card()
            card.set_info(info)
            card._stagger = k * 0.04
            self.cards.append(card)
        self._layout_cards()

    def _hide_cards(self, keep_request=False):
        for card in self.cards:
            if card.isVisible():
                self.update(self._shadow_rect(card))
            card.hide()
            card.deleteLater()
        self.cards = []
        self._card_col = {}
        self._board_cols = None
        self._pending_cards = []
        self._card_anims.clear()
        if not keep_request:
            self._card_token = None
            self._card_text = None

    def _plan_columns(self, cols):
        if self._board_cols != cols:
            self._card_col, self._board_cols = {}, cols
        col_of = self._card_col
        heights, spots = [0.0] * cols, {}
        for card in self.cards:
            if card not in col_of:
                shortest = min(range(cols), key=lambda c: heights[c])
                if card is self.cards[0]:
                    col_of[card] = 0
                elif card.info and card.info.kind in CARD_IDENTITY and heights[0] <= min(heights) + CARD_BALANCE:
                    col_of[card] = 0
                else:
                    col_of[card] = shortest
            c = col_of[card]
            spots[card] = (c, heights[c])
            heights[c] += card.layout_height() + CARD_GAP
        return spots, heights

    def _board_options(self, colw):
        bar = QRectF(self.bar_to if self.bar_to is not None else QPointF(self.bar.pos()), QSizeF(self.bar.size()))
        usable = self.width() - 32
        max_cols = max(1, int((usable + CARD_GAP) // (colw + CARD_GAP)))
        first = min(2, max_cols)
        sides = ["below", "above"] if bar.top() >= self.selection.center().y() else ["above", "below"]
        for side in sides:
            for cols in range(first, max_cols + 1):
                yield side, cols
        for side in ("right", "left"):
            for cols in range(1, max_cols + 1):
                yield side, cols

    def _board_rect(self, side, cols, colw, height):
        bar = QRectF(self.bar_to if self.bar_to is not None else QPointF(self.bar.pos()), QSizeF(self.bar.size()))
        sel = self.selection.adjusted(-4, -4, 4, 4)
        block = bar.united(sel)
        width = cols * colw + (cols - 1) * CARD_GAP
        screen = QRectF(16, 16, self.width() - 32, self.height() - 32)
        if side in ("below", "above"):
            x = min(max(screen.left(), bar.left()), screen.right() - width)
            y = max(bar.bottom(), sel.bottom()) + CARD_GAP if side == "below" else min(bar.top(), sel.top()) - CARD_GAP - height
        else:
            x = block.right() + CARD_GAP + 4 if side == "right" else block.left() - CARD_GAP - 4 - width
            y = min(max(screen.top(), block.top()), screen.bottom() - height)
        rect = QRectF(x, y, width, height)
        if not screen.contains(rect) or rect.intersects(sel) or rect.intersects(bar):
            return None
        return rect

    def _layout_cards(self):
        _, colw = self._board_columns()
        while True:
            choice = None
            for side, cols in self._board_options(colw):
                spots, heights = self._plan_columns(cols)
                height = max(heights) - CARD_GAP
                rect = self._board_rect(side, cols, colw, height)
                if rect is not None:
                    choice = (side, cols, spots, heights, rect)
                    break
            if choice or len(self.cards) <= 1:
                break
            victim = max(self.cards[1:], key=lambda c: CARD_PRIORITY.get(c.info.kind, 9) if c.info else 9)
            self.cards.remove(victim)
            self._card_col.pop(victim, None)
            self._card_anims.pop(victim, None)
            if victim.isVisible():
                self.update(self._shadow_rect(victim))
            victim.hide()
            victim.deleteLater()
        if choice is None:
            spots, heights = self._plan_columns(1)
            bar = QRectF(self.bar_to if self.bar_to is not None else QPointF(self.bar.pos()), QSizeF(self.bar.size()))
            choice = ("below", 1, spots, heights,
                      QRectF(bar.left(), min(bar.bottom() + CARD_GAP, self.height() - 16 - heights[0]), colw, heights[0]))
        side, cols, spots, heights, rect = choice
        for card in self.cards:
            c, offset = spots[card]
            x = rect.left() + c * (colw + CARD_GAP)
            y = rect.bottom() - offset - card.layout_height() if side == "above" else rect.top() + offset
            target = QPointF(x, y)
            if card.isVisible():
                if (target - QPointF(card.pos())).manhattanLength() > 1:
                    self._card_anims[card] = (QPointF(card.pos()), target, Tween(0.5, CARD_SPRING))
                self.update(self._shadow_rect(card))
                continue
            offset_in = {"below": QPointF(0, -18), "above": QPointF(0, 18), "right": QPointF(-18, 0), "left": QPointF(18, 0)}[side]
            start = target + offset_in
            tween = Tween(0.5, CARD_SPRING)
            tween.start += getattr(card, "_stagger", 0.0) * MOTION
            self._card_anims[card] = (start, target, tween)
            effect = QGraphicsOpacityEffect(card)
            effect.setOpacity(0.0)
            card.setGraphicsEffect(effect)
            card.move(start.toPoint())
            card.show()
            card.raise_()

    def _card_copy(self, text):
        if self._leaving or self.exit is not None:
            return
        copy_text(text)
        self._leaving = True
        self.status = "Copied"
        self.update()
        QTimer.singleShot(round(1000 * min(0.35, max(0.25, 0.3 * MOTION))), self.dismiss)

    def _card_open(self, url):
        if self._leaving or self.exit is not None:
            return
        open_url(url)
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
            r = w.rect.adjusted(-2, -2, 2, 2)
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
        target = QPointF(x, y)
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
            search_text(text)
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
        search_image(self._crop_png())
        self.dismiss()


    def paintEvent(self, e):
        now = time.monotonic()
        t = (now - self.t0) if AMBIENT else 0.0
        fade = 1.0 - (self.exit.value(now) if self.exit is not None else 0.0)
        intro = self.intro.value(now)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(0, 0, self.shot)

        self._paint_scrim(p, now, intro, fade)
        self._paint_aurora(p, now, t, intro, fade)
        if self.selection is not None:
            self._paint_selection(p, now, t, fade)
        if self.ghost is not None:
            ink, tween = self.ghost
            ink.paint(p, e.rect(), (1 - tween.value(now)) * fade, tip=False, fading=True)
        if self.ink is not None:
            self.ink.paint(p, e.rect())
        for widget, radius in ((self.bar, SearchBar.HEIGHT / 2), *((c, c.radius()) for c in self.cards)):
            if widget is not None and widget.isVisible():
                effect = widget.graphicsEffect()
                self._paint_bar_shadow(p, QRectF(widget.geometry()),
                                       effect.opacity() if effect is not None else 1.0, radius)
        for pixmap, geometry, opacity, radius in self._snaps:
            self._paint_bar_shadow(p, geometry, opacity * fade, radius)
            p.setOpacity(opacity * fade)
            p.drawPixmap(geometry.topLeft(), pixmap)
            p.setOpacity(1.0)
        self._paint_chip(p, now, fade)

    def _sweep_front(self, intro):
        return lerp(self.height() + 60, -SWEEP_EDGE - 60, intro)

    def _paint_scrim(self, p, now, intro, fade):
        h = self.height()
        front = self._sweep_front(intro)
        extra = SCRIM_SELECTED * self.scrim_selected.get(now)
        g = QLinearGradient(0, 0, 0, h)
        steps = 24
        for i in range(steps + 1):
            y = h * i / steps
            reveal = min(1.0, max(0.0, (y - front) / SWEEP_EDGE + 1.0))
            reveal = reveal * reveal * (3 - 2 * reveal)
            alpha = (lerp(self.scrim_top, self.scrim_bottom, i / steps) + extra) * reveal * fade
            g.setColorAt(i / steps, with_alpha(SCRIM, alpha))
        area = QPainterPath()
        area.addRect(QRectF(self.rect()))
        if self.selection is not None:
            rect, radius = self._shape(now)
            hole = QPainterPath()
            hole.addRoundedRect(rect, radius, radius)
            area = area.subtracted(hole)
        p.fillPath(area, QBrush(g))

    def _paint_aurora(self, p, now, t, intro, fade):
        w, h = self.width(), self.height()
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
        strength = self.aurora.get(now) * fade * min(1.0, intro * 1.6)
        if strength > 0.01:
            img = aurora_image(w, AURORA_HEIGHT, t, strength, anchor=1.15)
            p.drawImage(QRectF(0, h - AURORA_HEIGHT, w, AURORA_HEIGHT), img)
        if intro < 1.0:
            band = SWEEP_EDGE * 1.6
            wave = (1.0 - intro) ** 0.7 * fade
            img = aurora_image(w, band, t + 3.0, wave, anchor=0.5, seed=2.0, feather=True)
            p.drawImage(QRectF(0, self._sweep_front(intro) - band * 0.55, w, band), img)
        p.restore()

    def _paint_selection(self, p, now, t, fade):
        rect, radius = self._shape(now)
        shape = QPainterPath()
        shape.addRoundedRect(rect, radius, radius)
        if self.selected_words:
            self._paint_words(p, now, rect, radius, fade)

        if self.reading or self.frame_tween is None:
            if AMBIENT:
                p.save()
                p.setClipPath(shape, Qt.ClipOperation.IntersectClip)
                h = rect.height()
                reach = 80 + h * h / 160
                cycle = (t % SHIMMER_PERIOD) / SHIMMER_SWEEP
                x = lerp(rect.left() - reach, rect.right() + reach,
                         SWEEP_EASE.valueForProgress(min(1.0, cycle)))
                g = QLinearGradient(x - 80, rect.top(), x + 80, rect.bottom())
                if self.selection_light:
                    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
                    peak = with_alpha(HIGHLIGHT_LIGHT, 0.9 * fade)
                else:
                    peak = with_alpha(QColor("white"), 0.16 * fade)
                g.setColorAt(0.0, with_alpha(peak, 0.0))
                g.setColorAt(0.5, peak)
                g.setColorAt(1.0, with_alpha(peak, 0.0))
                p.fillRect(rect, QBrush(g))
                p.restore()
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QBrush(google_gradient(rect.center(), (now - self.t0) * 160, fade)), 3.5))
            p.drawPath(shape)
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
        corners = QPainterPath()
        corners.setFillRule(Qt.FillRule.WindingFill)
        for x, y in ((r.left() - 8, r.top() - 8), (r.right() - s, r.top() - 8),
                     (r.left() - 8, r.bottom() - s), (r.right() - s, r.bottom() - s)):
            corners.addRect(QRectF(x, y, s + 8, s + 8))
        p.save()
        p.setClipPath(corners, Qt.ClipOperation.IntersectClip)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if white < 1.0:
            p.setPen(QPen(QBrush(google_gradient(rect.center(), (now - self.t0) * 160, (1 - white) * fade)),
                          lerp(3.5, pen, k)))
            p.drawRoundedRect(r, rad, rad)
        a = white * fade
        if a > 0.01:
            p.setPen(QPen(with_alpha(QColor("black"), 0.30 * a), pen + 4))
            p.drawRoundedRect(r, rad, rad)
            p.setPen(QPen(with_alpha(QColor("white"), a), pen))
            p.drawRoundedRect(r, rad, rad)
        p.restore()

    def _paint_words(self, p, now, rect, radius, fade):
        grown = QPainterPath()
        grown.addRoundedRect(rect.adjusted(-10, -10, 10, 10), radius + 10, radius + 10)
        p.save()
        p.setClipPath(grown, Qt.ClipOperation.IntersectClip)
        p.setPen(Qt.PenStyle.NoPen)
        for i, w in enumerate(self.selected_words):
            u = self._word_progress(i, now)
            if u <= 0.0:
                continue
            a = min(1.0, u * 2.5) * fade
            r = w.rect.adjusted(-3, -2, 3, 2)
            r.setWidth(r.width() * WORD_SPRING.valueForProgress(u))
            if self._word_is_light(w):
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
                p.setBrush(mix(QColor("white"), HIGHLIGHT_LIGHT, a))
            else:
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
                p.setBrush(mix(QColor("black"), HIGHLIGHT_DARK, a))
            p.drawRoundedRect(r, 6, 6)
        p.restore()

    def _bar_shadow_rect(self):
        return self._shadow_rect(self.bar)

    def _shadow_rect(self, widget):
        return QRectF(widget.geometry()).adjusted(-48, -40, 48, 64).toAlignedRect()

    def _paint_bar_shadow(self, p, geometry, opacity, radius=None):
        size = geometry.size().toSize()
        radius = size.height() / 2 if radius is None else radius
        key = (size.width(), size.height(), radius)
        if key not in self._shadows:
            pad, s = 48, 12
            img = QImage((size.width() + 2 * pad) // s, (size.height() + 2 * pad) // s,
                         QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(0)
            sp = QPainter(img)
            sp.setRenderHint(QPainter.RenderHint.Antialiasing)
            sp.scale(1 / s, 1 / s)
            sp.setPen(Qt.PenStyle.NoPen)
            sp.setBrush(QColor(0, 0, 0, 170))
            sp.drawRoundedRect(QRectF(pad + 8, pad + 14, size.width() - 16, size.height()), radius, radius)
            sp.end()
            if len(self._shadows) > 8:
                self._shadows.clear()
            self._shadows[key] = img
        p.setOpacity(opacity)
        p.drawImage(geometry.adjusted(-48, -48, 48, 48), self._shadows[key])
        p.setOpacity(1.0)

    def _paint_chip(self, p, now, fade):
        a = max(0.0, self.chip.get(now)) * fade
        if a <= 0.01:
            return
        working = self.reading or bool(self._pending and self._pending[0] == "tap")
        text = self.status or "Circle or tap anything to search"
        font = ui_font(15, 480)
        fm = QFontMetrics(font)
        key_font = ui_font(12, 600)
        kfm = QFontMetrics(key_font)
        show_key = not self.status
        kw = kfm.horizontalAdvance("Esc") + 16 if show_key else 0
        tw = fm.horizontalAdvance(text)
        h = 46
        w = 18 + 20 + 12 + tw + (14 + kw if show_key else 0) + 16
        y = lerp(4, 26, min(1.0, a))
        box = QRectF((self.width() - w) / 2, y, w, h)
        self._chip_rect = QRectF((self.width() - w) / 2, 4, w, 26 + h)

        p.save()
        p.setOpacity(min(1.0, a))
        p.setPen(QPen(QColor(255, 255, 255, 16), 1))
        p.setBrush(with_alpha(SURFACE, 0.94))
        p.drawRoundedRect(box, h / 2, h / 2)
        icon = QPointF(box.left() + 28, box.center().y())
        if working:
            draw_spinner(p, icon, now - self.t0, PRIMARY, radius=8, width=2.6)
        else:
            draw_glyph(p, icon)
        p.setFont(font)
        p.setPen(ON_SURFACE)
        p.drawText(QRectF(box.left() + 50, box.top(), tw + 2, h), Qt.AlignmentFlag.AlignVCenter, text)
        if show_key:
            key = QRectF(box.right() - 16 - kw, box.center().y() - 12, kw, 24)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(SURFACE_HIGH)
            p.drawRoundedRect(key, 8, 8)
            p.setFont(key_font)
            p.setPen(ON_SURFACE_VARIANT)
            p.drawText(key, Qt.AlignmentFlag.AlignCenter, "Esc")
        p.restore()


def main():
    parser = argparse.ArgumentParser(description=HELP,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--instant", action="store_true",
                        help="search immediately when you finish circling")
    args = parser.parse_args()

    lock = QLockFile(os.path.join(tempfile.gettempdir(), f"circle-search-{os.getuid()}.lock"))
    if not lock.tryLock(0):
        return 0

    grab = start_kwin_grab()
    app = QApplication(sys.argv)
    app.setApplicationName("circle-search")
    app.setDesktopFileName("circle-search")
    for font_file in (FONT_FILE, FALLBACK_FONT_FILE):
        if os.path.exists(font_file):
            QFontDatabase.addApplicationFont(font_file)
    image = finish_kwin_grab(grab) or grab_with_tool()
    if image is None:
        print("Could not take a screenshot (need kwin-grab, spectacle, grim or gnome-screenshot).",
              file=sys.stderr)
        return 1

    overlay = Overlay(image, app.primaryScreen(), instant=args.instant)
    overlay.showFullScreen()
    overlay.activateWindow()
    code = app.exec()
    lock.unlock()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
