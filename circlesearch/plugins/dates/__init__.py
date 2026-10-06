import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, timedelta
from functools import cache

from circlesearch.core.cards import Action, Card
from circlesearch.core.locale import current
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer
from circlesearch.plugins.times import relative

MONTH = r"([^\W\d_]{3,12})\.?"


@dataclass(kw_only=True)
class DateCard(Card):
    kind = "date"
    accent = "red"

    date: date
    relative: str


@cache
def months():
    loc = current()
    names = {"sept": 9}
    for language in dict.fromkeys(["en", loc.language]):
        names.update(loc.month_names(language))
    return names


@recognizer("date", order=50)
def parse_date(text):
    t = text.strip().rstrip(".,").replace(" р.", "").replace(" року", "")
    today = date.today()
    names = months()
    patterns = [
        (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", lambda m: (int(m[1]), int(m[2]), int(m[3]))),
        (r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", lambda m: (int(m[3]), int(m[2]), int(m[1]))),
        (rf"^{MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})?$",
         lambda m: (int(m[3]) if m[3] else None, names.get(m[1].lower()), int(m[2]))),
        (rf"^(\d{{1,2}})(?:st|nd|rd|th|\.)?\s+(?:of\s+)?{MONTH},?\s*(\d{{4}})?$",
         lambda m: (int(m[3]) if m[3] else None, names.get(m[2].lower()), int(m[1]))),
    ]
    for pattern, get in patterns:
        m = re.match(pattern, t, re.I)
        if not m:
            continue
        year, month, day = get(m)
        if not month:
            return None
        try:
            if year is None:
                d = date(today.year, month, day)
                return d if d >= today - timedelta(days=30) else date(today.year + 1, month, day)
            return date(year, month, day)
        except ValueError:
            return None
    return None


@resolver("date")
def date_card(route):
    d = route.value
    end = d + timedelta(days=1)
    gcal = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(
        {"action": "TEMPLATE", "text": "", "dates": f"{d:%Y%m%d}/{end:%Y%m%d}"})
    return DateCard(title=route.text, date=d, relative=relative((d - date.today()).days),
                    actions=[Action("Add to calendar", "open", gcal), Action("Copy date", "copy", d.isoformat())])
