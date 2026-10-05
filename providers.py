import re
import time
import urllib.parse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import date, datetime, timezone

from PyQt6.QtGui import QImage

from card_data import (OPTIONAL_TIMEOUT, Action, CardInfo, get_bytes, get_json, home_rates, money_str, rate_history, rate_of,
                       safe)
from locale_profile import PROFILE

ENRICH_DEADLINE = 6.0


@dataclass
class Provider:
    name: str
    needs: frozenset
    run: callable


def enrich(facts, emit, providers=None, deadline=ENRICH_DEADLINE):
    facts = dict(facts)
    pending = list(providers or PROVIDERS)
    end = time.monotonic() + deadline
    with ThreadPoolExecutor(6) as pool:
        running = {}

        def launch():
            for p in [p for p in pending if p.needs <= facts.keys()]:
                pending.remove(p)
                running[pool.submit(safe, p.run, dict(facts))] = p

        launch()
        while running and time.monotonic() < end:
            done, _ = wait(running, timeout=max(0.0, end - time.monotonic()), return_when=FIRST_COMPLETED)
            for f in done:
                running.pop(f)
                result = f.result()
                if not result:
                    continue
                cards, new_facts = result
                facts.update(new_facts or {})
                for card in cards:
                    emit(card)
            launch()
        for f in running:
            f.cancel()


WMO = [(0, "Clear"), (1, "Mostly clear"), (2, "Partly cloudy"), (3, "Cloudy"), (48, "Fog"), (57, "Drizzle"),
       (67, "Rain"), (77, "Snow"), (82, "Showers"), (86, "Snow showers"), (99, "Thunderstorm")]


def wmo_text(code):
    return next((w for c, w in WMO if (code or 0) <= c), "")


def weather_week(facts):
    if facts.get("zoom", 15) < 9:
        return [], {}
    with ThreadPoolExecutor(1) as pool:
        aqi_f = pool.submit(safe, air_quality, facts["lat"], facts["lon"])
        data = _forecast(facts)
        aqi = aqi_f.result()
    return _weather_card(facts, data, aqi)


def _forecast(facts):
    return get_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": f"{facts['lat']:.4f}", "longitude": f"{facts['lon']:.4f}", "timezone": "auto", "forecast_days": 7,
        **({} if PROFILE.metric else {"temperature_unit": "fahrenheit"}),
        "current": "temperature_2m,weather_code,apparent_temperature,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"}))


AQI_BANDS = [(20, "Good"), (40, "Fair"), (60, "Moderate"), (80, "Poor"), (100, "Very poor"), (10 ** 6, "Extremely poor")]


def air_quality(lat, lon):
    data = get_json("https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode(
        {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "current": "european_aqi"}), timeout=OPTIONAL_TIMEOUT)
    value = data["current"]["european_aqi"]
    if value is None:
        return None
    return f"Air: {next(name for limit, name in AQI_BANDS if value <= limit)} ({round(value)})"


def _weather_card(facts, data, aqi):
    d, cur = data["daily"], data["current"]
    days = []
    for i, day in enumerate(d["time"]):
        dt = date.fromisoformat(day)
        days.append({"label": "Today" if i == 0 else dt.strftime("%a"), "date": dt.strftime("%A %-d %B"),
                     "hi": d["temperature_2m_max"][i], "lo": d["temperature_2m_min"][i],
                     "rain": (d["precipitation_probability_max"] or [None] * 7)[i], "text": wmo_text(d["weather_code"][i]),
                     "code": d["weather_code"][i]})
    tz = data.get("timezone", "")
    local = datetime.now(timezone.utc).timestamp() + data.get("utc_offset_seconds", 0)
    local_time = datetime.fromtimestamp(local, timezone.utc).strftime("%H:%M")
    sunrise, sunset = d["sunrise"][0][-5:], d["sunset"][0][-5:]
    card = CardInfo("weather", f"Weather in {facts.get('title', 'this place')}",
                    value=f"{round(cur['temperature_2m'])}°", description=wmo_text(cur["weather_code"]),
                    chips=[f"Local time {local_time}", *([aqi] if aqi else []), f"Sunrise {sunrise}", f"Sunset {sunset}"],
                    chart={"type": "forecast", "days": days}, source="Open-Meteo",
                    now={"code": cur["weather_code"], "feels": cur.get("apparent_temperature", cur["temperature_2m"])},
                    is_day=bool(cur.get("is_day", 1)),
                    url=f"https://open-meteo.com/en/docs#latitude={facts['lat']:.4f}&longitude={facts['lon']:.4f}")
    return [card], {"timezone": tz}


WDQS = "https://query.wikidata.org/sparql?format=json&query="
QLEVER = "https://qlever.dev/api/wikidata?query="
WD_PROPS = ("P31 P17 P36 P37 P38 P474 P1082 P2046 P2044 P571 P577 P569 P570 P27 P106 P856 P1324 P277 P275 "
            "P178 P348 P159 P169 P1128 P452 P498 P297 P5568 P8262").split()
SPARQL_PREFIXES = ("PREFIX wd: <http://www.wikidata.org/entity/>\nPREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
                   "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n")


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
  OPTIONAL {{ ?v rdfs:label ?uk FILTER(LANG(?uk) = "{PROFILE.language}") }}
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


def _compact(n):
    for size, suffix in ((1e9, " billion"), (1e6, " million")):
        if abs(n) >= size:
            return f"{n / size:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{round(n):,}"


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

    rows, new = [], {}
    if is_person:
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
            rows.append(("Population", _compact(float(first("P1082")))))
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
            rows.append(("Employees", _compact(float(first("P1128")))))
        rows.append(("Industry", labels("P452")))
    elif is_place:
        rows.append(("Country", labels("P17", 1)))
        if first("P1082"):
            rows.append(("Population", _compact(float(first("P1082")))))
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
    if len(shown) < 3:
        return [], new
    actions = [Action("Website", "open", first("P856"))] if first("P856") else []
    return [CardInfo("facts", "At a glance", rows=shown, actions=actions, source="Wikidata",
                     url=f"https://www.wikidata.org/wiki/{qid}")], new


def country_currency(facts):
    qid = facts["currency_qid"]
    rows = sparql(f"""SELECT ?code ?en ?mul WHERE {{
  wd:{qid} wdt:P498 ?code .
  OPTIONAL {{ wd:{qid} rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ wd:{qid} rdfs:label ?mul FILTER(LANG(?mul) = "mul") }}
}}""")
    rates = home_rates()
    home = PROFILE.currency
    code = next((r["code"]["value"] for r in rows if rate_of(r["code"]["value"]) is not None), None)
    if code is None or code == home:
        return [], {}
    name = rows[0].get("en", {}).get("value") or rows[0].get("mul", {}).get("value") or code
    rate = rates[code]
    history = safe(rate_history, code, 30)
    chart = {"type": "lines", "series": [{"label": "Last 30 days", "points": history, "format": "money",
                                          "currency": home, "x": "date"}]} if history and len(history) > 2 else None
    return [CardInfo("money", name[:1].upper() + name[1:], value=money_str(rate, home), chart=chart,
                     description=f"1 {code}",
                     rows=[(f"100 {code}", money_str(100 * rate, home)),
                           (f"1 {home}", money_str(1 / rate, code))],
                     source=f"{rates['_source']}, {rates['_date']}", url=rates["_url"])], {}


def country_trends(facts):
    iso2 = facts["iso2"]

    def series(indicator):
        data = get_json(f"https://api.worldbank.org/v2/country/{iso2}/indicator/{indicator}?" + urllib.parse.urlencode(
            {"format": "json", "date": f"{date.today().year - 26}:{date.today().year}", "per_page": 100}))
        points = [(int(r["date"]), r["value"]) for r in (data[1] if data and len(data) > 1 and data[1] else [])
                  if r["value"] is not None]
        return sorted(points)

    with ThreadPoolExecutor(2) as pool:
        pop_f = pool.submit(safe, series, "SP.POP.TOTL")
        gdp_f = pool.submit(safe, series, "NY.GDP.PCAP.CD")
        pop, gdp = pop_f.result() or [], gdp_f.result() or []
    charts = []
    if len(pop) > 3:
        charts.append({"label": "Population", "points": pop, "format": "compact"})
    if len(gdp) > 3:
        charts.append({"label": "GDP per person", "points": gdp, "format": "usd"})
    if not charts:
        return [], {}
    return [CardInfo("trends", "Trends", chart={"type": "lines", "series": charts}, source="World Bank",
                     url=f"https://data.worldbank.org/country/{iso2.lower()}")], {}


def public_holidays(facts):
    iso2 = facts["iso2"]
    data = get_json(f"https://date.nager.at/api/v3/NextPublicHolidays/{iso2}")
    rows, items = [], []
    for h in (data or [])[:4]:
        d = date.fromisoformat(h["date"])
        days = (d - date.today()).days
        when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
        local = "" if h["localName"] == h["name"] else h["localName"]
        rows.append((f"{d:%-d %b}", f"{h['name']}{f' ({local})' if local else ''}, {when}"))
        items.append({"date": f"{d:%-d %b}", "name": h["name"], "local": local, "when": when})
    if not rows:
        return [], {}
    return [CardInfo("holidays", "Public holidays", rows=rows, items=items, source="Nager.Date",
                     url=f"https://date.nager.at/PublicHoliday/Country/{iso2}")], {}


EVENT_WORDS = re.compile(r"\b(battle|siege|war|uprising|massacre|pogrom|fire|election|treaty|offensive|attack|"
                         r"bombing|riot|protest|strike|crash|disaster|earthquake)\b", re.I)


def nearby(facts):
    zoom = facts.get("zoom", 15)
    if zoom < 9:
        return [], {}
    radius = 10000 if zoom <= 12 else 1500
    with ThreadPoolExecutor(2) as pool:
        geo_f = pool.submit(get_json, "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "geosearch", "ggscoord": f"{facts['lat']}|{facts['lon']}",
            "ggsradius": radius, "ggslimit": 20, "prop": "pageimages|description|coordinates",
            "piprop": "thumbnail", "pithumbsize": 120, "pilimit": 20}))
        voyage_f = pool.submit(safe, get_json, "https://en.wikivoyage.org/api/rest_v1/page/summary/"
                               + urllib.parse.quote(facts.get("title", "").replace(" ", "_"))) if zoom <= 12 else None
        geo = geo_f.result()
        voyage = voyage_f.result() if voyage_f else None
    pages = list(((geo or {}).get("query") or {}).get("pages", {}).values())
    places = []
    for p in pages:
        desc = p.get("description", "")
        if p.get("title") == facts.get("title") or EVENT_WORDS.search(p.get("title", "") + " " + desc):
            continue
        if not p.get("thumbnail") or not p.get("coordinates"):
            continue
        c = p["coordinates"][0]
        dist = _distance_km(facts["lat"], facts["lon"], c["lat"], c["lon"])
        places.append((dist, p["title"], desc, p["thumbnail"]["source"]))
    places.sort()
    places = places[:5]
    if len(places) < 2:
        return [], {}

    def thumb(url):
        img = QImage()
        img.loadFromData(get_bytes(url))
        return img if not img.isNull() else None

    with ThreadPoolExecutor(5) as pool:
        images = list(pool.map(lambda pl: safe(thumb, pl[3]), places))
    items = [{"title": title, "subtitle": f"{_km(dist)}{', ' + desc if desc else ''}", "image": img,
              "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))}
             for (dist, title, desc, _), img in zip(places, images)]
    blurb = ""
    if voyage and voyage.get("type") == "standard":
        blurb = re.split(r"(?<=[.!?])\s+", voyage.get("extract", ""))[0]
    return [CardInfo("nearby", f"Around {facts.get('title', 'here')}", definition=blurb, items=items,
                     source="Wikipedia" + (", Wikivoyage" if blurb else ""),
                     url=f"https://en.wikivoyage.org/wiki/{urllib.parse.quote(facts.get('title', ''))}" if blurb else "")], {}


def _distance_km(lat1, lon1, lat2, lon2):
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def _km(d):
    if not PROFILE.metric:
        miles = d * 0.621371
        return f"{d * 3280.84:.0f} ft" if miles < 0.2 else f"{miles:.1f} mi"
    return f"{d * 1000:.0f} m" if d < 1 else f"{d:.1f} km"


def npm_package(facts):
    return package(facts, "npm")


def pypi_package(facts):
    return package(facts, "pypi")


def package(facts, registry):
    if registry == "npm":
        name = facts["npm"]
        with ThreadPoolExecutor(2) as pool:
            meta_f = pool.submit(get_json, f"https://registry.npmjs.org/{name}/latest")
            dl_f = pool.submit(safe, get_json, f"https://api.npmjs.org/downloads/range/last-month/{name}")
            meta, dl = meta_f.result(), dl_f.result()
        if not meta:
            return [], {}
        days = [(date.fromisoformat(d["day"]).strftime("%-d %b"), d["downloads"]) for d in (dl or {}).get("downloads", [])]
        total = sum(v for _, v in days)
        chart = {"type": "lines", "series": [{"label": "Daily downloads", "points": days, "format": "compact", "x": "date"}]} \
            if len(days) > 2 else None
        return [CardInfo("package", f"npm i {name}", value=meta.get("version", ""), description="Latest version",
                         rows=[("Last 30 days", f"{_compact(total)} downloads")] if total else [], chart=chart,
                         actions=[Action("Copy install command", "copy", f"npm i {name}")],
                         source="npm", url=f"https://www.npmjs.com/package/{name}")], {}
    name = facts["pypi"]
    meta = get_json(f"https://pypi.org/pypi/{name}/json")
    if not meta:
        return [], {}
    info = meta["info"]
    released = meta.get("urls", [{}])[0].get("upload_time_iso_8601", "") if meta.get("urls") else ""
    rows = [("Released", _ago(released))] if released else []
    if info.get("requires_python"):
        rows.append(("Python", info["requires_python"]))
    return [CardInfo("package", f"pip install {name}", value=info.get("version", ""), description="Latest version",
                     definition=info.get("summary") or "", rows=rows,
                     actions=[Action("Copy install command", "copy", f"pip install {name}")],
                     source="PyPI", url=f"https://pypi.org/project/{name}/")], {}


def _ago(iso):
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    s = (datetime.now(timezone.utc) - then).total_seconds()
    for size, unit in ((365 * 86400, "year"), (30 * 86400, "month"), (7 * 86400, "week"), (86400, "day"), (3600, "hour")):
        if s >= size:
            n = int(s // size)
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


def github_repo(facts):
    repo = facts["github_repo"]
    headers = {"Accept": "application/vnd.github+json"}
    with ThreadPoolExecutor(2) as pool:
        info_f = pool.submit(get_json, f"https://api.github.com/repos/{repo}", headers)
        rel_f = pool.submit(safe, get_json, f"https://api.github.com/repos/{repo}/releases/latest", headers)
        info, release = info_f.result(), rel_f.result()
    if not info:
        return deps_dev_repo(repo)
    rows = [("Stars", _compact(info.get("stargazers_count", 0)))]
    if release and release.get("tag_name"):
        rows.append(("Latest release", f"{release['tag_name']}, {_ago(release['published_at'])}"))
    if info.get("pushed_at"):
        rows.append(("Last push", _ago(info["pushed_at"])))
    if info.get("language"):
        rows.append(("Language", info["language"]))
    rows.append(("Open issues", _compact(info.get("open_issues_count", 0))))
    return [CardInfo("repo", info.get("full_name", repo), definition=info.get("description") or "",
                     rows=rows, actions=[Action("Open on GitHub", "open", info.get("html_url", f"https://github.com/{repo}"))],
                     source="GitHub", url=info.get("html_url", ""))], {}


def deps_dev_repo(repo):
    info = get_json("https://api.deps.dev/v3/projects/" + urllib.parse.quote(f"github.com/{repo}", safe=""))
    if not info:
        return [], {}
    rows = [("Stars", _compact(info.get("starsCount", 0))), ("Forks", _compact(info.get("forksCount", 0))),
            ("Open issues", _compact(info.get("openIssuesCount", 0)))]
    if info.get("license"):
        rows.append(("Licence", info["license"]))
    url = f"https://github.com/{repo}"
    return [CardInfo("repo", repo, definition=info.get("description") or "", rows=rows,
                     actions=[Action("Open on GitHub", "open", url)], source="deps.dev", url=url)], {}


PROVIDERS = [
    Provider("weather", frozenset({"lat", "lon"}), weather_week),
    Provider("wikidata", frozenset({"qid"}), wikidata_facts),
    Provider("currency", frozenset({"currency_qid"}), country_currency),
    Provider("github", frozenset({"github_repo"}), github_repo),
    Provider("nearby", frozenset({"lat", "lon"}), nearby),
    Provider("trends", frozenset({"iso2"}), country_trends),
    Provider("holidays", frozenset({"iso2"}), public_holidays),
    Provider("pypi", frozenset({"pypi"}), pypi_package),
    Provider("npm", frozenset({"npm"}), npm_package),
]
