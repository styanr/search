import os
import shutil
import subprocess
from dataclasses import dataclass

from circlesearch.core import settings
from circlesearch.core.geometry import Point, Rect
from circlesearch.core.locale import current
from circlesearch.core.registry import Registry


@dataclass
class Box:
    text: str
    x: float
    y: float
    w: float
    h: float
    line: tuple


@dataclass
class Word:
    text: str
    rect: Rect
    line: tuple
    order: int


engines = Registry("ocr engine")


def engine(cls):
    engines.add(cls.name, cls(), getattr(cls, "order", 100))
    return cls


def active():
    return next((e for e in engines if e.available()), None)


def available():
    return active() is not None


def read(path, scale, offset=Point(0, 0), pass_id=0, background=False, debug_dir=None):
    e = active()
    if e is None:
        return []
    debug = os.path.join(debug_dir, f"ocr-{pass_id:02d}") if debug_dir else None
    boxes = e.recognize(path, background, debug)
    return [Word(b.text, Rect(offset.x + b.x / scale, offset.y + b.y / scale, b.w / scale, b.h / scale),
                 (pass_id, *b.line), pass_id * 1_000_000 + i) for i, b in enumerate(boxes)]


def join_words(words):
    lines, current_line, last_key = [], [], None
    for w in sorted(words, key=lambda w: w.order):
        if last_key is not None and w.line != last_key:
            lines.append(" ".join(current_line))
            current_line = []
        current_line.append(w.text)
        last_key = w.line
    if current_line:
        lines.append(" ".join(current_line))
    return "\n".join(lines)


def parse_tsv(tsv, min_confidence=30):
    boxes = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":
            continue
        text = cols[11].strip()
        if not text or float(cols[10]) < min_confidence:
            continue
        x, y, w, h = (int(c) for c in cols[6:10])
        boxes.append(Box(text, x, y, w, h, (int(cols[2]), int(cols[3]), int(cols[4]))))
    return boxes


@engine
class Tesseract:
    name = "tesseract"
    order = 10

    def __init__(self):
        self._langs = None
        self._installed = None

    def available(self):
        return shutil.which("tesseract") is not None

    def installed(self):
        if self._installed is None:
            try:
                out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=5).stdout
                self._installed = [lang for lang in (line.strip() for line in out.splitlines()[1:])
                                   if lang and lang not in ("osd", "equ") and "/" not in lang]
            except (OSError, subprocess.SubprocessError):
                self._installed = []
        return self._installed

    def default_languages(self):
        loc = current()
        return [lang for lang in dict.fromkeys(["eng", loc.ocr_language(loc.language)]) if lang in self.installed()]

    def languages(self):
        if self._langs is None:
            have = set(self.installed())
            wanted = dict.fromkeys(settings.OCR_LANGUAGES or self.default_languages())
            self._langs = "+".join(lang for lang in wanted if lang in have) or "eng"
        return self._langs

    def recognize(self, path, background=False, debug=None):
        cmd = ["tesseract", path, "-", "-l", self.languages(), "--psm", "3", "tsv"]
        if background and shutil.which("nice"):
            cmd = ["nice", "-n", "10"] + cmd
        try:
            tsv = subprocess.run(cmd, capture_output=True).stdout.decode(errors="replace")
        except OSError:
            tsv = ""
        if debug:
            with open(debug + ".tsv", "w") as f:
                f.write(tsv)
        return parse_tsv(tsv)
