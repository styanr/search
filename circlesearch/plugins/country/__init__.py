import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date

from circlesearch.core.cards import Card
from circlesearch.core.net import get_json, safe
from circlesearch.core.pipeline import enricher


@dataclass
class Series:
    label: str
    points: list[tuple[int, float]]
    format: str


@dataclass(kw_only=True)
class TrendsCard(Card):
    kind = "trends"
    priority = 5

    series: list[Series] = field(default_factory=list)


@dataclass
class Holiday:
    date: date
    name: str
    local: str
    days: int


@dataclass(kw_only=True)
class HolidaysCard(Card):
    kind = "holidays"
    priority = 4
    anchored = True
    accent = "red"

    holidays: list[Holiday] = field(default_factory=list)


@enricher("trends", needs={"iso2"}, order=60)
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
        charts.append(Series("Population", pop, "compact"))
    if len(gdp) > 3:
        charts.append(Series("GDP per person", gdp, "usd"))
    if not charts:
        return [], {}
    return [TrendsCard(title="Trends", series=charts, source="World Bank",
                       url=f"https://data.worldbank.org/country/{iso2.lower()}")], {}


@enricher("holidays", needs={"iso2"}, order=70)
def public_holidays(facts):
    iso2 = facts["iso2"]
    data = get_json(f"https://date.nager.at/api/v3/NextPublicHolidays/{iso2}")
    holidays = []
    for h in (data or [])[:4]:
        d = date.fromisoformat(h["date"])
        holidays.append(Holiday(d, h["name"], "" if h["localName"] == h["name"] else h["localName"],
                                (d - date.today()).days))
    if not holidays:
        return [], {}
    return [HolidaysCard(title="Public holidays", holidays=holidays, source="Nager.Date",
                         url=f"https://date.nager.at/PublicHoliday/Country/{iso2}")], {}
