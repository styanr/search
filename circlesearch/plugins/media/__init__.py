import re
import urllib.parse

from circlesearch.core.net import get_json, safe
from circlesearch.core.pipeline import enricher
from circlesearch.plugins.wikidata import wikidata_facts

KINDS = (
    ("series", re.compile(r"television series|tv series|web series|miniseries|animated series", re.I)),
    ("film", re.compile(r"\bfilm\b|\bmovie\b", re.I)),
    ("book", re.compile(r"\bnovel\b|\bnovella\b|\bbook\b|\bmemoir\b|\bshort story\b|\bpoem\b|\bplay\b", re.I)),
    ("album", re.compile(r"\balbum\b|\bep\b|\bmixtape\b", re.I)),
    ("song", re.compile(r"\bsingle\b|\bsong\b", re.I)),
)
MAX_WORDS = 6
MAX_KINDS = 2


def kind_of(description):
    return next((kind for kind, pattern in KINDS if pattern.search(description)), None)


def base_title(title):
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip().lower()


def find_works(name):
    q = urllib.parse.urlencode({"q": name, "limit": 10})
    data = get_json(f"https://en.wikipedia.org/w/rest.php/v1/search/page?{q}")
    wanted = name.strip().lower()
    out, seen = [], set()
    for page in (data or {}).get("pages", []):
        kind = kind_of(page.get("description") or "")
        if kind and kind not in seen and base_title(page["title"]) == wanted:
            seen.add(kind)
            out.append((kind, page["title"]))
    return out[:MAX_KINDS]


@enricher("media", needs={"name"}, order=15)
def media(facts):
    name = facts["name"]
    if len(name.split()) > MAX_WORDS or not name[:1].isupper():
        return [], {}
    cards = []
    for _, title in find_works(name):
        page = safe(get_json, "https://en.wikipedia.org/api/rest_v1/page/summary/"
                    + urllib.parse.quote(title.replace(" ", "_")))
        qid = (page or {}).get("wikibase_item")
        if qid:
            found, _ = wikidata_facts({"qid": qid, "title": title}) or ([], {})
            cards += found
    return cards, {}
