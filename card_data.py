import ast
import json
import unicodedata
import math
import operator
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from PyQt6.QtCore import QLocale, QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter

from locale_profile import PROFILE

USER_AGENT = "circle-search/0.1 (personal desktop prototype)"
CONTACT = os.environ.get("CIRCLE_SEARCH_CONTACT", "").strip()
CONTACT_USER_AGENT = (f"circle-search/0.1 (personal desktop prototype; {CONTACT})" if CONTACT else
                      "circle-search/0.1 (personal desktop prototype; https://www.mediawiki.org/wiki/API:Etiquette)")
CONTACT_HOSTS = ("wikipedia.org", "wiktionary.org", "wikidata.org", "wikivoyage.org", "wikimedia.org",
                 "openstreetmap.org", "musicbrainz.org", "listenbrainz.org")


def user_agent(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    return CONTACT_USER_AGENT if any(host == h or host.endswith("." + h) for h in CONTACT_HOSTS) else USER_AGENT
TIMEOUT = 2.5
OPTIONAL_TIMEOUT = 1.2
MAX_STRUCTURED_CHARS = 90


@dataclass
class Action:
    label: str
    kind: str
    payload: str


@dataclass
class CardInfo:
    kind: str
    title: str
    pronunciation: str = ""
    part_of_speech: str = ""
    definition: str = ""
    description: str = ""
    chips: list = field(default_factory=list)
    value: str = ""
    rows: list = field(default_factory=list)
    translation: str = ""
    translation_label: str = ""
    alternatives: list = field(default_factory=list)
    swatch: str = ""
    map_image: QImage | None = None
    map_attribution: str = ""
    actions: list = field(default_factory=list)
    chart: dict | None = None
    items: list = field(default_factory=list)
    source: str = ""
    url: str = ""
    facts: dict = field(default_factory=dict)
    image: QImage | None = None
    image_shape: str = ""
    now: dict = field(default_factory=dict)
    is_day: bool = True
    zone_there: str = ""
    city_here: str = ""
    date_value: date | None = None


def get_json(url, headers=None, timeout=TIMEOUT, retry=True):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(url), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if retry and e.code in (502, 503, 504):
            time.sleep(0.15)
            return get_json(url, headers, timeout, retry=False)
        raise


def get_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(url)})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def safe(fn, *args):
    try:
        return fn(*args)
    except (OSError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError, OverflowError) as e:
        print(f"context: {fn.__name__} failed: {e}", file=sys.stderr)
        return None


def parse_number(s):
    s = s.replace(" ", " ").replace("\xa0", " ").replace("'", "").replace(" ", "")
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


TLDS = "com|org|net|io|dev|app|ai|ua|eu|de|uk|pl|fr|gov|edu|co|me|info|xyz|tech|site|page"
LINK = re.compile(rf"^(?:https?://\S+|www\.[\w-]+(?:\.[\w-]+)+\S*|[\w-]+(?:\.[\w-]+)*\.(?:{TLDS})(?:/\S*)?)$", re.I)
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")


def parse_link(text):
    t = text.strip().rstrip(".,;)")
    return t if LINK.match(t) and " " not in t else None


def card_link(text):
    t = parse_link(text)
    url = t if re.match(r"^https?://", t, re.I) else "https://" + t
    parts = urllib.parse.urlsplit(url)
    path = (parts.path + ("?" + parts.query if parts.query else "")).strip("/")
    return CardInfo("link", parts.netloc, definition=path,
                    actions=[Action("Open", "open", url), Action("Copy link", "copy", url)])


def parse_email(text):
    t = text.strip().strip("<>").rstrip(".,;")
    return t if EMAIL.match(t) else None


def card_email(text):
    t = parse_email(text)
    return CardInfo("email", t, actions=[Action("Write email", "open", "mailto:" + t),
                                         Action("Copy", "copy", t)])


UA_OPERATORS = {**dict.fromkeys(["50", "66", "95", "99", "75"], "Vodafone"),
                **dict.fromkeys(["67", "68", "96", "97", "98", "77"], "Kyivstar"),
                **dict.fromkeys(["63", "73", "93"], "lifecell")}
PHONE = re.compile(r"^\+?[\d\s().-]{9,20}$")


def parse_phone(text):
    t = text.strip()
    if not PHONE.match(t) or re.match(r"^\d{4}-\d{2}-\d{2}$", t):
        return None
    digits = re.sub(r"\D", "", t)
    if t.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10 and digits.startswith("0") and PROFILE.country == "UA":
        return "+38" + digits
    if len(digits) == 12 and digits.startswith("380"):
        return "+" + digits
    return None


def card_phone(text):
    number = parse_phone(text)
    chips = []
    if number.startswith("+380") and len(number) == 13:
        shown = f"+380 {number[4:6]} {number[6:9]} {number[9:11]} {number[11:]}"
        if number[4:6] in UA_OPERATORS:
            chips.append(UA_OPERATORS[number[4:6]])
        chips.append("Ukraine")
    else:
        shown = number
    return CardInfo("phone", shown, chips=chips,
                    actions=[Action("Call", "open", "tel:" + number), Action("Copy", "copy", number)])


TRACKING_S10 = re.compile(r"^[A-Z]{2}\d{9}[A-Z]{2}$")


def parse_tracking(text):
    t = re.sub(r"\s", "", text.strip()).upper()
    if re.fullmatch(r"(20|59)\d{12}", t):
        return ("Nova Poshta", t)
    if TRACKING_S10.match(t):
        return ("Ukrposhta" if t.endswith("UA") else "International mail", t)
    return None


def card_tracking(text):
    carrier, number = parse_tracking(text)
    url = {"Nova Poshta": f"https://novaposhta.ua/tracking/{number}/",
           "Ukrposhta": f"https://track.ukrposhta.ua/tracking_UA.html?barcode={number}"
           }.get(carrier, f"https://parcelsapp.com/en/tracking/{number}")
    return CardInfo("tracking", number, description=f"{carrier} parcel",
                    actions=[Action("Track parcel", "open", url), Action("Copy number", "copy", number)])


HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$", re.I)
FUNC = re.compile(r"^(rgba?|hsla?)\(\s*([^)]*)\)$", re.I)


def parse_color(text):
    t = text.strip().rstrip(";,")
    m = HEX.match(t)
    if m and (t.startswith("#") or len(m.group(1)) in (6, 8) and re.search(r"\d", t) and re.search(r"[a-f]", t, re.I)):
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return r, g, b, a
    m = FUNC.match(t)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(2)) if p]
    if len(parts) < 3:
        return None

    def num(p, scale):
        return float(p[:-1]) / 100 * scale if p.endswith("%") else float(p.rstrip("deg"))
    a = num(parts[3], 1.0) if len(parts) > 3 else 1.0
    if m.group(1).lower().startswith("rgb"):
        r, g, b = (round(min(255, max(0, num(p, 255)))) for p in parts[:3])
    else:
        c = QColor.fromHslF((num(parts[0], 360) % 360) / 360, num(parts[1], 1.0) if parts[1].endswith("%") else num(parts[1], 1.0) / 100,
                            num(parts[2], 1.0) if parts[2].endswith("%") else num(parts[2], 1.0) / 100)
        r, g, b = c.red(), c.green(), c.blue()
    return r, g, b, a


def _luminance(r, g, b):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _oklch(r, g, b):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    A = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    C = math.hypot(A, B)
    H = math.degrees(math.atan2(B, A)) % 360 if C > 1e-4 else 0
    return L, C, H


def card_color(text):
    r, g, b, a = parse_color(text)
    hex_ = f"#{r:02X}{g:02X}{b:02X}" + (f"{round(a * 255):02X}" if a < 1 else "")
    c = QColor(r, g, b)
    L, C, H = _oklch(r, g, b)
    lum = _luminance(r, g, b)
    on_white, on_black = (1.05) / (lum + 0.05), (lum + 0.05) / 0.05
    better = ("white", on_white) if on_white >= on_black else ("black", on_black)
    grade = "AAA" if better[1] >= 7 else "AA" if better[1] >= 4.5 else "AA large" if better[1] >= 3 else "low"
    alpha = f" / {fmt(a, 2)}" if a < 1 else ""
    rows = [("HEX", hex_),
            ("RGB", f"rgb({r} {g} {b}{alpha})"),
            ("HSL", f"hsl({round(c.hslHueF() * 360) if c.hslHueF() >= 0 else 0} "
                    f"{round(c.hslSaturationF() * 100)}% {round(c.lightnessF() * 100)}%{alpha})"),
            ("OKLCH", f"oklch({L * 100:.1f}% {C:.3f} {H:.1f}{alpha})")]
    return CardInfo("color", hex_, swatch=hex_, rows=rows,
                    chips=[f"{better[1]:.1f}:1 on {better[0]} ({grade})"])


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


def card_time(text):
    h, mi, zone = parse_time(text)
    local, city = local_zone()
    there = datetime.now(zone).replace(hour=h, minute=mi, second=0, microsecond=0)
    here = there.astimezone(local)
    day = (here.date() - datetime.now(local).date()).days
    key = getattr(zone, "key", "") or there.strftime("%Z")
    return CardInfo("time", text.strip(), value=here.strftime("%H:%M"),
                    zone_there=key.rsplit("/", 1)[-1].replace("_", " "), city_here=city,
                    chips=[f"{relative(day)} in {city}", relative(seconds=(here - datetime.now(local)).total_seconds())],
                    rows=[("Their time", there.strftime("%H:%M %Z")), ("Your time", here.strftime("%H:%M %Z"))])


def _month_names():
    names = {"sept": 9}
    for loc in {QLocale(QLocale.Language.English), QLocale(PROFILE.language)}:
        for i in range(1, 13):
            for fmt_ in (QLocale.FormatType.LongFormat, QLocale.FormatType.ShortFormat):
                for name in (loc.monthName(i, fmt_), loc.standaloneMonthName(i, fmt_)):
                    if name:
                        names[name.lower().rstrip(".")] = i
    return names


MONTHS = _month_names()
MONTH = r"([^\W\d_]{3,12})\.?"


def parse_date(text):
    t = text.strip().rstrip(".,").replace(" р.", "").replace(" року", "")
    today = date.today()
    patterns = [
        (r"^(\d{4})-(\d{1,2})-(\d{1,2})$", lambda m: (int(m[1]), int(m[2]), int(m[3]))),
        (r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", lambda m: (int(m[3]), int(m[2]), int(m[1]))),
        (rf"^{MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s*(\d{{4}})?$",
         lambda m: (int(m[3]) if m[3] else None, MONTHS.get(m[1].lower()), int(m[2]))),
        (rf"^(\d{{1,2}})(?:st|nd|rd|th|\.)?\s+(?:of\s+)?{MONTH},?\s*(\d{{4}})?$",
         lambda m: (int(m[3]) if m[3] else None, MONTHS.get(m[2].lower()), int(m[1]))),
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


def card_date(text):
    d = parse_date(text)
    days = (d - date.today()).days
    end = d + timedelta(days=1)
    gcal = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(
        {"action": "TEMPLATE", "text": "", "dates": f"{d:%Y%m%d}/{end:%Y%m%d}"})
    return CardInfo("date", text.strip(), value=d.strftime("%A"), date_value=d,
                    chips=[relative(days), f"Week {d.isocalendar()[1]}"],
                    rows=[("Date", d.strftime("%-d %B %Y")), ("ISO", d.isoformat())],
                    actions=[Action("Add to calendar", "open", gcal)])


SYMBOLS = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "₴": "UAH", "грн": "UAH", "¥": "JPY",
           "zł": "PLN", "kč": "CZK", "chf": "CHF", "c$": "CAD", "ca$": "CAD", "a$": "AUD", "₺": "TRY", "₾": "GEL"}
CODES = {"USD", "EUR", "GBP", "UAH", "PLN", "CHF", "CZK", "JPY", "CNY", "CAD", "AUD", "SEK", "NOK",
         "DKK", "HUF", "RON", "TRY", "GEL", "ILS", "MDL", "KZT", "BGN", "INR", "KRW", "SGD", "HKD"}
SYMBOL_OF = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "UAH": "₴", "PLN": "zł", "CHF": "CHF", "CZK": "Kč",
             "TRY": "₺", "GEL": "₾", "INR": "₹", "KRW": "₩", "CNY": "¥"}


_currency_names = {}


def currency_name(code):
    if not _currency_names:
        for loc in QLocale.matchingLocales(QLocale.Language.AnyLanguage, QLocale.Script.AnyScript, QLocale.Country.AnyCountry):
            iso = loc.currencySymbol(QLocale.CurrencySymbolFormat.CurrencyIsoCode)
            if iso and iso not in _currency_names:
                name = QLocale(QLocale.Language.English, loc.territory()).currencySymbol(
                    QLocale.CurrencySymbolFormat.CurrencyDisplayName)
                if name:
                    _currency_names[iso] = name[:1].upper() + name[1:]
    return _currency_names.get(code, code)
MONEY = re.compile(r"^(?P<pre>[$€£₴¥₺₾]|US\$|CA\$|C\$|A\$|[A-Za-z]{3})?\s?"
                   r"(?P<num>\d{1,3}(?:[\s.,' \xa0]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s?"
                   r"(?P<k>[kKmM](?![a-z]))?\s?(?P<post>[$€£₴¥₺₾]|zł|Kč|грн\.?|[A-Za-z]{3})?$")
_rates = {}


def _currency(token):
    if not token:
        return None
    t = token.rstrip(".")
    return SYMBOLS.get(t.lower()) or SYMBOLS.get(t) or (t.upper() if t.upper() in CODES else None)


def parse_money(text):
    m = MONEY.match(text.strip())
    if not m or bool(m.group("pre")) == bool(m.group("post")):
        return None
    code = _currency(m.group("pre") or m.group("post"))
    if not code:
        return None
    amount = parse_number(m.group("num")) * {"k": 1e3, "m": 1e6}.get((m.group("k") or "").lower(), 1)
    return amount, code


FRANKFURTER = "https://api.frankfurter.dev/v1/"
CURRENCY_API = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/"


def home_rates():
    if _rates:
        return _rates
    home = PROFILE.currency
    if home == "UAH":
        data = get_json("https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json")
        _rates.update({r["cc"]: r["rate"] for r in data})
        _rates.update(_date=data[0].get("exchangedate", "") if data else "", _source="National Bank of Ukraine",
                      _url="https://bank.gov.ua/en/markets/exchangerates", _history="nbu")
    else:
        data = get_json(f"{FRANKFURTER}latest?base={home}")
        if data and data.get("rates"):
            _rates.update({c: 1 / r for c, r in data["rates"].items() if r})
            _rates.update(_date=data.get("date", ""), _source="European Central Bank",
                          _url="https://www.frankfurter.app", _history="frankfurter")
        else:
            data = get_json(f"{CURRENCY_API}{home.lower()}.json")
            table = (data or {}).get(home.lower(), {})
            _rates.update({c.upper(): 1 / r for c, r in table.items() if r})
            _rates.update(_date=(data or {}).get("date", ""), _source="currency-api",
                          _url="https://github.com/fawazahmed0/exchange-api", _history=None)
    _rates[home] = 1.0
    return _rates


def rate_of(code):
    rates = home_rates()
    if code not in rates and not rates.get("_extended"):
        rates["_extended"] = True
        data = safe(get_json, f"{CURRENCY_API}{PROFILE.currency.lower()}.json")
        for c, r in ((data or {}).get(PROFILE.currency.lower(), {}) or {}).items():
            if r and c.upper() not in rates:
                rates[c.upper()] = 1 / r
    return rates.get(code)


def rate_history(code, days):
    rates = home_rates()
    end = date.today()
    start = end - timedelta(days=days)
    if rates.get("_history") == "nbu":
        data = get_json("https://bank.gov.ua/NBU_Exchange/exchange_site?" + urllib.parse.urlencode(
            {"start": f"{start:%Y%m%d}", "end": f"{end:%Y%m%d}", "valcode": code.lower(), "sort": "exchangedate",
             "order": "asc", "json": ""}), timeout=OPTIONAL_TIMEOUT)
        return [(datetime.strptime(r["exchangedate"], "%d.%m.%Y").strftime("%-d %b"), r["rate_per_unit"]) for r in data]
    if rates.get("_history") == "frankfurter":
        data = get_json(f"{FRANKFURTER}{start:%Y-%m-%d}..{end:%Y-%m-%d}?base={code}&symbols={PROFILE.currency}",
                        timeout=OPTIONAL_TIMEOUT)
        series = (data or {}).get("rates", {})
        return [(date.fromisoformat(d).strftime("%-d %b"), v[PROFILE.currency]) for d, v in sorted(series.items())
                if PROFILE.currency in v]
    return None


def money_str(amount, code):
    if code == PROFILE.currency:
        return PROFILE.money.toCurrencyString(amount, PROFILE.money.currencySymbol())
    return PROFILE.money.toCurrencyString(amount, SYMBOL_OF.get(code, code))


def card_money(text):
    amount, code = parse_money(text)
    rates = home_rates()
    home = PROFILE.currency
    if rate_of(code) is None:
        return None
    worth = amount * rates[code]
    if code == home:
        others = [c for c in ("USD", "EUR") if c != home and c in rates]
        value = money_str(worth / rates[others[0]], others[0]) if others else money_str(worth, home)
        others = others[1:]
    else:
        value = money_str(worth, home)
        others = [c for c in ("USD", "EUR") if c not in (code, home) and c in rates]
    return CardInfo("money", text.strip(), value=value,
                    rows=[(currency_name(c), money_str(worth / rates[c], c)) for c in others],
                    chips=[f"1 {code} = {money_str(rates[code], home)}"] if code != home else [],
                    source=f"{rates['_source']}, {rates['_date']}", url=rates["_url"])


UNITS = [
    (r"mi|miles?", "km", 1.609344), (r"ft|feet|foot", "m", 0.3048), (r"in|inch(?:es)?|″|\"", "cm", 2.54),
    (r"yd|yards?", "m", 0.9144), (r"lbs?|pounds?", "kg", 0.45359237), (r"oz|ounces?", "g", 28.349523125),
    (r"fl\.?\s?oz", "ml", 29.5735295625), (r"gal(?:lons?)?", "L", 3.785411784), (r"qt|quarts?", "L", 0.946352946),
    (r"cups?", "ml", 240.0), (r"mph", "km/h", 1.609344), (r"sq\.?\s?ft|ft²|square\s+feet", "m²", 0.09290304),
    (r"acres?", "ha", 0.40468564224),
    (r"°\s?F|degrees?\s+fahrenheit|fahrenheit", "°C", lambda f: (f - 32) * 5 / 9),
]
METRIC_UNITS = [
    (r"km|kilomet(?:er|re)s?", "mi", 0.621371), (r"m|met(?:er|re)s?", "ft", 3.28084), (r"cm|centimet(?:er|re)s?", "in", 0.393701),
    (r"kg|kilos?|kilograms?", "lb", 2.20462), (r"g|grams?", "oz", 0.035274), (r"l|litres?|liters?", "gal", 0.264172),
    (r"ml|millilit(?:er|re)s?", "fl oz", 0.033814), (r"km/h|kph", "mph", 0.621371), (r"m²|sq\.?\s?m", "sq ft", 10.7639),
    (r"ha|hectares?", "acres", 2.47105), (r"°\s?C|degrees?\s+celsius|celsius", "°F", lambda c: c * 9 / 5 + 32),
]
QUANTITY = re.compile(r"^(?P<num>-?\d[\d,]*(?:\.\d+)?)\s?(?P<unit>.+)$", re.I)
FEET_INCHES = re.compile(r"^(\d+)\s?(?:'|′|ft|feet)\s?(\d+(?:\.\d+)?)\s?(?:\"|″|in|inches)?$", re.I)


def parse_quantity(text):
    t = text.strip()
    m = FEET_INCHES.match(t)
    if m and PROFILE.metric:
        return ("height", float(m.group(1)) * 30.48 + float(m.group(2)) * 2.54, "cm")
    m = QUANTITY.match(t)
    if not m:
        return None
    for pattern, unit, conv in (UNITS if PROFILE.metric else METRIC_UNITS):
        if re.fullmatch(pattern, m.group("unit").strip(), re.I):
            n = parse_number(m.group("num")) if "," in m.group("num") else float(m.group("num"))
            return ("unit", conv(n) if callable(conv) else n * conv, unit)
    return None


def card_quantity(text):
    _, value, unit = parse_quantity(text)
    shown = f"{fmt(value, 1 if unit in ('°C', '°F', 'cm', 'in') else 2)} {unit}"
    rows = []
    if unit == "cm" and value >= 100:
        rows.append(("Metres", f"{fmt(value / 100, 2)} m"))
    if unit == "km":
        rows.append(("Metres", f"{fmt(value * 1000, 0)} m"))
    return CardInfo("quantity", text.strip(), value=shown, rows=rows)


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
MATH_CHARS = re.compile(r"^[\d\s.,+\-*/×÷^()%]+$")


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return -_eval(node.operand) if isinstance(node.op, ast.USub) else _eval(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return OPS[type(node.op)](left, right)
    raise ValueError("not arithmetic")


def parse_math(text):
    t = text.strip().rstrip("=").strip()
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s?%\s+of\s+(\d[\d,]*(?:\.\d+)?)", t, re.I)
    if m:
        return float(m.group(1).replace(",", ".")) / 100 * parse_number(m.group(2))
    if not MATH_CHARS.match(t) or not re.search(r"\d\s*[-+*/×÷^%]\s*[\d(]", t) or len(re.findall(r"\d+", t)) < 2:
        return None
    if re.fullmatch(r"[\d\s()+-]{9,}", t) or re.fullmatch(r"\d{1,4}([./-])\d{1,2}\1\d{1,4}", t):
        return None
    expr = t.replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    expr = re.sub(r"(\d+(?:\.\d+)?)\s?%", r"(\1/100)", expr)
    try:
        return float(_eval(ast.parse(expr, mode="eval")))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None


def card_math(text):
    result = parse_math(text)
    shown = fmt(result, 6) if abs(result) < 1e15 else f"{result:.6g}"
    return CardInfo("math", text.strip(), value=shown)


ADDRESS = re.compile(
    r"\b(\d+[a-zа-я]?\s+[\w' .-]+\s(street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|way|place|pl|square|sq)\b"
    r"|(вул\.?|вулиця|просп\.?|проспект|пл\.?|площа|бульв\.?|бульвар|пров\.?|провулок|узвіз)\s+[\w'’ .-]+,?\s*\d+"
    r"|\b\d{5}(-\d{4})?\b.*\b(USA|Ukraine|Україна|Deutschland|Germany|Poland|Polska)\b)", re.I)


def parse_address(text):
    t = " ".join(text.split())
    return t if 8 <= len(t) <= 160 and ADDRESS.search(t) else None


WEATHER = [(0, "clear"), (1, "mostly clear"), (2, "partly cloudy"), (3, "cloudy"), (48, "fog"), (57, "drizzle"),
           (67, "rain"), (77, "snow"), (82, "showers"), (86, "snow showers"), (99, "thunderstorm")]


def weather(lat, lon):
    data = get_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
        {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "current": "temperature_2m,weather_code"}),
        timeout=OPTIONAL_TIMEOUT)
    cur = data["current"]
    words = next(w for code, w in WEATHER if cur["weather_code"] <= code)
    return f"{round(cur['temperature_2m'])}°, {words}"


MAP_W, MAP_H, TILE = 416, 176, 256


MAP_TINT = QColor("#9DB4E0")


def dark_tile(data):
    tile = QImage()
    tile.loadFromData(data)
    tile = tile.convertToFormat(QImage.Format.Format_Grayscale8)
    tile.invertPixels()
    tile = tile.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(tile)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Multiply)
    p.fillRect(tile.rect(), MAP_TINT)
    p.end()
    return tile


def map_image(lat, lon, zoom):
    n = 2 ** zoom
    cx = (lon + 180) / 360 * n * TILE
    lat_r = math.radians(lat)
    cy = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n * TILE
    x0, y0 = cx - MAP_W / 2, cy - MAP_H / 2
    tiles = [(tx, ty) for tx in range(int(x0 // TILE), int((x0 + MAP_W) // TILE) + 1)
             for ty in range(int(y0 // TILE), int((y0 + MAP_H) // TILE) + 1) if 0 <= ty < n]

    def fetch(t):
        tx, ty = t
        return t, dark_tile(get_bytes(f"https://tile.openstreetmap.org/{zoom}/{tx % n}/{ty}.png"))

    img = QImage(MAP_W, MAP_H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#1B1C21"))
    p = QPainter(img)
    with ThreadPoolExecutor(6) as pool:
        for (tx, ty), tile in pool.map(fetch, tiles):
            p.drawImage(QPointF(tx * TILE - x0, ty * TILE - y0), tile)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QPointF(MAP_W / 2, MAP_H / 2)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(168, 199, 250, 60))
    p.drawEllipse(c, 18, 18)
    p.setBrush(QColor("white"))
    p.drawEllipse(c, 8, 8)
    p.setBrush(QColor("#4285F4"))
    p.drawEllipse(c, 5.5, 5.5)
    p.end()
    return img


def zoom_for(description):
    full = (description or "").lower()
    head = re.split(r"\s+(?:in|of|on|near)\s+|,", full, maxsplit=1)[0]
    return _zoom_words(head) or _zoom_words(full) or 15


def _zoom_words(d):
    for words, zoom in ((("country", "sovereign"), 5), (("state of", "province", "oblast", "region", "island"), 7),
                        (("river", "lake", "mountain", "national park", "sea"), 9),
                        (("city", "capital", "town", "municipality", "village", "commune"), 11),
                        (("district", "neighbourhood", "neighborhood", "suburb"), 13)):
        if any(w in d for w in words):
            return zoom
    return None


def place_actions(lat, lon, query, copy_text):
    q = query or f"{lat},{lon}"
    return [Action("Open in Maps", "open", "https://www.google.com/maps/search/?" + urllib.parse.urlencode({"api": 1, "query": q})),
            Action("Directions", "open", "https://www.google.com/maps/dir/?" + urllib.parse.urlencode({"api": 1, "destination": f"{lat},{lon}"})),
            Action("Copy", "copy", copy_text)]


def fetch_image(url):
    img = QImage()
    img.loadFromData(get_bytes(url))
    return img if not img.isNull() else None


def image_shape_for(description, zoom=15):
    d = (description or "").lower()
    if zoom <= 6:
        return "squircle"
    if any(w in d for w in ("software", "library", "framework", "programming language", "company", "organization",
                            "organisation", "brand", "website", "service")):
        return "logo_squircle"
    return "cookie9"


def place_card(title, lat, lon, zoom, description="", definition="", source="", url="", query="", copy_text="",
               facts=None, image_url=None):
    with ThreadPoolExecutor(2) as pool:
        map_f = pool.submit(safe, map_image, lat, lon, zoom)
        img_f = pool.submit(safe, fetch_image, image_url) if image_url else None
        img, picture = map_f.result(), img_f.result() if img_f else None
    return CardInfo("place", title, description=description, definition=definition,
                    image=picture, image_shape=image_shape_for(description, zoom),
                    map_image=img, map_attribution="© OpenStreetMap contributors",
                    actions=place_actions(lat, lon, query, copy_text or f"{lat:.5f}, {lon:.5f}"),
                    source=source, url=url,
                    facts={"lat": lat, "lon": lon, "title": title, "zoom": zoom, **(facts or {})})


def card_address(text):
    q = parse_address(text)
    data = get_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 1, "accept-language": "uk,en"}))
    if not data:
        return None
    hit = data[0]
    parts = [s.strip() for s in hit["display_name"].split(",")]
    title = ", ".join(parts[:2]) if parts[0][:1].isdigit() else parts[0]
    zoom = {"building": 17, "house": 17, "road": 16, "street": 16, "suburb": 13, "city": 11,
            "town": 12, "village": 13}.get(hit.get("addresstype"), 16)
    return place_card(title, float(hit["lat"]), float(hit["lon"]), zoom,
                      description=", ".join(parts[2:4]), source="OpenStreetMap",
                      url=f"https://www.openstreetmap.org/?mlat={hit['lat']}&mlon={hit['lon']}#map={zoom}/{hit['lat']}/{hit['lon']}",
                      query=q, copy_text=hit["display_name"])


def find_structured(text, max_words=12):
    words = tidy(text).split()
    if len(words) > max_words:
        return None
    for length in range(len(words) - 1, 0, -1):
        for start in range(len(words) - length + 1):
            span = tidy(" ".join(words[start:start + length]))
            kind = recognise(span)
            if kind and kind != "address":
                return kind, span
    return None


STRUCTURED = [
    ("link", parse_link, card_link),
    ("email", parse_email, card_email),
    ("color", parse_color, card_color),
    ("tracking", parse_tracking, card_tracking),
    ("date", parse_date, card_date),
    ("time", parse_time, card_time),
    ("money", parse_money, card_money),
    ("quantity", parse_quantity, card_quantity),
    ("phone", parse_phone, card_phone),
    ("math", parse_math, card_math),
    ("address", parse_address, card_address),
]
BUILDERS = {kind: build for kind, _, build in STRUCTURED}


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


def recognise(text):
    t = tidy(text)
    if not t or len(t) > MAX_STRUCTURED_CHARS and not parse_address(t):
        return None
    for kind, parse, _ in STRUCTURED:
        try:
            if parse(t) is not None:
                return kind
        except (ValueError, OverflowError, TypeError):
            continue
    return None
