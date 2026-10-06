import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from circlesearch.core.cards import Card
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer

TZ_ABBR = {
    "UTC": "UTC", "GMT": "UTC", "Z": "UTC",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles", "PT": "America/Los_Angeles",
    "MST": "America/Denver", "MDT": "America/Denver", "MT": "America/Denver",
    "CST": "America/Chicago", "CDT": "America/Chicago", "CT": "America/Chicago",
    "EST": "America/New_York", "EDT": "America/New_York", "ET": "America/New_York",
    "BST": "Europe/London", "CET": "Europe/Berlin", "CEST": "Europe/Berlin",
    "EET": "Europe/Kyiv", "EEST": "Europe/Kyiv", "KYIV": "Europe/Kyiv", "IST": "Asia/Kolkata",
    "JST": "Asia/Tokyo", "KST": "Asia/Seoul", "SGT": "Asia/Singapore",
    "AEST": "Australia/Sydney", "AEDT": "Australia/Sydney",
}
TIME = re.compile(r"^(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<ap>[ap]\.?\s?m\.?)?\s*"
                  r"(?P<tz>[A-Za-z]{1,5}|(?:UTC|GMT)\s?[+-]\s?\d{1,2}(?::?\d{2})?)$", re.I)


@dataclass(kw_only=True)
class TimeCard(Card):
    kind = "time"
    accent = "red"

    here: datetime
    there: datetime
    zone_there: str
    city_here: str
    day: str
    relative: str


def local_zone():
    try:
        name = os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
        return ZoneInfo(name), name.rsplit("/", 1)[-1].replace("_", " ")
    except (IndexError, OSError, KeyError, ValueError):
        return datetime.now().astimezone().tzinfo, "your time"


def _zone(tz):
    t = tz.upper().replace(" ", "")
    m = re.fullmatch(r"(?:UTC|GMT)([+-])(\d{1,2})(?::?(\d{2}))?", t)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3) or 0)))
    return ZoneInfo(TZ_ABBR[t]) if t in TZ_ABBR else None


def relative(delta_days=None, seconds=None):
    if seconds is not None:
        mins = round(seconds / 60)
        if abs(mins) < 60:
            return "now" if mins == 0 else f"in {mins} min" if mins > 0 else f"{-mins} min ago"
        hours = round(seconds / 3600)
        return f"in {hours} h" if hours > 0 else f"{-hours} h ago"
    if delta_days == 0:
        return "Today"
    if delta_days == 1:
        return "Tomorrow"
    if delta_days == -1:
        return "Yesterday"
    return f"In {delta_days} days" if delta_days > 0 else f"{-delta_days} days ago"


@recognizer("time", order=60)
def parse_time(text):
    m = TIME.match(text.strip())
    if not m:
        return None
    h, mi, ap, tz = int(m.group("h")), int(m.group("m") or 0), m.group("ap"), m.group("tz")
    zone = _zone(tz)
    if zone is None or mi > 59 or (ap and not 1 <= h <= 12) or (not ap and h > 23):
        return None
    if ap:
        h = h % 12 + (12 if ap.lower().startswith("p") else 0)
    return h, mi, zone


@resolver("time")
def time_card(route):
    h, mi, zone = route.value
    local, city = local_zone()
    there = datetime.now(zone).replace(hour=h, minute=mi, second=0, microsecond=0)
    here = there.astimezone(local)
    day = (here.date() - datetime.now(local).date()).days
    key = getattr(zone, "key", "") or there.strftime("%Z")
    return TimeCard(title=route.text, here=here, there=there, zone_there=key.rsplit("/", 1)[-1].replace("_", " "),
                    city_here=city, day=relative(day),
                    relative=relative(seconds=(here - datetime.now(local)).total_seconds()))
