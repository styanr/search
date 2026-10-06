import os
import re
import sys
import threading
from dataclasses import dataclass
from typing import Any, Callable

from circlesearch.core import settings
from circlesearch.core.registry import Registry
from circlesearch.core.text import EDGE_JUNK, non_latin, tidy


@dataclass
class Route:
    kind: str
    confidence: float = 1.0
    known_word: bool | None = None
    text: str = ""
    value: Any = None
    words: list | None = None
    source: str = ""


@dataclass
class Recognizer:
    kind: str
    parse: Callable[[str], Any]
    max_chars: int = 90
    in_spans: bool = True
    raw: bool = False


recognizers = Registry("recognizer")


def recognizer(kind, order=100, max_chars=90, in_spans=True, raw=False):
    def register(parse):
        recognizers.add(kind, Recognizer(kind, parse, max_chars, in_spans, raw), order)
        return parse
    return register


def recognise(text, spans_only=False, with_text=False):
    t, raw = tidy(text), text.strip()
    if not t and not raw:
        return None
    for r in recognizers:
        source = raw if r.raw else t
        if not source or len(source) > r.max_chars or (spans_only and not r.in_spans):
            continue
        try:
            value = r.parse(source)
        except (ValueError, OverflowError, TypeError):
            continue
        if value is not None:
            return (r.kind, value, source) if with_text else (r.kind, value)
    return None


def find_structured(text, max_words=12):
    words = tidy(text).split()
    if len(words) > max_words:
        return None
    for length in range(len(words) - 1, 0, -1):
        for start in range(len(words) - length + 1):
            span = tidy(" ".join(words[start:start + length]))
            found = recognise(span, spans_only=True)
            if found:
                return found[0], span, found[1]
    return None


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

CODE_SYMBOLS = re.compile(r"[{}\[\];=<>|\\`$]|::|->|=>|\w\(|\w+\.\w+\(|^\s*[$#>] ")
ERROR_WORDS = re.compile(r"\b(error|exception|traceback|errno|failed|fatal|warning|segfault)\b", re.I)
IDENTIFIER = re.compile(r"^[a-z]+(_[a-z0-9]+)+$|^[a-z]+([A-Z][a-z0-9]+)+$|^[\w.-]+/[\w./-]+$")
WORD = re.compile(r"^[^\W\d_]+(?:[-'’][^\W\d_]+)*$")

routers = Registry("router")


def router(cls):
    routers.add(cls.name, cls)
    return cls


@router
class LocalRouter:
    name = "local"

    def route(self, text):
        t = tidy(text)
        found = recognise(text, with_text=True)
        if found:
            return Route(found[0], text=found[2], value=found[1])
        found = find_structured(t)
        if found:
            return Route(found[0], text=found[1], value=found[2])
        letters = sum(c.isalpha() for c in t)
        if letters < 2 or letters < len(t) * 0.4:
            return Route("not_text", text=t)
        words = [w.strip(EDGE_JUNK) or w for w in t.split()]
        if CODE_SYMBOLS.search(t) or (len(words) == 1 and IDENTIFIER.match(t)) or \
                (ERROR_WORDS.search(t) and len(words) <= 30 and re.search(r"[:/_]", t)):
            return Route("code_or_error", text=t)
        if non_latin(t):
            return Route("term" if len(words) <= 4 else "foreign_text", known_word=False, text=t)

        have_dict = ENGLISH.available
        plain_words = [w for w in words if WORD.match(w)]
        known = [w in ENGLISH for w in plain_words] if have_dict else []
        if len(plain_words) == len(words) and len(words) <= 3 and len(t) <= 40:
            capitalised = all(w[0].isupper() for w in words)
            all_known = all(known) if have_dict else None
            if capitalised and (len(words) >= 2 or all_known is False):
                return Route("entity", known_word=all_known, text=t)
            return Route("term", known_word=all_known, text=t)
        if len(plain_words) == len(words) and len(words) <= 6 and all(w[0].isupper() for w in words):
            return Route("entity", known_word=False, text=t)
        if have_dict and plain_words:
            english_share = sum(known) / len(known)
            return Route("plain_text" if english_share >= 0.6 else "foreign_text",
                         confidence=abs(english_share - 0.6) + 0.4, text=t)
        return Route("foreign_text" if not t.isascii() else "plain_text", confidence=0.5, text=t)


def default_router():
    name = settings.ROUTER
    if name not in routers:
        print(f"context: unknown router {name!r}, using {LocalRouter.name!r}", file=sys.stderr)
        name = LocalRouter.name
    return routers.get(name)()
