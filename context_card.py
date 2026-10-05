import html
import os
import unicodedata
import re
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from locale_profile import PROFILE
from providers import enrich
from card_data import (BUILDERS, EDGE_JUNK, money_str, OPTIONAL_TIMEOUT, STRUCTURED, TIMEOUT, CardInfo, fetch_image,
                       find_structured, get_json, image_shape_for, place_card, recognise, safe, tidy, zoom_for)

from PyQt6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

TARGET_LANG = PROFILE.language
FALLBACK_LANG = PROFILE.ui_language
MAX_TRANSLATE_CHARS = 600

KINDS = ["term", "entity", "foreign_text", "code_or_error", "plain_text", "not_text"] + [k for k, _, _ in STRUCTURED]
language_name = PROFILE.language_name


@dataclass
class Route:
    kind: str
    confidence: float = 1.0
    known_word: bool | None = None
    text: str = ""


CODE_SYMBOLS = re.compile(r"[{}\[\];=<>|\\`$]|::|->|=>|\w\(|\w+\.\w+\(|^\s*[$#>] ")
ERROR_WORDS = re.compile(r"\b(error|exception|traceback|errno|failed|fatal|warning|segfault)\b", re.I)
IDENTIFIER = re.compile(r"^[a-z]+(_[a-z0-9]+)+$|^[a-z]+([A-Z][a-z0-9]+)+$|^[\w.-]+/[\w./-]+$")
WORD = re.compile(r"^[^\W\d_]+(?:[-'’][^\W\d_]+)*$")
def non_latin(text):
    return any(ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN") for ch in text)


def clean(text):
    return tidy(text)


class EnglishWords:
    PATHS = ["/usr/share/hunspell/en_US.dic", "/usr/share/myspell/en_US.dic"]
    SUFFIXES = [("ies", "y"), ("ied", "y"), ("ier", "y"), ("iest", "y"), ("ily", "y"), ("es", ""),
                ("s", ""), ("ed", ""), ("ed", "e"), ("ing", ""), ("ing", "e"), ("ly", ""), ("er", ""),
                ("est", ""), ("'s", ""), ("’s", "")]

    def __init__(self):
        self.words = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self.words is None:
                path = next((p for p in self.PATHS if os.path.exists(p)), None)
                words = set()
                if path:
                    with open(path, encoding="utf-8", errors="ignore") as f:
                        next(f, None)
                        words = {line.split("/", 1)[0].strip().lower() for line in f}
                self.words = words
        return self.words

    @property
    def available(self):
        return bool(self._load())

    def __contains__(self, word):
        words, w = self._load(), word.lower()
        if w in words:
            return True
        for suffix, repl in self.SUFFIXES:
            if w.endswith(suffix) and len(w) - len(suffix) >= 2:
                stem = w[: len(w) - len(suffix)] + repl
                if stem in words or (repl == "" and len(stem) > 2 and stem[-1] == stem[-2] and stem[:-1] in words):
                    return True
        return False


ENGLISH = EnglishWords()


class LocalRouter:
    name = "local"

    def route(self, text):
        t = clean(text)
        structured = recognise(t)
        if structured:
            return Route(structured, text=t)
        found = find_structured(t)
        if found:
            return Route(found[0], text=found[1])
        letters = sum(c.isalpha() for c in t)
        if letters < 2 or letters < len(t) * 0.4:
            return Route("not_text")
        words = [w.strip(EDGE_JUNK) or w for w in t.split()]
        if CODE_SYMBOLS.search(t) or (len(words) == 1 and IDENTIFIER.match(t)) or \
                (ERROR_WORDS.search(t) and len(words) <= 30 and re.search(r"[:/_]", t)):
            return Route("code_or_error")
        if non_latin(t):
            return Route("term" if len(words) <= 4 else "foreign_text", known_word=False)

        have_dict = ENGLISH.available
        plain_words = [w for w in words if WORD.match(w)]
        known = [w in ENGLISH for w in plain_words] if have_dict else []
        if len(plain_words) == len(words) and len(words) <= 3 and len(t) <= 40:
            capitalised = all(w[0].isupper() for w in words)
            all_known = all(known) if have_dict else None
            if capitalised and (len(words) >= 2 or all_known is False):
                return Route("entity", known_word=all_known)
            return Route("term", known_word=all_known)
        if len(plain_words) == len(words) and len(words) <= 6 and all(w[0].isupper() for w in words):
            return Route("entity", known_word=False)
        if have_dict and plain_words:
            english_share = sum(known) / len(known)
            return Route("plain_text" if english_share >= 0.6 else "foreign_text", confidence=abs(english_share - 0.6) + 0.4)
        return Route("foreign_text" if not t.isascii() else "plain_text", confidence=0.5)


ROUTERS = {LocalRouter.name: LocalRouter}


def default_router():
    name = os.environ.get("CIRCLE_SEARCH_ROUTER", LocalRouter.name)
    if name not in ROUTERS:
        print(f"context: unknown router {name!r}, using {LocalRouter.name!r}", file=sys.stderr)
        name = LocalRouter.name
    return ROUTERS[name]()


def google_translate(text, source="auto", target=TARGET_LANG):
    q = urllib.parse.urlencode({"client": "gtx", "sl": source, "tl": target, "q": text})
    data = get_json(f"https://translate.googleapis.com/translate_a/single?{q}&dt=t&dt=bd&dt=rm")
    if not data:
        return None
    segments = data[0] or []
    translation = "".join(s[0] for s in segments if s and isinstance(s[0], str))
    pronunciation = next((s[3] for s in segments if s and s[0] is None and len(s) > 3 and s[3]), "")
    alternatives = {e[0]: e[1] for e in (data[1] or []) if e and len(e) > 1}
    confidence = data[6] if len(data) > 6 and isinstance(data[6], (int, float)) else 1.0
    return {"translation": translation, "detected": data[2], "confidence": confidence,
            "pronunciation": pronunciation, "alternatives": alternatives}


def wiktionary(word, timeout=TIMEOUT):
    for candidate in dict.fromkeys([word, word.lower()]):
        data = get_json("https://en.wiktionary.org/api/rest_v1/page/definition/"
                        + urllib.parse.quote(candidate.replace(" ", "_")), timeout=timeout)
        if not data:
            continue
        senses = {}
        for lang, entries in data.items():
            for entry in entries:
                if lang == "en" and entry.get("language") == "Translingual":
                    continue
                for d in entry.get("definitions", []):
                    text = html.unescape(re.sub(r"<[^>]+>", "", d.get("definition", ""))).strip()
                    text = text.split("\n", 1)[0].strip()
                    if text:
                        senses.setdefault(lang, []).append((entry.get("partOfSpeech", "").lower(), text))
                        break
        if senses:
            return senses
    return None


def wikipedia(title, lang="en", resolve=True):
    data = get_json(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                    + urllib.parse.quote(title.replace(" ", "_")) + "?redirect=true")
    if data and data.get("type") == "disambiguation" and resolve:
        best = disambiguate(title, lang)
        return wikipedia(best, lang, resolve=False) if best else None
    if not data or data.get("type") != "standard":
        return None
    coords = data.get("coordinates") or {}
    return {"title": data.get("title", title), "description": data.get("description", ""),
            "qid": data.get("wikibase_item"), "thumb": (data.get("thumbnail") or {}).get("source"),
            "extract": data.get("extract", ""), "lat": coords.get("lat"), "lon": coords.get("lon"),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page", "")}


def disambiguate(title, lang="en"):
    q = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": title, "srlimit": 5, "format": "json"})
    hits = (get_json(f"https://{lang}.wikipedia.org/w/api.php?{q}") or {}).get("query", {}).get("search", [])
    key = title.lower()
    for hit in hits:
        name = hit["title"]
        if name.lower().startswith(key) and name.lower() != key and "disambiguation" not in name.lower():
            return name
    return None


def wikipedia_title_in(title, lang=TARGET_LANG, source="en"):
    q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "langlinks",
                                "lllang": lang, "redirects": 1, "format": "json"})
    data = get_json(f"https://{source}.wikipedia.org/w/api.php?{q}")
    for page in ((data or {}).get("query", {}).get("pages", {}) or {}).values():
        for link in page.get("langlinks", []):
            return link.get("*")
    return None


SMALL_WORDS = {"of", "the", "and", "de", "la", "le", "in", "on", "at", "for", "du", "von", "van", "der"}


def smart_case(text):
    words = text.lower().split()
    return " ".join(w if i and w in SMALL_WORDS else "-".join(p[:1].upper() + p[1:] for p in w.split("-"))
                    for i, w in enumerate(words))


def first_sentences(text, n=2, limit=260):
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:n])
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + "…"


SKIP_POS = {"symbol", "letter", "abbreviation", "initialism", "acronym", "prefix", "suffix",
            "proper noun", "contraction", "particle", "phrase"}


def pick_sense(senses, lang, preferred_pos):
    options = senses.get(lang, [])
    real = [s for s in options if s[0] not in SKIP_POS] or options
    return next((s for s in real if s[0] in preferred_pos), real[0]) if real else None


def lookup(text, route):
    t, kind = clean(route.text or text), route.kind
    if kind in BUILDERS:
        return safe(BUILDERS[kind], t)
    if kind in ("code_or_error", "not_text", "plain_text") or not t:
        return None
    target = TARGET_LANG

    if kind == "foreign_text":
        if len(t) > MAX_TRANSLATE_CHARS:
            return None
        tr = safe(google_translate, t, "auto", target)
        if not tr or not tr["translation"] or tr["detected"] in (target, FALLBACK_LANG):
            return None
        return translation_card(t, tr, target)

    script = non_latin(t)
    detected = None
    if script:
        first = safe(google_translate, t, "auto", FALLBACK_LANG)
        detected = (first or {}).get("detected")
        if detected and detected != FALLBACK_LANG and len(t.split()) <= 4:
            card = native_name_card(t, detected)
            if card is not None:
                return card
    if detected == TARGET_LANG:
        target = FALLBACK_LANG

    english = route.known_word is True and not script
    want_wiki = not english or kind == "entity" or t[:1].isupper()
    caps = t.isupper() and sum(ch.isalpha() for ch in t) >= 2
    name = smart_case(t) if caps else t
    with ThreadPoolExecutor(4) as pool:
        dict_f = pool.submit(safe, wiktionary, t.lower() if caps else t, OPTIONAL_TIMEOUT if kind == "entity" else TIMEOUT)
        tr_f = pool.submit(safe, google_translate, t, "en" if english else "auto", target)
        wiki_f = pool.submit(safe, wikipedia, name) if want_wiki else None
        native_f = pool.submit(safe, wikipedia_title_in, name, TARGET_LANG) \
            if want_wiki and not script and TARGET_LANG != "en" else None
        senses, tr = dict_f.result(), tr_f.result()
        wiki = wiki_f.result() if wiki_f else None
        native_title = native_f.result() if native_f else None
    if caps and wiki:
        return entity_card(wiki, native_title, tr, "en", target)

    if english:
        lang = "en"
    elif senses:
        detected = (tr or {}).get("detected")
        lang = "en" if "en" in senses and detected in ("en", None) else detected if detected in senses \
            else next(iter(senses))
    else:
        lang = (tr or {}).get("detected") or detected or "en"

    sense = pick_sense(senses or {}, lang, set((tr or {}).get("alternatives", {})))
    foreign_word = sense is not None and lang not in ("en", target) and len(t.split()) == 1
    proper_noun = sense is not None and (sense[0] == "proper noun" or (
        t[:1].isupper() and any(pos == "proper noun" for pos, _ in (senses or {}).get(lang, []))))
    if (kind == "entity" or proper_noun) and wiki and not foreign_word:
        return entity_card(wiki, native_title, tr, lang, target)
    if sense:
        if lang == "en" and not english:
            tr = safe(google_translate, t, "en", target) or tr
        pos, definition = sense
        translation = (tr or {}).get("translation", "") if lang != target else ""
        alts = [a for a in (tr or {}).get("alternatives", {}).get(pos, []) if a.lower() != translation.lower()][:4]
        return CardInfo("term", t, pronunciation=(tr or {}).get("pronunciation", "") if lang == "en" else "",
                        part_of_speech=pos, definition=definition,
                        description="" if lang == "en" else language_name(lang),
                        translation=translation, translation_label=language_name(target),
                        alternatives=alts, source="Wiktionary",
                        url="https://en.wiktionary.org/wiki/" + urllib.parse.quote(t.replace(" ", "_")))
    if wiki is None and english:
        wiki = safe(wikipedia, t)
    if wiki:
        return entity_card(wiki, native_title, tr, lang, target)
    if tr and tr["translation"] and tr["translation"].lower() != t.lower() and lang != target:
        return translation_card(t, tr, target)
    return None


def native_name_card(t, lang):
    name = smart_case(t) if t.isupper() else t
    with ThreadPoolExecutor(2) as pool:
        native_f = pool.submit(safe, wikipedia, name, lang)
        en_title_f = pool.submit(safe, wikipedia_title_in, name, FALLBACK_LANG, lang)
        native, en_title = native_f.result(), en_title_f.result()
    if not native:
        return None
    en = safe(wikipedia, en_title) if en_title else None
    if en is None:
        return entity_card(native, None, None, lang, lang)
    if lang == TARGET_LANG or TARGET_LANG == FALLBACK_LANG:
        return entity_card(en, native["title"], None, "en", lang)
    shown = safe(wikipedia_title_in, en["title"], TARGET_LANG)
    return entity_card(en, shown or native["title"], None, "en", TARGET_LANG if shown else lang)


def entity_card(wiki, native_title, tr, lang, target):
    name = native_title or ((tr or {}).get("translation", "") if lang != target else "")
    if name and name.lower() == wiki["title"].lower():
        name = ""
    if wiki.get("lat") is not None:
        card = place_card(wiki["title"], wiki["lat"], wiki["lon"], zoom_for(wiki["description"]),
                          description=wiki["description"], definition=first_sentences(wiki["extract"], 1),
                          source="Wikipedia", url=wiki["url"], query=wiki["title"],
                          facts={"qid": wiki["qid"]} if wiki.get("qid") else None, image_url=wiki.get("thumb"))
        card.translation, card.translation_label = name, language_name(target)
        return card
    picture = safe(fetch_image, wiki["thumb"]) if wiki.get("thumb") else None
    return CardInfo("entity", wiki["title"], description=wiki["description"],
                    image=picture, image_shape=image_shape_for(wiki["description"]),
                    definition=first_sentences(wiki["extract"]), translation=name,
                    translation_label=language_name(target), source="Wikipedia", url=wiki["url"],
                    facts={"qid": wiki["qid"], "title": wiki["title"]} if wiki.get("qid") else {})


def translation_card(text, tr, target):
    lang = language_name(tr["detected"])
    return CardInfo("translation", text, description=f"Translated from {lang}", translation=tr["translation"],
                    translation_label=language_name(target), source="Google Translate",
                    url="https://translate.google.com/?" + urllib.parse.urlencode(
                        {"sl": tr["detected"], "tl": target, "text": text, "op": "translate"}))


class CardFetcher(QObject):
    routed = pyqtSignal(int, object)
    ready = pyqtSignal(int, object)
    extra = pyqtSignal(int, object)

    def __init__(self, parent=None, router=None):
        super().__init__(parent)
        self.router = router or default_router()
        self.token = 0

    def start(self, text):
        self.token += 1
        token = self.token

        def work():
            try:
                route = self.router.route(text)
            except Exception as e:
                print(f"context: router {self.router.name!r} failed: {e}", file=sys.stderr)
                route = Route("not_text")
            self.routed.emit(token, route)
            card = lookup(text, route)
            if card is None:
                print(f"context: no card for {text!r} (routed as {route.kind}, text {route.text!r})", file=sys.stderr)
            self.ready.emit(token, card)
            if card is not None and card.facts and token == self.token:
                enrich(card.facts, lambda extra: self.extra.emit(token, extra))

        threading.Thread(target=work, daemon=True).start()
        return token


def wrap(fm, text, width, max_lines):
    if max_lines <= 1:
        return [fm.elidedText(" ".join(text.split()), Qt.TextElideMode.ElideRight, int(width))]
    words, lines, line = text.split(), [], ""
    for i, w in enumerate(words):
        trial = f"{line} {w}".strip()
        if fm.horizontalAdvance(trial) <= width or not line:
            line = trial
            continue
        lines.append(line)
        line = w
        if len(lines) == max_lines - 1:
            line = " ".join(words[i:])
            break
    if line:
        lines.append(line)
    if lines:
        lines[-1] = fm.elidedText(lines[-1], Qt.TextElideMode.ElideRight, int(width))
    return lines


class InfoCard(QWidget):
    copyRequested = pyqtSignal(str)
    openRequested = pyqtSignal(str)

    WIDTH = 460
    PAD = 22

    def __init__(self, parent, font, palette, ambient=True):
        super().__init__(parent)
        self.font_fn, self.c, self.ambient = font, palette, ambient
        self.info = None
        self.loading = False
        self._hover = None
        self._mouse = QPointF()
        self._targets = {}
        self._t0 = time.monotonic()
        self._timer = QTimer(self, interval=16, timeout=self.update)
        self.setMouseTracking(True)
        self.resize(self.WIDTH, 120)


    def set_loading(self):
        self.info, self.loading = None, True
        self.resize(self.WIDTH, 132)
        self._t0 = time.monotonic()
        if self.ambient:
            self._timer.start()
        self.update()

    def set_info(self, info):
        self.info, self.loading = info, False
        self._timer.stop()
        self.resize(self.WIDTH, self._layout(paint=None))
        self.update()

    def sizeHint(self):
        return QSize(self.WIDTH, self.height())


    def _target_at(self, pos):
        return next((name for name, (r, _) in self._targets.items() if r.contains(pos)), None)

    def mouseMoveEvent(self, e):
        self._mouse = e.position()
        hover = self._target_at(e.position())
        if hover and hover.startswith("series"):
            self._hover = hover
            self.update()
            return
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.CursorShape.PointingHandCursor if hover else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        name = self._target_at(e.position())
        if name and self._targets[name][1] is not None:
            self._targets[name][1]()
        e.accept()


    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(self.c["surface"])
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawRoundedRect(r, 26, 26)
        if self.loading:
            self._paint_skeleton(p)
        elif self.info:
            self._layout(paint=p)

    def _paint_skeleton(self, p):
        x, w = self.PAD, self.width() - 2 * self.PAD
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.c["surface_high"])
        bars = [QRectF(x, 24, w * 0.42, 22), QRectF(x, 60, w, 13), QRectF(x, 81, w * 0.78, 13)]
        for b in bars:
            p.drawRoundedRect(b, b.height() / 2, b.height() / 2)
        if self.ambient:
            t = (time.monotonic() - self._t0) % 1.4 / 1.4
            cx = -120 + t * (self.width() + 240)
            g = QLinearGradient(cx - 90, 0, cx + 90, 0)
            g.setColorAt(0, QColor(255, 255, 255, 0))
            g.setColorAt(0.5, QColor(255, 255, 255, 22))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(g)
            for b in bars:
                p.drawRoundedRect(b, b.height() / 2, b.height() / 2)

    def _layout(self, paint):
        info, c, pad = self.info, self.c, self.PAD
        width = self.WIDTH - 2 * pad
        y = pad - 2
        targets = {}

        def text(s, px, weight, color, x, y, w=None, max_lines=1):
            f = self.font_fn(px, weight)
            fm = QFontMetrics(f)
            lines = wrap(fm, s, w or width, max_lines)
            if paint:
                paint.setFont(f)
                paint.setPen(color)
                for i, line in enumerate(lines):
                    paint.drawText(QPointF(x, y + fm.ascent() + i * fm.lineSpacing()), line)
            return len(lines) * fm.lineSpacing(), (fm.horizontalAdvance(lines[0]) if lines else 0)

        def copy_button(name, rect, payload):
            targets[name] = (rect, lambda: self.copyRequested.emit(payload))
            if paint:
                self._paint_copy_icon(paint, rect, self._hover == name)

        if info.kind == "translation":
            title_h, title_w = text(info.title, 15, 450, c["on_surface_variant"], pad, y, max_lines=3)
        elif info.kind in ("money", "quantity", "time", "date", "math"):
            title_h, title_w = text(info.title, 17, 520, c["on_surface_variant"], pad, y, max_lines=2)
        else:
            title_h, title_w = text(info.title, 24, 620, c["on_surface"], pad, y, max_lines=2)
        if info.pronunciation:
            fp = QFontMetrics(self.font_fn(15, 430))
            pw = fp.horizontalAdvance(info.pronunciation)
            if title_h < 40 and title_w + 12 + pw <= width:
                f24 = QFontMetrics(self.font_fn(24, 620))
                text(info.pronunciation, 15, 430, c["on_surface_variant"], pad + title_w + 12,
                     y + f24.ascent() - fp.ascent())
            else:
                title_h += text(info.pronunciation, 15, 430, c["on_surface_variant"], pad, y + title_h)[0]
        y += title_h + 6

        chips = [s for s in (info.part_of_speech, info.description, *info.chips) if s]
        if chips:
            chip_font = self.font_fn(12, 600)
            fm = QFontMetrics(chip_font)
            x = pad
            for label in chips:
                cw = min(fm.horizontalAdvance(label) + 24, width)
                if x + cw > pad + width and x > pad:
                    x, y = pad, y + 24 + 6
                if paint:
                    paint.setPen(Qt.PenStyle.NoPen)
                    paint.setBrush(c["surface_high"])
                    paint.drawRoundedRect(QRectF(x, y, cw, 24), 8, 8)
                    paint.setFont(chip_font)
                    paint.setPen(c["on_surface_variant"])
                    paint.drawText(QRectF(x, y, cw, 24), Qt.AlignmentFlag.AlignCenter,
                                   fm.elidedText(label, Qt.TextElideMode.ElideRight, int(cw - 20)))
                x += cw + 8
            y += 24 + 12

        if info.swatch:
            sw = QRectF(pad, y, width, 72)
            if paint:
                paint.setPen(QPen(QColor(255, 255, 255, 30), 1))
                paint.setBrush(QColor(info.swatch))
                paint.drawRoundedRect(sw, 18, 18)
            y += sw.height() + 12

        if info.definition and info.kind != "translation":
            y += text(info.definition, 15, 420, c["on_surface"], pad, y,
                      max_lines=4 if info.kind == "entity" else 3)[0] + 14

        if info.value:
            vf = QFontMetrics(self.font_fn(34, 600))
            h = vf.lineSpacing()
            text(info.value, 34, 600, c["on_surface"], pad, y, w=width - 48)
            copy_button("value", QRectF(pad + width - 36, y + (h - 36) / 2, 36, 36), info.value)
            y += h + 10

        if info.chart and info.chart.get("type") == "forecast":
            y = self._forecast(paint, info.chart["days"], QRectF(pad, y, width, 0), targets) + 10
        if info.chart and info.chart.get("type") == "lines":
            y = self._lines(paint, info.chart["series"], QRectF(pad, y, width, 0), targets) + 6

        for i, (label, value) in enumerate(info.rows):
            lf, vf_ = QFontMetrics(self.font_fn(13, 560)), QFontMetrics(self.font_fn(15, 460))
            value_lines = len(wrap(vf_, value, width - 116 - 36, 2))
            row_h = max(36, value_lines * vf_.lineSpacing() + 12)
            row = QRectF(pad - 8, y, width + 16, row_h)
            name = f"row{i}"
            targets[name] = (row, lambda v=value: self.copyRequested.emit(v))
            if paint:
                if self._hover == name:
                    paint.setPen(Qt.PenStyle.NoPen)
                    paint.setBrush(QColor(255, 255, 255, 14))
                    paint.drawRoundedRect(row, 12, 12)
                    self._paint_copy_icon(paint, QRectF(row.right() - 34, row.top() + (row_h - 28) / 2, 28, 28), True)
            text(label, 13, 560, c["on_surface_variant"], pad, y + 6 + (vf_.lineSpacing() - lf.lineSpacing()) / 2, w=110)
            text(value, 15, 460, c["on_surface"], pad + 116, y + 6, w=width - 116 - 36, max_lines=2)
            y += row_h
        if info.rows:
            y += 8

        if info.items:
            y = self._items(paint, info.items, QRectF(pad - 8, y, width + 16, 0), targets) + 8

        if info.translation:
            inner = QRectF(pad - 8, y, width + 16, 0)
            ix, iw = inner.left() + 16, inner.width() - 32 - 40
            label_h = QFontMetrics(self.font_fn(12, 600)).lineSpacing()
            big = 19 if info.kind != "translation" else 17
            fm_big = QFontMetrics(self.font_fn(big, 560))
            n_lines = len(wrap(fm_big, info.translation, iw, 6 if info.kind == "translation" else 2))
            alt_h = QFontMetrics(self.font_fn(13, 430)).lineSpacing() if info.alternatives else 0
            inner.setHeight(14 + label_h + 4 + n_lines * fm_big.lineSpacing() + (4 + alt_h if alt_h else 0) + 14)
            if paint:
                paint.setPen(Qt.PenStyle.NoPen)
                paint.setBrush(c["surface_high"])
                paint.drawRoundedRect(inner, 18, 18)
            copy_button("copy", QRectF(inner.right() - 14 - 36, inner.top() + 12, 36, 36), info.translation)
            ty = inner.top() + 14
            ty += text(info.translation_label, 12, 600, c["primary"], ix, ty)[0] + 4
            ty += text(info.translation, big, 560, c["on_surface"], ix, ty, w=iw,
                       max_lines=6 if info.kind == "translation" else 2)[0]
            if info.alternatives:
                text(", ".join(info.alternatives), 13, 430, c["on_surface_variant"], ix, ty + 4, w=iw)
            y = inner.bottom() + 12

        if info.map_image is not None:
            m = QRectF(pad - 8, y, width + 16, info.map_image.height() * (width + 16) / info.map_image.width())
            if paint:
                clip = QPainterPath()
                clip.addRoundedRect(m, 18, 18)
                paint.save()
                paint.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                paint.drawImage(m, info.map_image)
                if info.map_attribution:
                    af = self.font_fn(10, 500)
                    afm = QFontMetrics(af)
                    aw = afm.horizontalAdvance(info.map_attribution) + 12
                    ar = QRectF(m.right() - aw, m.bottom() - afm.height() - 4, aw, afm.height() + 4)
                    paint.fillRect(ar, QColor(0, 0, 0, 120))
                    paint.setFont(af)
                    paint.setPen(QColor(255, 255, 255, 170))
                    paint.drawText(ar, Qt.AlignmentFlag.AlignCenter, info.map_attribution)
                paint.restore()
            y = m.bottom() + 12

        if info.actions:
            af = self.font_fn(13, 580)
            afm = QFontMetrics(af)
            x = pad - 8
            for i, action in enumerate(info.actions):
                aw = afm.horizontalAdvance(action.label) + 32
                if x + aw > pad + width + 8 and x > pad:
                    x, y = pad - 8, y + 40 + 8
                r = QRectF(x, y, aw, 40)
                name = f"action{i}"
                emit = (lambda a=action: self.openRequested.emit(a.payload)) if action.kind == "open" \
                    else (lambda a=action: self.copyRequested.emit(a.payload))
                targets[name] = (r, emit)
                if paint:
                    primary = i == 0
                    hover = self._hover == name
                    bg = c["primary"] if primary else c["surface_high"]
                    fg = c["on_primary"] if primary else c["on_surface"]
                    paint.setPen(Qt.PenStyle.NoPen)
                    paint.setBrush(bg)
                    paint.drawRoundedRect(r, 20, 20)
                    if hover:
                        paint.setBrush(QColor(fg.red(), fg.green(), fg.blue(), 22))
                        paint.drawRoundedRect(r, 20, 20)
                    paint.setFont(af)
                    paint.setPen(fg)
                    paint.drawText(r, Qt.AlignmentFlag.AlignCenter, action.label)
                x += aw + 8
            y += 40 + 14

        if info.source:
            f = self.font_fn(12, 560)
            fm = QFontMetrics(f)
            label = info.source
            r = QRectF(pad, y, fm.horizontalAdvance(label) + 2, fm.lineSpacing())
            if info.url:
                targets["source"] = (r.adjusted(-6, -4, 6, 4), lambda: self.openRequested.emit(info.url))
            if paint:
                paint.setFont(f)
                hover = self._hover == "source"
                paint.setPen(c["on_surface"] if hover else c["on_surface_variant"])
                paint.drawText(QPointF(r.left(), r.top() + fm.ascent()), label)
                if hover:
                    paint.drawLine(QPointF(r.left(), r.bottom() - 1), QPointF(r.right(), r.bottom() - 1))
            y += fm.lineSpacing()
        else:
            y -= 10

        self._targets = targets
        return int(y + pad - 4)

    CHART_MARK = QColor("#4285F4")

    def _forecast(self, paint, days, area, targets):
        c = self.c
        top_label, bars_h, bottom_label = 18, 96, 18
        day_h, rain_h = 18, 16
        n = len(days)
        col = area.width() / n
        lo = min(d["lo"] for d in days)
        hi = max(d["hi"] for d in days)
        span = max(hi - lo, 1.0)
        y0 = area.top() + top_label
        y1 = y0 + bars_h

        def ty(t):
            return y1 - (t - lo) / span * bars_h

        f_val, f_day, f_rain = self.font_fn(13, 560), self.font_fn(12, 520), self.font_fn(11, 520)
        hot = max(range(n), key=lambda i: days[i]["hi"])
        cold = min(range(n), key=lambda i: days[i]["lo"])
        any_rain = any((d["rain"] or 0) >= 30 for d in days)
        bottom = y1 + bottom_label + day_h + (rain_h if any_rain else 0)

        for i, d in enumerate(days):
            cx = area.left() + col * (i + 0.5)
            column = QRectF(area.left() + col * i, area.top(), col, bottom - area.top())
            name = f"day{i}"
            targets[name] = (column, None)
            if not paint:
                continue
            if self._hover == name:
                paint.setPen(Qt.PenStyle.NoPen)
                paint.setBrush(QColor(255, 255, 255, 12))
                paint.drawRoundedRect(column.adjusted(3, 0, -3, 0), 10, 10)
            bar = QRectF(cx - 5, ty(d["hi"]), 10, max(10.0, ty(d["lo"]) - ty(d["hi"])))
            paint.setPen(Qt.PenStyle.NoPen)
            paint.setBrush(self.CHART_MARK)
            paint.drawRoundedRect(bar, 5, 5)
            paint.setFont(f_val)
            paint.setPen(c["on_surface"])
            if i == hot:
                paint.drawText(QRectF(cx - col / 2, bar.top() - top_label, col, top_label - 2),
                               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"{round(d['hi'])}°")
            if i == cold:
                paint.drawText(QRectF(cx - col / 2, bar.bottom() + 2, col, bottom_label),
                               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{round(d['lo'])}°")
            paint.setFont(f_day)
            paint.setPen(c["on_surface"] if i == 0 else c["on_surface_variant"])
            paint.drawText(QRectF(cx - col / 2, y1 + bottom_label, col, day_h), Qt.AlignmentFlag.AlignCenter, d["label"])
            if (d["rain"] or 0) >= 30:
                ry = y1 + bottom_label + day_h
                fm = QFontMetrics(f_rain)
                label = f"{d['rain']}%"
                tw = fm.horizontalAdvance(label)
                drop_x = cx - (tw + 9) / 2
                drop = QPainterPath(QPointF(drop_x + 3, ry + 3))
                drop.cubicTo(QPointF(drop_x + 3, ry + 3), QPointF(drop_x - 0.5, ry + 8), QPointF(drop_x + 3, ry + 11))
                drop.cubicTo(QPointF(drop_x + 6.5, ry + 8), QPointF(drop_x + 3, ry + 3), QPointF(drop_x + 3, ry + 3))
                paint.setPen(Qt.PenStyle.NoPen)
                paint.setBrush(c["on_surface_variant"])
                paint.drawPath(drop)
                paint.setFont(f_rain)
                paint.setPen(c["on_surface_variant"])
                paint.drawText(QRectF(drop_x + 9, ry, tw + 2, rain_h), Qt.AlignmentFlag.AlignVCenter, label)

        if paint and self._hover and self._hover.startswith("day"):
            d = days[int(self._hover[3:])]
            lines = [d["date"], f"{round(d['hi'])}° / {round(d['lo'])}°   {d['text']}"]
            if d["rain"] is not None:
                lines.append(f"{d['rain']}% chance of rain")
            ft = self.font_fn(12, 520)
            fm = QFontMetrics(ft)
            w = max(fm.horizontalAdvance(s) for s in lines) + 20
            h = fm.lineSpacing() * len(lines) + 12
            i = int(self._hover[3:])
            cx = area.left() + col * (i + 0.5)
            x = min(max(area.left(), cx - w / 2), area.right() - w)
            tip = QRectF(x, area.top() - h + 4, w, h)
            paint.setPen(QPen(QColor(255, 255, 255, 24), 1))
            paint.setBrush(c["surface_high"])
            paint.drawRoundedRect(tip, 10, 10)
            paint.setFont(ft)
            for k, s in enumerate(lines):
                paint.setPen(c["on_surface"] if k == 1 else c["on_surface_variant"])
                paint.drawText(QPointF(tip.left() + 10, tip.top() + 6 + fm.ascent() + k * fm.lineSpacing()), s)
        return bottom

    @staticmethod
    def _format(v, s):
        kind = s.get("format")
        if kind == "compact":
            for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
                if abs(v) >= size:
                    return f"{v / size:.1f}".rstrip("0").rstrip(".") + suffix
            return f"{v:,.0f}"
        if kind == "usd":
            return f"${v:,.0f}"
        if kind == "money":
            return money_str(v, s.get("currency", PROFILE.currency))
        return f"{v:,.2f}"

    def _lines(self, paint, series, area, targets):
        c = self.c
        y = area.top()
        f_label, f_value, f_axis = self.font_fn(12, 560), self.font_fn(15, 600), self.font_fn(11, 500)
        for k, s in enumerate(series):
            pts = s["points"]
            head_h, plot_h, axis_h = 22, 54, 16
            plot = QRectF(area.left() + 4, y + head_h + 4, area.width() - 8, plot_h)
            name = f"series{k}"
            targets[name] = (plot.adjusted(-4, -8, 4, 8), None)
            if paint:
                vs = [v for _, v in pts]
                lo, hi = min(vs), max(vs)
                pad_v = (hi - lo) * 0.08 or abs(hi) * 0.02 or 1
                lo, hi = lo - pad_v, hi + pad_v

                def pos(i, v):
                    return QPointF(plot.left() + plot.width() * i / (len(pts) - 1),
                                   plot.bottom() - (v - lo) / (hi - lo) * plot.height())

                paint.setFont(f_label)
                paint.setPen(c["on_surface_variant"])
                paint.drawText(QRectF(area.left(), y, area.width() / 2, head_h), Qt.AlignmentFlag.AlignVCenter, s["label"])
                paint.setFont(f_value)
                paint.setPen(c["on_surface"])
                paint.drawText(QRectF(area.left() + area.width() / 2, y, area.width() / 2, head_h),
                               Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._format(pts[-1][1], s))
                line = QPainterPath(pos(0, pts[0][1]))
                for i, (_, v) in enumerate(pts[1:], 1):
                    line.lineTo(pos(i, v))
                wash = QPainterPath(line)
                wash.lineTo(QPointF(plot.right(), plot.bottom()))
                wash.lineTo(QPointF(plot.left(), plot.bottom()))
                wash.closeSubpath()
                mark = self.CHART_MARK
                paint.setPen(Qt.PenStyle.NoPen)
                paint.setBrush(QColor(mark.red(), mark.green(), mark.blue(), 26))
                paint.drawPath(wash)
                paint.setBrush(Qt.BrushStyle.NoBrush)
                paint.setPen(QPen(mark, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                paint.drawPath(line)
                hover_i = None
                if self._hover == name and len(pts) > 1:
                    rel = (self._mouse.x() - plot.left()) / plot.width()
                    hover_i = max(0, min(len(pts) - 1, round(rel * (len(pts) - 1))))
                end = pos(len(pts) - 1, pts[-1][1]) if hover_i is None else pos(hover_i, pts[hover_i][1])
                if hover_i is not None:
                    paint.setPen(QPen(QColor(255, 255, 255, 50), 1))
                    paint.drawLine(QPointF(end.x(), plot.top()), QPointF(end.x(), plot.bottom()))
                paint.setPen(QPen(c["surface"], 2))
                paint.setBrush(mark)
                paint.drawEllipse(end, 5, 5)
                paint.setFont(f_axis)
                paint.setPen(c["on_surface_variant"])
                axis = QRectF(plot.left(), plot.bottom() + 2, plot.width(), axis_h)
                paint.drawText(axis, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(pts[0][0]))
                paint.drawText(axis, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(pts[-1][0]))
                if hover_i is not None:
                    tip_text = f"{pts[hover_i][0]}: {self._format(pts[hover_i][1], s)}"
                    fm = QFontMetrics(f_axis)
                    w = fm.horizontalAdvance(tip_text) + 16
                    tip = QRectF(min(max(plot.left(), end.x() - w / 2), plot.right() - w), plot.top() - 6, w, fm.height() + 8)
                    paint.setPen(QPen(QColor(255, 255, 255, 24), 1))
                    paint.setBrush(c["surface_high"])
                    paint.drawRoundedRect(tip, 8, 8)
                    paint.setPen(c["on_surface"])
                    paint.drawText(tip, Qt.AlignmentFlag.AlignCenter, tip_text)
            y += head_h + 4 + plot_h + axis_h + 10
        return y

    def _items(self, paint, items, area, targets):
        c, y = self.c, area.top()
        f_title, f_sub = self.font_fn(14, 560), self.font_fn(12, 450)
        ft, fs = QFontMetrics(f_title), QFontMetrics(f_sub)
        for i, item in enumerate(items):
            row = QRectF(area.left(), y, area.width(), 56)
            name = f"item{i}"
            targets[name] = (row, (lambda u=item["url"]: self.openRequested.emit(u)) if item.get("url") else None)
            if paint:
                if self._hover == name:
                    paint.setPen(Qt.PenStyle.NoPen)
                    paint.setBrush(QColor(255, 255, 255, 14))
                    paint.drawRoundedRect(row, 14, 14)
                thumb = QRectF(row.left() + 8, row.top() + 6, 44, 44)
                clip = QPainterPath()
                clip.addRoundedRect(thumb, 10, 10)
                paint.save()
                paint.setClipPath(clip, Qt.ClipOperation.IntersectClip)
                img = item.get("image")
                if img is not None and not img.isNull():
                    side = min(img.width(), img.height())
                    src = QRectF((img.width() - side) / 2, (img.height() - side) / 2, side, side)
                    paint.drawImage(thumb, img, src)
                else:
                    paint.fillRect(thumb, c["surface_high"])
                paint.restore()
                x = thumb.right() + 12
                w = row.right() - 10 - x
                paint.setFont(f_title)
                paint.setPen(c["on_surface"])
                paint.drawText(QPointF(x, row.top() + 10 + ft.ascent()),
                               ft.elidedText(item["title"], Qt.TextElideMode.ElideRight, int(w)))
                paint.setFont(f_sub)
                paint.setPen(c["on_surface_variant"])
                paint.drawText(QPointF(x, row.top() + 30 + fs.ascent()),
                               fs.elidedText(item.get("subtitle", ""), Qt.TextElideMode.ElideRight, int(w)))
            y += 56
        return y

    def _paint_copy_icon(self, p, r, hover):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 22 if hover else 0))
        p.drawEllipse(r)
        c = r.center()
        p.setPen(QPen(self.c["on_surface_variant"] if not hover else self.c["on_surface"], 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(c.x() - 5, c.y() - 3, 9, 10), 2.5, 2.5)
        p.drawRoundedRect(QRectF(c.x() - 2, c.y() - 7, 9, 10), 2.5, 2.5)


if __name__ == "__main__":
    router = default_router()
    for arg in sys.argv[1:] or ["idempotent"]:
        start = time.perf_counter()
        r = router.route(arg)
        routed = time.perf_counter()
        info = lookup(arg, r)
        print(f"{arg!r}: {r.kind} (known word: {r.known_word}) via {router.name}, "
              f"routed in {(routed - start) * 1000:.1f} ms, card in {(time.perf_counter() - start) * 1000:.0f} ms")
        print(f"  {info}\n")
