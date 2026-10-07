import re
import urllib.parse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date

from circlesearch.core.cards import Action, Card
from circlesearch.core.locale import current
from circlesearch.core.net import get_json
from circlesearch.core.pipeline import enricher

WDQS = "https://query.wikidata.org/sparql?format=json&query="
QLEVER = "https://qlever.dev/api/wikidata?query="
WD_PROPS = ("P31 P17 P36 P37 P38 P474 P1082 P2046 P2044 P571 P577 P569 P570 P27 P106 P856 P1324 P277 P275 "
            "P178 P348 P159 P169 P1128 P452 P498 P297 P5568 P8262 P50 P57 P136 P161 P170 P175 P212 P957 P8383 P436 P435 P345 "
            "P4947 P4983 P8600 P495 P2047 P2437 P2205 P2207").split()
SPARQL_PREFIXES = ("PREFIX wd: <http://www.wikidata.org/entity/>\nPREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
                   "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n")


@dataclass(kw_only=True)
class FactsCard(Card):
    kind = "facts"
    priority = 2
    anchored = True
    accent = "blue"

    rows: list[tuple[str, str]] = field(default_factory=list)


def _sparql(endpoint, query):
    data = get_json(endpoint + urllib.parse.quote(SPARQL_PREFIXES + query),
                    {"Accept": "application/sparql-results+json"})
    return data["results"]["bindings"]


def sparql(query, head_start=0.6):
    pool = ThreadPoolExecutor(2)
    try:
        futures = [pool.submit(_sparql, WDQS, query)]
        done, _ = wait(futures, timeout=head_start)
        if not done or futures[0].exception():
            futures.append(pool.submit(_sparql, QLEVER, query))
        for f in _first_good(futures):
            return f
        return []
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _first_good(futures):
    pending = set(futures)
    while pending:
        done, pending = wait(pending, return_when=FIRST_COMPLETED)
        for f in done:
            if not f.exception():
                yield f.result()


def wd_claims(qid, props=WD_PROPS):
    query = f"""SELECT ?p ?v ?en ?mul ?uk ?iso WHERE {{
  VALUES ?p {{ {" ".join("wdt:" + p for p in props)} }}
  wd:{qid} ?p ?v .
  OPTIONAL {{ ?v rdfs:label ?uk FILTER(LANG(?uk) = "{current().language}") }}
  OPTIONAL {{ ?v rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?v rdfs:label ?mul FILTER(LANG(?mul) = "mul") }}
  OPTIONAL {{ ?v wdt:P498 ?iso }}
}}"""
    out = {}
    for row in sparql(query):
        pid = row["p"]["value"].rsplit("/", 1)[-1]
        v = row["v"]["value"]
        if v.startswith("http://www.wikidata.org/entity/"):
            v = v.rsplit("/", 1)[-1]
        en = row.get("en", {}).get("value") or row.get("mul", {}).get("value", "")
        out.setdefault(pid, []).append((v, en, row.get("uk", {}).get("value", ""), row.get("iso", {}).get("value", "")))
    return out


def _date(iso):
    m = re.match(r"(-?)(\d+)-(\d\d)-(\d\d)", iso)
    if not m:
        return iso
    if m.group(1):
        return f"{int(m.group(2))} BC"
    try:
        return date(int(m.group(2)), int(m.group(3)), int(m.group(4)))
    except ValueError:
        return m.group(2)


def genres(labels):
    return ", ".join(re.sub(r"\s+(film|series)$", "", g, flags=re.I) for g in labels("P136", 2).split(", ") if g)


def work_rows(work, claims, labels, first, year, imdb):
    new = {}
    for key, pid in (("isbn", "P212"), ("tvmaze", "P8600")):
        if first(pid):
            new[key] = first(pid)
    if work == "album" and first("P436"):
        new["mb_rg"] = first("P436")
    if imdb:
        new["imdb"] = imdb
    length = None
    if first("P2047"):
        try:
            amount = float(first("P2047"))
            if work in ("song", "album"):
                total = int(amount)
                length = f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}" if total >= 3600 \
                    else f"{total // 60}:{total % 60:02d}"
            else:
                length = f"{amount:.0f} min"
        except ValueError:
            pass
    if work == "book":
        rows = [("Author", labels("P50", 3)), ("First published", year("P577") or ""), ("Genre", genres(labels))]
    elif work in ("album", "song"):
        rows = [("Artist", labels("P175", 3)), ("Released", year("P577") or ""), ("Genre", genres(labels))]
        if length:
            rows.append(("Length", length))
    elif work == "series":
        rows = [("Created by", labels("P170", 2)), ("Starring", labels("P161", 4)), ("Seasons", first("P2437") or ""),
                ("First aired", year("P577") or ""), ("Genre", genres(labels)), ("Country", labels("P495", 1))]
    else:
        rows = [("Directed by", labels("P57", 2)), ("Starring", labels("P161", 4)), ("Released", year("P577") or ""),
                ("Runtime", length or ""), ("Genre", genres(labels)), ("Country", labels("P495", 1))]
    return rows, new


def work_actions(claims, first, imdb):
    out = []
    if imdb:
        out.append(Action("IMDb", "open", f"https://www.imdb.com/title/{imdb}/"))
    if first("P2205"):
        out.append(Action("Spotify", "open", f"https://open.spotify.com/album/{first('P2205')}"))
    elif first("P2207"):
        out.append(Action("Spotify", "open", f"https://open.spotify.com/track/{first('P2207')}"))
    if first("P8383"):
        out.append(Action("Goodreads", "open", f"https://www.goodreads.com/work/editions/{first('P8383')}"))
    return out


@enricher("wikidata", needs={"qid"}, order=20)
def wikidata_facts(facts):
    qid = facts["qid"]
    claims = wd_claims(qid)
    if not claims:
        return [], {}

    def labels(pid, n=2):
        return ", ".join(en or uk for _, en, uk, _ in claims.get(pid, [])[:n] if en or uk)

    def first(pid):
        return claims[pid][0][0] if claims.get(pid) else None

    def year(pid):
        d = _date(first(pid)) if first(pid) else None
        return str(d.year) if isinstance(d, date) else d

    kinds = {v for v, _, _, _ in claims.get("P31", [])}
    is_person = "Q5" in kinds
    is_country = bool(kinds & {"Q6256", "Q3624078", "Q7275"}) and "P36" in claims
    is_software = any(p in claims for p in ("P348", "P1324", "P277")) and not is_person
    is_org = any(p in claims for p in ("P1128", "P159", "P169", "P452")) and not (is_person or is_country)
    is_place = not (is_person or is_country or is_org or is_software) and ("P1082" in claims or "P2044" in claims)
    imdb = first("P345") if str(first("P345")).startswith("tt") else None
    work = None
    if not (is_person or is_country or is_org or is_software or is_place):
        if any(p in claims for p in ("P2437", "P4983", "P8600")):
            work = "series"
        elif imdb or "P4947" in claims or "P57" in claims:
            work = "film"
        elif any(p in claims for p in ("P212", "P957", "P8383", "P50")):
            work = "book"
        elif "P436" in claims:
            work = "album"
        elif "P435" in claims and "P175" in claims:
            work = "song"

    rows, new = [], {}
    if work:
        rows, new = work_rows(work, claims, labels, first, year, imdb)
    elif is_person:
        born, died = first("P569"), first("P570")
        if born:
            b = _date(born)
            if isinstance(b, date) and not died:
                rows.append(("Born", f"{b:%-d %B %Y} (age {(date.today() - b).days // 365})"))
            else:
                rows.append(("Born", b.strftime("%-d %B %Y") if isinstance(b, date) else b))
        if died:
            d = _date(died)
            rows.append(("Died", d.strftime("%-d %B %Y") if isinstance(d, date) else d))
        rows += [("Occupation", labels("P106", 3)), ("Citizenship", labels("P27"))]
    elif is_country:
        rows.append(("Capital", labels("P36", 1)))
        if first("P1082"):
            rows.append(("Population", current().format_compact(float(first("P1082")))))
        currencies = sorted(claims.get("P38", []), key=lambda c: (c[3] != "EUR", not c[3] or c[3].startswith("X")))
        if currencies:
            cq, cen, cuk, _ = currencies[0]
            rows.append(("Currency", cen or cuk))
            new["currency_qid"] = cq
        rows.append(("Languages", labels("P37")))
        if first("P474"):
            rows.append(("Calling code", first("P474")))
        if first("P297"):
            new["iso2"] = first("P297")
    elif is_software:
        rows.append(("Developer", labels("P178")))
        if first("P348"):
            rows.append(("Latest version", first("P348")))
        rows += [("Licence", labels("P275", 1)), ("Written in", labels("P277", 3)),
                 ("First released", year("P571") or year("P577") or "")]
    elif is_org:
        rows += [("Founded", year("P571") or ""), ("Headquarters", labels("P159", 1)),
                 ("Chief executive", labels("P169", 1))]
        if first("P1128"):
            rows.append(("Employees", current().format_compact(float(first("P1128")))))
        rows.append(("Industry", labels("P452")))
    elif is_place:
        rows.append(("Country", labels("P17", 1)))
        if first("P1082"):
            rows.append(("Population", current().format_compact(float(first("P1082")))))
        if first("P2046"):
            km2 = float(first("P2046"))
            rows.append(("Area", f"{km2:,.0f} km²" if km2 >= 10 else f"{km2:,.2f} km²"))
        if first("P2044"):
            rows.append(("Elevation", f"{float(first('P2044')):,.0f} m"))
        rows.append(("Founded", year("P571") or ""))

    if first("P5568"):
        new["pypi"] = first("P5568")
    if first("P8262"):
        new["npm"] = first("P8262")
    for url, _, _, _ in claims.get("P1324", []):
        m = re.match(r"https?://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
        if m:
            new["github_repo"] = m.group(1)
            break

    shown = [(name, value) for name, value in rows if value]
    if len(shown) < (2 if work else 3):
        return [], new
    actions = [Action("Website", "open", first("P856"))] if first("P856") else []
    if work:
        actions = work_actions(claims, first, imdb)
    title = None
    if work:
        kind = {"album": "Album", "song": "Song", "book": "Book", "film": "Film", "series": "TV series"}[work]
        name = re.sub(r"\s*\([^)]*\)\s*$", "", facts.get("title", "")).strip()
        title = f"{name} · {kind}" if name else kind
    return [FactsCard(title=title or "At a glance", rows=shown, actions=actions, source="Wikidata",
                      url=f"https://www.wikidata.org/wiki/{qid}")], new
