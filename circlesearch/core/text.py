import re
import unicodedata

EDGE_JUNK = ".,;:!?\"'“”‘’„«»‹›()[]{}<>…|/\\*_~`^=—–-•·"
FOOTNOTE = re.compile(r"\[(?:\d{1,3}|[a-z]|citation needed|note \d+|edit)\]", re.I)
LIST_MARKER = re.compile(r"^(?:[-–—•·*>|]+|\(?\d{1,2}\))\s+")
POSSESSIVE = re.compile(r"^([A-Z][\w-]*(?: [A-Z][\w-]*)*)['’]s$")

BRACKETS = {"(": ")", "[": "]", "{": "}", "«": "»", "‹": "›", "“": "”", "„": "“", "‘": "’"}
CLOSERS = {v: k for k, v in BRACKETS.items()}
SIMPLE_JUNK = "".join(ch for ch in EDGE_JUNK if ch not in BRACKETS and ch not in CLOSERS)


def _strip_edges(t):
    t = t.strip()
    while t:
        first, last = t[0], t[-1]
        if len(t) > 1 and (BRACKETS.get(first) == last or (first == last and first in "\"'")):
            t = t[1:-1].strip()
        elif first in BRACKETS and t.count(first) > t.count(BRACKETS[first]):
            t = t[1:].strip()
        elif last in CLOSERS and t.count(last) > t.count(CLOSERS[last]):
            t = t[:-1].strip()
        elif first in SIMPLE_JUNK:
            t = t[1:].strip()
        elif last in SIMPLE_JUNK:
            t = t[:-1].strip()
        else:
            break
    return t


def tidy(text):
    t = unicodedata.normalize("NFC", text).replace("ﬁ", "fi").replace("ﬂ", "fl")
    t = re.sub(r"(\w)[-‐]\s*\n\s*(\w)", r"\1\2", t)
    t = FOOTNOTE.sub("", t)
    t = " ".join(t.split())
    previous = None
    while t != previous:
        previous = t
        t = _strip_edges(LIST_MARKER.sub("", t))
    m = POSSESSIVE.match(t)
    return m.group(1) if m else t


def non_latin(text):
    return any(ch.isalpha() and not unicodedata.name(ch, "").startswith("LATIN") for ch in text)


def parse_number(s):
    s = s.replace(" ", " ").replace("\xa0", " ").replace("'", "").replace(" ", "")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s or "." in s:
        sep = "," if "," in s else "."
        head, _, tail = s.rpartition(sep)
        if s.count(sep) == 1 and len(tail) != 3:
            s = head.replace(sep, "") + "." + tail
        else:
            s = s.replace(sep, "")
    return float(s)


def fmt(x, digits=2):
    if abs(x - round(x)) < 10 ** -digits / 2:
        return f"{round(x):,}"
    return f"{x:,.{digits}f}".rstrip("0").rstrip(".")


def first_sentences(text, n=2, limit=260):
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(parts[:n])
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0] + "…"
