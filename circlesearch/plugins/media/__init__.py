import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from circlesearch.core.cards import Dismiss, Pending
from circlesearch.core.net import get_json, safe
from circlesearch.core.pipeline import enricher, resolver
from circlesearch.plugins.wikidata import work_card

LABELS = {"series": "TV series", "film": "Film", "book": "Book", "album": "Album", "song": "Song"}
KINDS = (
    ("series", re.compile(r"television series|tv series|web series|miniseries|animated series", re.I)),
    ("film", re.compile(r"\bfilm\b|\bmovie\b", re.I)),
    ("book", re.compile(r"\bnovel\b|\bnovella\b|\bbook\b|\bmemoir\b|\bshort story\b|\bpoem\b|\bplay\b", re.I)),
    ("album", re.compile(r"\balbum\b|\bep\b|\bmixtape\b", re.I)),
    ("song", re.compile(r"\bsingle\b|\bsong\b", re.I)),
)
MAX_WORDS = 10
MAX_KINDS = 2


def kind_of(description):
    if re.search(r"soundtrack|score|music from", description, re.I):
        return None
    return next((kind for kind, pattern in KINDS if pattern.search(description)), None)


def base_title(title):
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip().lower()


def norm(text):
    return " ".join(re.sub(r"[^\w\s]", " ", base_title(text).replace("'", "").replace("’", "")).split())


def find_works(name):
    q = urllib.parse.urlencode({"q": name, "limit": 10})
    data = get_json(f"https://en.wikipedia.org/w/rest.php/v1/search/page?{q}")
    wanted = norm(name)
    out, seen = [], set()
    for page in (data or {}).get("pages", []):
        kind = kind_of(page.get("description") or "")
        if kind and kind not in seen and norm(page["title"]) == wanted:
            seen.add(kind)
            out.append((kind, page["title"]))
    return out[:MAX_KINDS]


def build(kind, title):
    return work_card(title)


@enricher("media", needs={"name"}, order=15, stream=True)
def media(facts, emit):
    name = facts["name"]
    if len(name.split()) > MAX_WORDS or not name[:1].isupper():
        return [], {}
    works = [w for w in find_works(name) if w[1] != facts.get("skip")]
    for kind, title in works:
        emit(Pending(title="", slot=title, label=f"Looking up {base_title(title).title()} · {LABELS[kind]}…"))

    def fill(work):
        kind, title = work
        card = safe(build, kind, title)
        if card is None:
            emit(Dismiss(title="", slot=title))
        else:
            card.slot = title
            emit(card)

    with ThreadPoolExecutor(max(1, len(works))) as pool:
        list(pool.map(fill, works))
    return [], {}


@resolver("title", placeholder=True)
def look_up_title(route):
    for kind, title in find_works(route.text):
        card = safe(build, kind, title)
        if card is not None:
            card.facts = {"name": route.text, "skip": title}
            return card
    return None
