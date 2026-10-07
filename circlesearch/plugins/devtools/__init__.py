import base64
import binascii
import json
import re
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from circlesearch.core import layout
from circlesearch.core.cards import Action, Card, TextCard
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer
from circlesearch.plugins.devtools import errors as E

UNIX_MIN, UNIX_MAX = 631152000, 4102444800
TICKS_EPOCH = 621355968000000000
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:[.,]\d{1,9})?)?\s?(?:Z|[+-]\d{2}:?\d{2}|UTC)?$", re.I)
RFC2822 = re.compile(r"^(?:[A-Z][a-z]{2},\s)?\d{1,2}\s[A-Z][a-z]{2}\s\d{4}\s\d{2}:\d{2}(?::\d{2})?\s(?:GMT|UTC|[+-]\d{4})$")
JWT = re.compile(r"^(eyJ[\w-]+)\.(eyJ[\w-]+)\.([\w-]*)$")
UUID = re.compile(r"^\{?[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\}?$", re.I)
B64 = re.compile(r"^[A-Za-z0-9+/_-]{8,}={0,2}$")
HEXBYTES = re.compile(r"^(?:0x)?(?:[0-9a-f]{2}[\s:]?){4,}$", re.I)
CRON_FIELD = re.compile(r"^(?:\*|\?|[0-9A-Z]+(?:-[0-9A-Z]+)?)(?:/\d+)?(?:,(?:\*|[0-9A-Z]+(?:-[0-9A-Z]+)?)(?:/\d+)?)*$", re.I)
MACROS = {"@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *", "@weekly": "0 0 * * 0",
          "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *"}
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]
DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
CLAIM_NAMES = {"sub": "Subject", "iss": "Issuer", "aud": "Audience", "exp": "Expires", "iat": "Issued",
               "nbf": "Not before", "jti": "Token ID", "scope": "Scope", "scp": "Scope", "name": "Name",
               "email": "Email", "preferred_username": "Username", "azp": "Client", "client_id": "Client",
               "roles": "Roles", "tid": "Tenant", "sid": "Session"}


@dataclass(kw_only=True)
class CodeCard(TextCard):
    kind = "code"
    title_role = "query"

    code: str = ""
    language: str = ""
    copy_label: str = "Copy"


@dataclass(kw_only=True)
class JwtCard(Card):
    kind = "jwt"
    accent = "amber"

    header: dict = field(default_factory=dict)
    claims: dict = field(default_factory=dict)
    status: str = ""
    state: str = "none"
    progress: float | None = None
    chips: list[str] = field(default_factory=list)
    rows: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Run:
    when: datetime
    relative: str


@dataclass(kw_only=True)
class CronCard(Card):
    kind = "cron"
    accent = "red"

    expression: str
    description: str
    fields: list[tuple[str, str]] = field(default_factory=list)
    runs: list[Run] = field(default_factory=list)


@dataclass
class ErrorEntry:
    code: str
    title: str
    family: str
    explanation: str
    badge: str = ""


@dataclass(kw_only=True)
class ErrorCard(Card):
    kind = "error"
    accent = "red"
    priority = 2

    entries: list[ErrorEntry] = field(default_factory=list)
    code: str = ""


def humanize(seconds):
    future = seconds > 0
    s = abs(seconds)
    for size, unit in ((365.25 * 86400, "year"), (30.44 * 86400, "month"), (7 * 86400, "week"), (86400, "day"),
                       (3600, "hour"), (60, "minute")):
        if s >= size:
            n = int(s // size)
            text = f"{n} {unit}{'s' if n != 1 else ''}"
            return f"in {text}" if future else f"{text} ago"
    return "in a few seconds" if future else "just now"


def local(dt):
    return dt.astimezone()


def show(dt, seconds=True):
    return dt.strftime(f"%a %-d %b %Y, %H:%M{':%S' if seconds else ''}")


def b64decode(s):
    s = s.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4), validate=True)


def printable(data):
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    ok = sum(ch.isprintable() or ch in "\n\r\t" for ch in text)
    return text if ok / len(text) >= 0.97 else None


@recognizer("jwt", order=1, max_chars=8000, raw=True)
def parse_jwt(text):
    m = JWT.match(re.sub(r"\s", "", text.strip().removeprefix("Bearer ").removeprefix("bearer ")))
    if not m:
        return None
    try:
        header, claims = json.loads(b64decode(m.group(1))), json.loads(b64decode(m.group(2)))
    except (ValueError, binascii.Error):
        return None
    if not isinstance(header, dict) or "alg" not in header or not isinstance(claims, dict):
        return None
    return header, claims, bool(m.group(3))


@recognizer("json", order=2, max_chars=8000, in_spans=False, raw=True)
def parse_json(text):
    t = text.strip()
    if not t or t[0] not in "{[" or t[-1] not in "}]":
        return None
    try:
        value = json.loads(t)
    except ValueError:
        return None
    return value if isinstance(value, (dict, list)) and value else None


@recognizer("uuid", order=3)
def parse_uuid(text):
    t = text.strip().strip("\"'")
    if not UUID.match(t):
        return None
    return uuid.UUID(t.strip("{}"))


def http_title(code):
    return E.HTTP[code][0] if code in E.HTTP else ""


SQLSTATE_BY_NAME = {"".join(part.title() for part in name.split("_")): code for code, (name, _) in E.SQLSTATE.items()}


def find_errors(text, limit=4):
    found, seen = [], set()

    def add(code, title, family, explanation, badge=None):
        if code not in seen and len(found) < limit:
            seen.add(code)
            found.append(ErrorEntry(code, title, family, explanation, badge or code))

    for m in re.finditer(r"\bHTTP(?:/\d(?:\.\d)?)?\s*:?\s*([1-5]\d\d)\b|\bstatus(?:\s?code)?\s*[:=]?\s*([1-5]\d\d)\b|"
                         r"\b([1-5]\d\d)\s+([A-Z][A-Za-z' -]{2,40})|\b(?:error|code)\s*:?\s*([45]\d\d)\b", text, re.I):
        code = int(next(g for g in (m.group(1), m.group(2), m.group(3), m.group(5)) if g))
        if code not in E.HTTP:
            continue
        if m.group(3) and not m.group(4).lower().startswith(E.HTTP[code][0].lower()):
            continue
        title, explanation = E.HTTP[code]
        add(str(code), title, "HTTP status", explanation)
    for m in re.finditer(r"\[Errno (\d+)\]|\berrno\s*[:=]?\s*(-?\d+)\b", text, re.I):
        number = abs(int(m.group(1) or m.group(2)))
        name = next((n for n, v in E.ERRNO.items() if v[0] == number), None)
        if name:
            add(name, E.ERRNO[name][1], f"errno {number}", E.ERRNO[name][2], str(number))
    for m in re.finditer(r"\b(E[A-Z0-9]{2,15})\b", text):
        if m.group(1) in E.ERRNO:
            number, title, explanation = E.ERRNO[m.group(1)]
            add(m.group(1), title, f"errno {number}", explanation, str(number))
    by_name = {v[0]: (k, v) for k, v in E.SIGNALS.items()}
    for m in re.finditer(r"\b(SIG[A-Z]{2,7})\b|\bsignal\s*:?\s*(\d{1,2})\b", text, re.I):
        if m.group(1) and m.group(1).upper() in by_name:
            number, (name, title, explanation) = by_name[m.group(1).upper()]
        elif m.group(2) and int(m.group(2)) in E.SIGNALS:
            number = int(m.group(2))
            name, title, explanation = E.SIGNALS[number]
        else:
            continue
        add(name, title, f"Signal {number}", explanation, str(number))
    for m in re.finditer(r"\bexit(?:ed)?(?:\s+with)?(?:\s+(?:code|status))?\s*[:=]?\s*(\d{1,3})\b|"
                         r"\breturn(?:ed)?\s+(?:code\s+)?(\d{1,3})\b", text, re.I):
        number = int(m.group(1) or m.group(2))
        if 129 <= number <= 128 + 31:
            name, title, explanation = E.SIGNALS[number - 128]
            add(f"exit {number}", f"Killed by {name}", f"Exit code {number}", f"128 + {number - 128}: {title.lower()}. "
                + explanation, str(number))
        elif number in E.EXIT:
            add(f"exit {number}", "Success" if number == 0 else "Exit status", f"Exit code {number}", E.EXIT[number],
                str(number))
    for m in re.finditer(r"\bSQLSTATE\s*[\[:=]?\s*([0-9A-Z]{5})\b|\b(?:code|sqlstate)[\"']?\s*[:=]\s*[\"']?([0-9A-Z]{5})\b",
                         text, re.I):
        code = (m.group(1) or m.group(2)).upper()
        if code in E.SQLSTATE:
            name, explanation = E.SQLSTATE[code]
            add(code, name.replace("_", " ").capitalize(), "PostgreSQL SQLSTATE", explanation)
        elif code[:2] in E.SQLSTATE_CLASSES and re.search(r"\d", code):
            add(code, E.SQLSTATE_CLASSES[code[:2]], "SQLSTATE class " + code[:2], "")
    for m in re.finditer(r"\berrors\.([A-Z][A-Za-z]+)\b", text):
        code = SQLSTATE_BY_NAME.get(m.group(1))
        if code:
            name, explanation = E.SQLSTATE[code]
            add(code, name.replace("_", " ").capitalize(), "PostgreSQL SQLSTATE", explanation)
    for m in re.finditer(r"\b0x([0-9a-f]{8})\b|(?<![\d.])(-2\d{9})(?![\d.])", text, re.I):
        value = int(m.group(1), 16) if m.group(1) else int(m.group(2)) & 0xFFFFFFFF
        if value < 0x80000000:
            continue
        label = f"0x{value:08X}"
        if value in E.HRESULT:
            name, explanation = E.HRESULT[value]
            add(label, name, 'NTSTATUS' if value >= 0xC0000000 else 'HRESULT', explanation,
                f"{value & 0xFFFF:04X}")
        else:
            facility, code = (value >> 16) & 0x7FF, value & 0xFFFF
            add(label, f"Failure, facility {E.FACILITIES.get(facility, facility)}", "HRESULT",
                f"Facility {facility}, code {code}" + (" (a Win32 error code)." if facility == 7 else "."), f"{code:04X}")
    for m in re.finditer(r"\b(?:[a-z_]\w*\.)*([A-Z][A-Za-z]+(?:Error|Exception|Exit))\b", text):
        name = m.group(1)
        if name in E.EXCEPTIONS:
            family, explanation = E.EXCEPTIONS[name]
            add(name, re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name), family, explanation,
                {"Python": "Py", "JavaScript": "JS"}.get(family, family))
    for phrase, (family, explanation) in E.GO_RUST.items():
        if phrase in text and (len(phrase) > 8 or re.search(rf"\b{re.escape(phrase)}\b", text)):
            add(phrase if len(phrase) <= 28 else phrase[:26] + "…", phrase[:1].upper() + phrase[1:], family,
                explanation, "!")
    return found


@recognizer("error", order=5, max_chars=140)
def parse_error(text):
    if len(text.split()) > 10:
        return None
    found = find_errors(text)
    return found or None


def cron_values(spec, lo, hi, names=None):
    spec = spec.upper()
    if names:
        for i, name in enumerate(names):
            spec = re.sub(rf"\b{name[:3].upper()}\b", str(i + lo), spec)
    values = set()
    for part in spec.split(","):
        body, _, step = part.partition("/")
        step = int(step) if step else 1
        if step <= 0:
            raise ValueError("step")
        if body in ("*", "?"):
            a, b = lo, hi
        elif "-" in body:
            a, b = (int(x) for x in body.split("-"))
        else:
            a = int(body)
            b = hi if step > 1 else a
        if not (lo <= a <= hi and lo <= b <= hi + (1 if hi == 6 else 0)) or a > b:
            raise ValueError("range")
        values.update(range(a, b + 1, step))
    return sorted(v % 7 if hi == 6 else v for v in values)


@recognizer("cron", order=25, raw=True)
def parse_cron(text):
    t = " ".join(text.split())
    t = MACROS.get(t.lower(), t)
    parts = t.split(" ")
    if len(parts) == 6 and parts[0].isdigit():
        parts = parts[1:]
    if len(parts) != 5 or not all(CRON_FIELD.match(p) for p in parts) or not any("*" in p or "?" in p for p in parts):
        return None
    try:
        minutes = cron_values(parts[0], 0, 59)
        hours = cron_values(parts[1], 0, 23)
        days = cron_values(parts[2], 1, 31)
        months = cron_values(parts[3], 1, 12, MONTH_NAMES)
        weekdays = cron_values(parts[4], 0, 6, DAY_NAMES)
    except ValueError:
        return None
    star = [p in ("*", "?") for p in parts]
    return {"parts": parts, "minutes": minutes, "hours": hours, "days": days, "months": months,
            "weekdays": weekdays, "star": star, "text": " ".join(parts)}


def ranges(values):
    out, start = [], None
    for i, v in enumerate(values):
        if start is None:
            start = v
        if i == len(values) - 1 or values[i + 1] != v + 1:
            out.append((start, v))
            start = None
    return out


def join_words(items):
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def name_list(values, names, offset=0):
    parts = []
    for a, b in ranges(values):
        if b - a >= 2:
            parts.append(f"{names[a - offset]} to {names[b - offset]}")
        else:
            parts.extend(names[v - offset] for v in range(a, b + 1))
    return join_words(parts)


def step_of(spec):
    m = re.fullmatch(r"(?:\*|0)/(\d+)", spec)
    return int(m.group(1)) if m else None


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def describe_cron(c):
    p, star = c["parts"], c["star"]
    minutes, hours = c["minutes"], c["hours"]
    if star[0] and star[1]:
        time = "Every minute"
    elif step_of(p[0]) and star[1]:
        time = f"Every {step_of(p[0])} minutes"
    elif len(minutes) == 1 and star[1]:
        time = "Every hour, on the hour" if minutes[0] == 0 else f"At {minutes[0]} minutes past every hour"
    elif len(minutes) == 1 and step_of(p[1]):
        time = f"Every {step_of(p[1])} hours" + (f", at minute {minutes[0]}" if minutes[0] else "")
    elif len(minutes) * len(hours) <= 6:
        time = "At " + join_words(f"{h:02d}:{m:02d}" for h in hours for m in minutes)
    elif star[0]:
        time = f"Every minute during hour {join_words(map(str, hours))}"
    else:
        time = f"At minute {join_words(map(str, minutes))} past hour {join_words(map(str, hours))}"
    days = []
    if not star[2]:
        days.append("on the " + join_words(ordinal(d) for d in c["days"]) + " of the month")
    if not star[4]:
        days.append("on " + name_list(c["weekdays"], DAY_NAMES))
    day = " or ".join(days)
    month = "" if star[3] else "in " + name_list(c["months"], MONTH_NAMES, 1)
    if not day and not month and time.startswith("At ") and not star[1]:
        day = "every day"
    return " ".join(x for x in (time, day, month) if x)


def cron_runs(c, start, count=5):
    runs = []
    day = start.date()
    restricted_dom, restricted_dow = not c["star"][2], not c["star"][4]
    for _ in range(366 * 5):
        if day.month in c["months"]:
            dom_ok = day.day in c["days"]
            dow_ok = (day.weekday() + 1) % 7 in c["weekdays"]
            ok = (dom_ok or dow_ok) if restricted_dom and restricted_dow else (dom_ok and dow_ok)
            if ok:
                for h in c["hours"]:
                    for m in c["minutes"]:
                        when = datetime(day.year, day.month, day.day, h, m, tzinfo=start.tzinfo)
                        if when > start:
                            runs.append(when)
                            if len(runs) == count:
                                return runs
        day += timedelta(days=1)
    return runs


def from_unix(value):
    return datetime.fromtimestamp(value, timezone.utc)


@recognizer("timestamp", order=36, max_chars=48)
def parse_timestamp(text):
    t = text.strip().strip("\"'")
    if re.fullmatch(r"\d{9,19}(?:\.\d{1,9})?", t):
        whole, _, frac = t.partition(".")
        n = len(whole)
        value = float(t)
        for digits, scale, label in ((10, 1, "Unix seconds"), (9, 1, "Unix seconds"), (13, 1e3, "Unix milliseconds"),
                                     (12, 1e3, "Unix milliseconds"), (16, 1e6, "Unix microseconds"),
                                     (19, 1e9, "Unix nanoseconds")):
            if n == digits and UNIX_MIN <= value / scale <= UNIX_MAX:
                return from_unix(value / scale), label
        if n == 18 and not frac and TICKS_EPOCH <= int(t) <= TICKS_EPOCH + UNIX_MAX * 10_000_000:
            return from_unix((int(t) - TICKS_EPOCH) / 10_000_000), ".NET ticks"
        return None
    if ISO.match(t):
        s = re.sub(r"\s?UTC$", "+00:00", t, flags=re.I).replace(",", ".")
        s = re.sub(r"(\.\d{6})\d+", r"\1", s)
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        return (dt, "ISO 8601") if dt.tzinfo else (dt.astimezone(), "ISO 8601, no time zone")
    if RFC2822.match(t):
        try:
            return parsedate_to_datetime(t), "RFC 2822"
        except (TypeError, ValueError):
            return None
    return None


@recognizer("number", order=28, max_chars=70)
def parse_number(text):
    t = text.strip().replace("_", "").replace(" ", "")
    m = re.fullmatch(r"0([xbo])([0-9a-f]+)", t, re.I)
    if not m:
        return None
    try:
        return int(m.group(2), {"x": 16, "b": 2, "o": 8}[m.group(1).lower()]), m.group(1).lower()
    except ValueError:
        return None


@recognizer("encoded", order=120, max_chars=8000, raw=True)
def parse_encoded(text):
    t = text.strip()
    if re.search(r"%[0-9A-F]{2}", t, re.I) and len(re.findall(r"%[0-9A-F]{2}", t, re.I)) >= 2:
        decoded = urllib.parse.unquote_plus(t) if "+" in t and " " not in t else urllib.parse.unquote(t)
        if decoded != t and printable(decoded.encode()):
            return "URL encoding", decoded
    compact = re.sub(r"\s", "", t)
    if HEXBYTES.match(t) and len(re.sub(r"[^0-9a-f]", "", compact.lower().removeprefix("0x"))) >= 8:
        digits = re.sub(r"[^0-9a-f]", "", compact.lower().removeprefix("0x"))
        if len(digits) % 2 == 0:
            text_value = printable(bytes.fromhex(digits))
            if text_value and len(text_value) >= 4:
                return "Hex", text_value
    if B64.match(compact) and len(compact) % 4 != 1 and (re.search(r"[0-9+/=_-]", compact) or len(compact) >= 16):
        try:
            text_value = printable(b64decode(compact))
        except (binascii.Error, ValueError):
            return None
        if text_value and len(text_value) >= 4 and sum(ch.isalnum() for ch in text_value) >= len(text_value) * 0.5:
            return "Base64", text_value
    return None


@resolver("jwt")
def jwt_card(route):
    header, claims, signed = route.value
    now = datetime.now(timezone.utc)
    rows, state, status, progress = [], "none", "No expiry", None
    times = {k: from_unix(claims[k]) for k in ("exp", "iat", "nbf") if isinstance(claims.get(k), (int, float))}
    if "nbf" in times and times["nbf"] > now:
        state, status = "pending", "Valid " + humanize((times["nbf"] - now).total_seconds())
    elif "exp" in times:
        left = (times["exp"] - now).total_seconds()
        state, status = ("expired", "Expired " + humanize(left)) if left <= 0 else ("valid", "Expires " + humanize(left))
        start = times.get("iat") or times.get("nbf")
        if start and times["exp"] > start:
            progress = min(1.0, max(0.0, (now - start) / (times["exp"] - start)))
    for key, value in claims.items():
        label = CLAIM_NAMES.get(key, key)
        if key in times:
            shown = show(local(times[key]))
        elif isinstance(value, (list, tuple)):
            shown = ", ".join(map(str, value))
        elif isinstance(value, dict):
            shown = json.dumps(value, ensure_ascii=False)
        else:
            shown = str(value)
        rows.append((label, shown))
    chips = [header.get("alg", ""), header.get("typ", ""), "signed" if signed else "unsigned"]
    return JwtCard(title="JSON Web Token", header=header, claims=claims, status=status, state=state,
                   progress=progress, rows=rows[:8],
                   actions=[Action("Copy claims", "copy", json.dumps(claims, indent=2, ensure_ascii=False)),
                            Action("Copy header", "copy", json.dumps(header, indent=2, ensure_ascii=False))],
                   chips=[c for c in chips if c])


@resolver("json")
def json_card(route):
    value = route.value
    pretty = json.dumps(value, indent=2, ensure_ascii=False)
    shape = f"{len(value)} keys" if isinstance(value, dict) else f"{len(value)} items"
    return CodeCard(title="JSON", chips=[shape], code=pretty, language="JSON", copy_label="Copy formatted",
                    actions=[Action("Copy minified", "copy", json.dumps(value, separators=(",", ":"),
                                                                       ensure_ascii=False))])


@resolver("uuid")
def uuid_card(route):
    u = route.value
    chips, rows = [], []
    if u.int == 0:
        chips.append("Nil UUID")
    elif u.int == (1 << 128) - 1:
        chips.append("Max UUID")
    else:
        variant = {uuid.RFC_4122: "RFC 9562", uuid.RESERVED_NCS: "NCS", uuid.RESERVED_MICROSOFT: "Microsoft GUID",
                   uuid.RESERVED_FUTURE: "Reserved"}.get(u.variant, u.variant)
        chips.append(f"Version {u.version}" if u.variant == uuid.RFC_4122 else variant)
        rows.append(("Variant", variant))
        kind = {1: "Time and MAC address", 2: "DCE security", 3: "MD5 name hash", 4: "Random", 5: "SHA-1 name hash",
                6: "Reordered time", 7: "Unix time and random", 8: "Custom"}.get(u.version)
        if u.variant == uuid.RFC_4122 and kind:
            rows.append(("Kind", kind))
        when = None
        if u.variant == uuid.RFC_4122 and u.version in (1, 6):
            hi = u.int >> 64
            ticks = u.time if u.version == 1 else ((hi >> 16) << 12) | (hi & 0x0FFF)
            when = datetime(1582, 10, 15, tzinfo=timezone.utc) + timedelta(microseconds=ticks // 10)
            if u.version == 1:
                rows.append(("Node", ":".join(f"{(u.node >> s) & 0xFF:02x}" for s in range(40, -1, -8))))
        elif u.variant == uuid.RFC_4122 and u.version == 7:
            when = from_unix((u.int >> 80) / 1000)
        if when:
            rows.insert(0, ("Created", show(local(when))))
            chips.append(humanize((when - datetime.now(timezone.utc)).total_seconds()))
    s = str(u)
    return TextCard(title=s, chips=chips, rows=rows,
                    actions=[Action("Copy", "copy", s), Action("Uppercase", "copy", s.upper()),
                             Action("No dashes", "copy", u.hex)])


@resolver("cron")
def cron_card(route):
    c = route.value
    now = datetime.now().astimezone().replace(second=0, microsecond=0)
    runs = [Run(r, humanize((r - datetime.now().astimezone()).total_seconds())) for r in cron_runs(c, now)]
    labels = ["Minute", "Hour", "Day", "Month", "Weekday"]
    return CronCard(title=c["text"], expression=c["text"], description=describe_cron(c),
                    fields=list(zip(labels, c["parts"])), runs=runs,
                    actions=[Action("Copy", "copy", c["text"])])


@resolver("timestamp")
def timestamp_card(route):
    dt, label = route.value
    utc = dt.astimezone(timezone.utc)
    seconds = utc.timestamp()
    rows = [("Local", show(local(dt)) + " " + local(dt).strftime("%Z")),
            ("UTC", show(utc)),
            ("ISO 8601", utc.isoformat().replace("+00:00", "Z")),
            ("Unix", f"{seconds:.0f}" if seconds == int(seconds) else f"{seconds:.3f}"),
            ("Unix ms", f"{seconds * 1000:.0f}")]
    rows = [r for r in rows if r[1] != route.text.strip()]
    return TextCard(title=route.text.strip(), chips=[label, humanize(seconds - datetime.now(timezone.utc).timestamp())],
                    value=local(dt).strftime("%H:%M:%S"), definition=local(dt).strftime("%A %-d %B %Y"), rows=rows)


@resolver("number")
def number_card(route):
    n, base = route.value
    rows = [("Decimal", f"{n:,}".replace(",", " ")), ("Hex", f"0x{n:X}"), ("Octal", f"0o{n:o}"),
            ("Binary", " ".join(re.findall(r".{1,4}", f"{n:b}"[::-1]))[::-1])]
    rows = [r for r in rows if not (base == "x" and r[0] == "Hex" or base == "o" and r[0] == "Octal"
                                    or base == "b" and r[0] == "Binary")]
    bits = max(8, 1 << (n.bit_length() - 1).bit_length()) if n else 8
    chips = [f"{bits}-bit"]
    if n >> (bits - 1) & 1 and bits <= 64:
        chips.append(f"signed {n - (1 << bits)}")
    if 32 <= n < 127:
        chips.append(f"ASCII '{chr(n)}'")
    return TextCard(title=route.text.strip(), value=str(n), chips=chips, rows=rows)


@resolver("encoded")
def encoded_card(route):
    encoding, decoded = route.value
    try:
        pretty = json.dumps(json.loads(decoded), indent=2, ensure_ascii=False)
        language = "JSON"
    except ValueError:
        pretty, language = decoded, ""
    return CodeCard(title=f"Decoded {encoding}", chips=[f"{len(decoded.encode())} bytes"] + ([language] if language else []),
                    code=pretty, language=language, copy_label="Copy decoded")


def error_actions(entries, code):
    query = " ".join(dict.fromkeys(f"{e.code} {e.title}" if e.code != e.title else e.code for e in entries[:2]))
    return [Action("Search the web", "open", "https://www.google.com/search?q=" + urllib.parse.quote_plus(query)),
            Action("Copy", "copy", code)]


@resolver("error")
def error_card(route):
    entries = route.value
    return ErrorCard(title=entries[0].title, entries=entries, code=route.text.strip(),
                     actions=error_actions(entries, route.text.strip()))


@resolver("code_or_error")
def code_or_error_card(route):
    code = layout.code(route.words) if route.words else (route.source or route.text).strip()
    entries = find_errors(route.text)
    if entries:
        return ErrorCard(title=entries[0].title, entries=entries, code=code, actions=error_actions(entries, code))
    lines = code.count("\n") + 1
    return CodeCard(title="Code", chips=[f"{lines} line{'s' if lines != 1 else ''}"], code=code,
                    copy_label="Copy code")
