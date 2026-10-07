import hashlib
import re
import urllib.parse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import cache

from circlesearch.core.cards import Action, Card
from circlesearch.core.locale import current
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer
from circlesearch.plugins.times import local_zone, relative

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


WEEKDAYS = {name: i for i, names in enumerate([("monday", "mon"), ("tuesday", "tue", "tues"), ("wednesday", "wed"),
                                                ("thursday", "thu", "thur", "thurs"), ("friday", "fri"),
                                                ("saturday", "sat"), ("sunday", "sun")]) for name in names}
PLATFORMS = re.compile(r"\b(google meet|microsoft teams|ms teams|zoom|teams|meet|skype|discord|slack huddle|slack|webex|"
                       r"jitsi|facetime|phone call|whatsapp|telegram|signal)\b", re.I)
MEETING_URL = re.compile(r"https?://(?:[\w-]+\.)?(?:zoom\.us|meet\.google\.com|teams\.microsoft\.com|"
                         r"teams\.live\.com|meet\.jit\.si|whereby\.com)\S*", re.I)
CLOCK = re.compile(r"(?:\b(?:at|from|@)\s+)?\b(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?"
                   r"(?:\s*(?:-|–|—|to|till|until)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?)?(?!\w)", re.I)
NAMED_TIME = re.compile(r"(\b(?:at|from)\s+|@\s*)?(\b12(?::00)?\s*)?\b(noon|midday|midnight)\b", re.I)
DURATION = re.compile(r"\(?\b(?:for\s+)?(\d+(?:[.,]\d+)?)\s*(h|hr|hrs|hours?|m|min|mins|minutes?)\b\)?", re.I)
RELATIVE = re.compile(r"\b(today|tonight|tomorrow|day after tomorrow|in (\d{1,2}) days?)\b", re.I)
SHORT = re.compile(r"\b(standup|stand-up|sync|call|check-in|1:1|catch-up|catchup)\b", re.I)
TZ_WORDS = {"utc", "gmt", "pst", "pdt", "est", "edt", "cet", "cest", "eet", "eest", "bst", "ist", "jst", "kyiv"}


@dataclass(kw_only=True)
class EventCard(Card):
    kind = "event"
    accent = "red"
    priority = 1

    start: datetime
    end: datetime
    all_day: bool = False
    location: str = ""
    link: str = ""
    relative: str = ""


def _clock(h, m, ap):
    h, m = int(h), int(m or 0)
    if ap:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ap.lower().startswith("p") else 0)
    if h > 23 or m > 59:
        return None
    return h, m


def _find_day(t, today):
    m = RELATIVE.search(t)
    if m:
        word = m.group(1).lower()
        offset = {"today": 0, "tonight": 0, "tomorrow": 1, "day after tomorrow": 2}.get(word)
        if offset is None:
            offset = int(m.group(2))
        return today + timedelta(days=offset), m.span(), word == "tonight"
    m = re.search(r"\b(?:(next|this|on)\s+)(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b\.?", t, re.I)
    if not m:
        m = re.search(r"\b(" + "|".join(sorted(WEEKDAYS, key=len, reverse=True)) + r")\b\.?", t, re.I)
        anchored = False
    else:
        anchored = True
    if m:
        name = (m.group(2) if anchored else m.group(1)).lower()
        ahead = (WEEKDAYS[name] - today.weekday()) % 7
        if anchored and m.group(1).lower() == "next" and ahead == 0:
            ahead = 7
        return today + timedelta(days=ahead), m.span(), "weekday" if not anchored else "anchored"
    names = months()
    month = r"([^\W\d_]{3,12})\.?"
    for pattern, get in ((rf"\b(\d{{1,2}})(?:st|nd|rd|th|\.)?\s+(?:of\s+)?{month}(?:,?\s*(\d{{4}}))?", lambda m: (m[3], m[2], m[1])),
                         (rf"\b{month}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s*(\d{{4}}))?\b", lambda m: (m[3], m[1], m[2])),
                         (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda m: (m[1], m[2], m[3])),
                         (r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", lambda m: (m[3], m[2], m[1]))):
        m = re.search(pattern, t, re.I)
        if not m:
            continue
        year, mon, day = get(m)
        mon = int(mon) if str(mon).isdigit() else names.get(str(mon).lower())
        if not mon:
            continue
        try:
            d = date(int(year), mon, int(day)) if year else date(today.year, mon, int(day))
        except ValueError:
            continue
        if not year and d < today - timedelta(days=30):
            d = d.replace(year=today.year + 1)
        return d, m.span(), "date"
    return None, None, None


def _cut(t, span):
    return t[:span[0]] + " " + t[span[1]:]


@recognizer("event", order=55, max_chars=160, in_spans=False)
def parse_event(text):
    t = " ".join(text.split())
    if len(t.split()) > 16 or len(t.split()) < 2:
        return None
    today = date.today()
    link = MEETING_URL.search(t)
    url = link.group(0) if link else ""
    if link:
        t = _cut(t, link.span())
    day, span, how = _find_day(t, today)
    if span:
        t = _cut(t, span)
    t = NAMED_TIME.sub(lambda m: ("12am" if m.group(3).lower() == "midnight" else "12pm")
                       if day is not None or m.group(1) or m.group(2) else m.group(0), t)
    clock = None
    for m in CLOCK.finditer(t):
        has_colon, has_ap = m.group(2) is not None, m.group(3) is not None
        if not (has_colon or has_ap or re.match(r"\s*(?:at|from|@)\s", t[m.start():m.end()], re.I)):
            continue
        start = _clock(m.group(1), m.group(2), m.group(3))
        if start is None:
            continue
        end = _clock(m.group(4), m.group(5), m.group(6) or m.group(3)) if m.group(4) else None
        clock = (start, end)
        t = _cut(t, m.span())
        break
    duration = None
    m = DURATION.search(t)
    if m and clock:
        amount = float(m.group(1).replace(",", "."))
        duration = timedelta(hours=amount) if m.group(2).lower().startswith("h") else timedelta(minutes=amount)
        t = _cut(t, m.span())
    if clock is None and how not in ("date", "anchored", True, False):
        return None
    location = url
    m = PLATFORMS.search(t)
    if m:
        location = m.group(1).title().replace("Ms ", "Microsoft ")
        t = _cut(t, m.span())
    else:
        m = re.search(r"(?:\b(?:at|in)\s+|@\s*)((?:[A-Z0-9][\w'’.-]*)(?:\s+[A-Z0-9][\w'’.-]*){0,3})\s*$", t.strip())
        if m:
            location = m.group(1)
            t = t.strip()[:m.start()]
    title = re.sub(r"\s+", " ", t)
    title = re.sub(r"^[\s,;:–—@-]+|[\s,;:–—@(-]+$", "", title)
    title = re.sub(r"\b(on|at|from|for)\s*$", "", title, flags=re.I).strip(" ,;-–")
    if len(re.findall(r"[^\W\d_]{2,}", title)) < 1 or title.lower() in TZ_WORDS:
        return None
    if day is None:
        day = today
        if clock and datetime.combine(today, datetime.min.time()).replace(hour=clock[0][0], minute=clock[0][1]) < datetime.now():
            day = today + timedelta(days=1)
    if how is True and clock and clock[0] == (0, 0):
        day += timedelta(days=1)
    if clock is None:
        if how is True:
            clock = ((20, 0), None)
        else:
            start = datetime.combine(day, datetime.min.time())
            return {"title": title, "start": start, "end": start + timedelta(days=1), "all_day": True,
                    "location": location, "link": url}
    (h, mi), end_clock = clock
    start = datetime.combine(day, datetime.min.time()).replace(hour=h, minute=mi)
    if end_clock:
        end = start.replace(hour=end_clock[0], minute=end_clock[1])
        if end <= start:
            end += timedelta(days=1)
    else:
        end = start + (duration or timedelta(minutes=30 if SHORT.search(title) else 60))
    return {"title": title[:1].upper() + title[1:], "start": start, "end": end, "all_day": False,
            "location": location, "link": url}


def ics_escape(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics(event):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    uid = hashlib.sha1(f"{event['title']}{event['start']}".encode()).hexdigest()[:16] + "@circle-search"
    if event["all_day"]:
        when = [f"DTSTART;VALUE=DATE:{event['start']:%Y%m%d}", f"DTEND;VALUE=DATE:{event['end']:%Y%m%d}"]
    else:
        when = [f"DTSTART:{event['start'].astimezone(timezone.utc):%Y%m%dT%H%M%SZ}",
                f"DTEND:{event['end'].astimezone(timezone.utc):%Y%m%dT%H%M%SZ}"]
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//circle-search//EN", "BEGIN:VEVENT", f"UID:{uid}",
             f"DTSTAMP:{stamp}", *when, f"SUMMARY:{ics_escape(event['title'])}"]
    if event["location"]:
        lines.append(f"LOCATION:{ics_escape(event['location'])}")
    if event["link"]:
        lines.append(f"URL:{event['link']}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


@resolver("event")
def event_card(route):
    e = route.value
    if e["all_day"]:
        dates = f"{e['start']:%Y%m%d}/{e['end']:%Y%m%d}"
        rel = relative((e["start"].date() - date.today()).days)
    else:
        dates = f"{e['start']:%Y%m%dT%H%M%S}/{e['end']:%Y%m%dT%H%M%S}"
        days = (e["start"].date() - date.today()).days
        rel = relative(seconds=(e["start"] - datetime.now()).total_seconds()) if days == 0 else relative(days)
    params = {"action": "TEMPLATE", "text": e["title"], "dates": dates}
    zone = local_zone()[0]
    if getattr(zone, "key", None):
        params["ctz"] = zone.key
    if e["location"] or e["link"]:
        params["location"] = e["location"] or e["link"]
    if e["link"]:
        params["details"] = e["link"]
    gcal = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)
    name = re.sub(r"\W+", "-", e["title"]).strip("-")[:40] or "event"
    actions = [Action("Google Calendar", "open", gcal), Action("Save .ics", "save", ics(e), filename=f"{name}.ics")]
    if e["link"]:
        actions.append(Action("Join", "open", e["link"]))
    return EventCard(title=e["title"], start=e["start"], end=e["end"], all_day=e["all_day"], location=e["location"],
                     link=e["link"], relative=rel, actions=actions)
