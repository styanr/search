import html
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from circlesearch.core.cards import HeroCard, TextCard
from circlesearch.core.locale import current
from circlesearch.core.net import OPTIONAL_TIMEOUT, TIMEOUT, get_bytes, get_json, safe
from circlesearch.core.pipeline import resolver
from circlesearch.core.text import first_sentences, non_latin
from circlesearch.plugins.places import image_shape_for, place_card, zoom_for

MAX_TRANSLATE_CHARS = 600
SMALL_WORDS = {"of", "the", "and", "de", "la", "le", "in", "on", "at", "for", "du", "von", "van", "der"}
SKIP_POS = {"symbol", "letter", "abbreviation", "initialism", "acronym", "prefix", "suffix",
            "proper noun", "contraction", "particle", "phrase"}


@dataclass(kw_only=True)
class TermCard(TextCard):
    kind = "term"
    accent = "blue"


@dataclass(kw_only=True)
class TranslationCard(TextCard):
    kind = "translation"
    accent = "blue"
    title_role = "passage"


@dataclass(kw_only=True)
class EntityCard(HeroCard):
    kind = "entity"


def google_translate(text, source="auto", target=None):
    q = urllib.parse.urlencode({"client": "gtx", "sl": source, "tl": target or current().language, "q": text})
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


def wikipedia_title_in(title, lang, source="en"):
    q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "langlinks",
                                "lllang": lang, "redirects": 1, "format": "json"})
    data = get_json(f"https://{source}.wikipedia.org/w/api.php?{q}")
    for page in ((data or {}).get("query", {}).get("pages", {}) or {}).values():
        for link in page.get("langlinks", []):
            return link.get("*")
    return None


def smart_case(text):
    words = text.lower().split()
    return " ".join(w if i and w in SMALL_WORDS else "-".join(p[:1].upper() + p[1:] for p in w.split("-"))
                    for i, w in enumerate(words))


def pick_sense(senses, lang, preferred_pos):
    options = senses.get(lang, [])
    real = [s for s in options if s[0] not in SKIP_POS] or options
    return next((s for s in real if s[0] in preferred_pos), real[0]) if real else None


@resolver("foreign_text")
def translate(route):
    t, target = route.text, current().language
    if len(t) > MAX_TRANSLATE_CHARS:
        return None
    tr = safe(google_translate, t, "auto", target)
    if not tr or not tr["translation"] or tr["detected"] in (target, current().ui_language):
        return None
    return translation_card(t, tr, target)


@resolver("term", "entity", placeholder=True)
def look_up(route):
    t, kind = route.text, route.kind
    loc = current()
    target, fallback = loc.language, loc.ui_language
    script = non_latin(t)
    detected = None
    if script:
        first = safe(google_translate, t, "auto", fallback)
        detected = (first or {}).get("detected")
        if detected and detected != fallback and len(t.split()) <= 4:
            card = native_name_card(t, detected)
            if card is not None:
                return card
    if detected == loc.language:
        target = fallback

    english = route.known_word is True and not script
    want_wiki = not english or kind == "entity" or t[:1].isupper()
    caps = t.isupper() and sum(ch.isalpha() for ch in t) >= 2
    name = smart_case(t) if caps else t
    with ThreadPoolExecutor(4) as pool:
        dict_f = pool.submit(safe, wiktionary, t.lower() if caps else t, OPTIONAL_TIMEOUT if kind == "entity" else TIMEOUT)
        tr_f = pool.submit(safe, google_translate, t, "en" if english else "auto", target)
        wiki_f = pool.submit(safe, wikipedia, name) if want_wiki else None
        native_f = pool.submit(safe, wikipedia_title_in, name, loc.language) \
            if want_wiki and not script and loc.language != "en" else None
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
        return TermCard(title=t, pronunciation=(tr or {}).get("pronunciation", "") if lang == "en" else "",
                        part_of_speech=pos, definition=definition,
                        description="" if lang == "en" else loc.language_name(lang),
                        translation=translation, translation_label=loc.language_name(target),
                        alternatives=alts, source="Wiktionary", facts={"name": t},
                        url="https://en.wiktionary.org/wiki/" + urllib.parse.quote(t.replace(" ", "_")))
    if wiki is None and english:
        wiki = safe(wikipedia, t)
    if wiki:
        return entity_card(wiki, native_title, tr, lang, target)
    if tr and tr["translation"] and tr["translation"].lower() != t.lower() and lang != target:
        return translation_card(t, tr, target)
    return None


def native_name_card(t, lang):
    loc = current()
    name = smart_case(t) if t.isupper() else t
    with ThreadPoolExecutor(2) as pool:
        native_f = pool.submit(safe, wikipedia, name, lang)
        en_title_f = pool.submit(safe, wikipedia_title_in, name, loc.ui_language, lang)
        native, en_title = native_f.result(), en_title_f.result()
    if not native:
        return None
    en = safe(wikipedia, en_title) if en_title else None
    if en is None:
        return entity_card(native, None, None, lang, lang)
    if lang == loc.language or loc.language == loc.ui_language:
        return entity_card(en, native["title"], None, "en", lang)
    shown = safe(wikipedia_title_in, en["title"], loc.language)
    return entity_card(en, shown or native["title"], None, "en", loc.language if shown else lang)


def entity_card(wiki, native_title, tr, lang, target):
    label = current().language_name(target)
    name = native_title or ((tr or {}).get("translation", "") if lang != target else "")
    if name and name.lower() == wiki["title"].lower():
        name = ""
    if wiki.get("lat") is not None:
        card = place_card(wiki["title"], wiki["lat"], wiki["lon"], zoom_for(wiki["description"]),
                          description=wiki["description"], definition=first_sentences(wiki["extract"], 1),
                          source="Wikipedia", url=wiki["url"], query=wiki["title"],
                          facts={"qid": wiki["qid"]} if wiki.get("qid") else None, image_url=wiki.get("thumb"))
        card.translation, card.translation_label = name, label
        return card
    picture = safe(get_bytes, wiki["thumb"]) if wiki.get("thumb") else None
    return EntityCard(title=wiki["title"], description=wiki["description"],
                      image=picture, image_shape=image_shape_for(wiki["description"]),
                      definition=first_sentences(wiki["extract"]), translation=name,
                      translation_label=label, source="Wikipedia", url=wiki["url"],
                      facts={"qid": wiki["qid"], "title": wiki["title"]} if wiki.get("qid") else {})


def translation_card(text, tr, target):
    loc = current()
    return TranslationCard(title=text, description=f"Translated from {loc.language_name(tr['detected'])}",
                           translation=tr["translation"], translation_label=loc.language_name(target),
                           source="Google Translate",
                           url="https://translate.google.com/?" + urllib.parse.urlencode(
                               {"sl": tr["detected"], "tl": target, "text": text, "op": "translate"}))
