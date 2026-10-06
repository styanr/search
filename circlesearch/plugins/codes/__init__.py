import base64
import hashlib
import hmac
import re
import shutil
import struct
import time
import urllib.parse
from dataclasses import dataclass, field

from circlesearch.core.cards import Action, Card, TextCard
from circlesearch.core.pipeline import resolve, resolver
from circlesearch.core.routing import Route, default_router
from circlesearch.plugins.iban import compact as iban_compact, describe as describe_iban, grouped

SENSITIVE = ("WIFI:", "otpauth://", "otpauth-migration://")
GS1 = [((0, 19), "USA or Canada"), ((30, 39), "USA"), ((60, 139), "USA or Canada"), ((300, 379), "France"),
       ((380, 380), "Bulgaria"), ((383, 383), "Slovenia"), ((385, 385), "Croatia"), ((400, 440), "Germany"),
       ((450, 459), "Japan"), ((460, 469), "Russia"), ((471, 471), "Taiwan"), ((474, 474), "Estonia"),
       ((475, 475), "Latvia"), ((477, 477), "Lithuania"), ((482, 482), "Ukraine"), ((484, 484), "Moldova"),
       ((489, 489), "Hong Kong"), ((490, 499), "Japan"), ((500, 509), "United Kingdom"), ((520, 521), "Greece"),
       ((539, 539), "Ireland"), ((540, 549), "Belgium or Luxembourg"), ((560, 560), "Portugal"),
       ((569, 569), "Iceland"), ((570, 579), "Denmark"), ((590, 590), "Poland"), ((594, 594), "Romania"),
       ((599, 599), "Hungary"), ((640, 649), "Finland"), ((690, 699), "China"), ((700, 709), "Norway"),
       ((729, 729), "Israel"), ((730, 739), "Sweden"), ((760, 769), "Switzerland"), ((800, 839), "Italy"),
       ((840, 849), "Spain"), ((858, 858), "Slovakia"), ((859, 859), "Czechia"), ((860, 860), "Serbia"),
       ((868, 869), "Türkiye"), ((870, 879), "Netherlands"), ((880, 880), "South Korea"), ((885, 885), "Thailand"),
       ((888, 888), "Singapore"), ((890, 890), "India"), ((893, 893), "Vietnam"), ((899, 899), "Indonesia"),
       ((900, 919), "Austria"), ((930, 939), "Australia"), ((940, 949), "New Zealand"), ((955, 955), "Malaysia"),
       ((977, 977), "Periodical (ISSN)"), ((978, 979), "Book (ISBN)")]


@dataclass(kw_only=True)
class WifiCard(Card):
    kind = "wifi"
    accent = "blue"
    priority = 1

    ssid: str
    security: str
    password: str = ""
    hidden: bool = False


@dataclass(kw_only=True)
class OtpCard(Card):
    kind = "otp"
    accent = "amber"
    priority = 1

    issuer: str
    account: str
    secret: str = field(repr=False)
    algorithm: str = "SHA1"
    digits: int = 6
    period: int = 30
    counter: int | None = None

    def code(self, at=None):
        key = base64.b32decode(self.secret.upper() + "=" * (-len(self.secret) % 8), casefold=True)
        counter = self.counter if self.counter is not None else int((at or time.time()) // self.period)
        digest = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, self.algorithm.lower(), hashlib.sha1)).digest()
        offset = digest[-1] & 0x0F
        value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
        return str(value % 10 ** self.digits).zfill(self.digits)


@dataclass(kw_only=True)
class CodeTextCard(TextCard):
    kind = "scanned"
    title_role = "passage"


def unescape_fields(body):
    fields, parts, current, escaped = {}, [], "", False
    for ch in body:
        if escaped:
            current += ch
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ";":
            parts.append(current)
            current = ""
        else:
            current += ch
    if current:
        parts.append(current)
    for part in parts:
        if ":" in part:
            key, _, value = part.partition(":")
            fields[key.upper()] = value
    return fields


def wifi(data):
    f = unescape_fields(data[5:])
    security = {"WPA": "WPA/WPA2", "WPA2": "WPA2", "WPA3": "WPA3", "SAE": "WPA3", "WEP": "WEP",
                "NOPASS": "Open", "": "Open"}.get(f.get("T", "").upper(), f.get("T", ""))
    ssid, password, hidden = f.get("S", ""), f.get("P", ""), f.get("H", "").lower() == "true"
    actions = []
    if shutil.which("nmcli"):
        command = ["nmcli", "--ask", "device", "wifi", "connect", ssid] + (["hidden", "yes"] if hidden else [])
        actions.append(Action("Connect", "run", {"command": command, "stdin": password + "\n" if password else None}))
    if password:
        actions.append(Action("Copy password", "copy", password))
    actions.append(Action("Copy name", "copy", ssid))
    return WifiCard(title=ssid or "Wi-Fi network", ssid=ssid, security=security, password=password, hidden=hidden,
                    actions=actions)


def otp(data):
    parts = urllib.parse.urlsplit(data)
    query = dict(urllib.parse.parse_qsl(parts.query))
    label = urllib.parse.unquote(parts.path.lstrip("/"))
    issuer, _, account = label.partition(":") if ":" in label else ("", "", label)
    issuer = query.get("issuer", issuer).strip()
    secret = re.sub(r"[\s=]", "", query.get("secret", ""))
    if not secret:
        return None
    try:
        base64.b32decode(secret.upper() + "=" * (-len(secret) % 8), casefold=True)
    except ValueError:
        return None
    hotp = parts.netloc.lower() == "hotp"
    card = OtpCard(title=issuer or account or "One-time code", issuer=issuer, account=account.strip(), secret=secret,
                   algorithm=query.get("algorithm", "SHA1").upper(), digits=int(query.get("digits", 6)),
                   period=int(query.get("period", 30)), counter=int(query.get("counter", 0)) if hotp else None)
    card.actions = [Action("Copy code", "copy", card.code()), Action("Copy secret", "copy", secret)]
    return card


def payment(lines):
    lines = [line.strip() for line in lines]
    if len(lines) < 7:
        return None
    iban_line = next((line for line in lines if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9 ]{10,32}", line)), "")
    amount_line = next((line for line in lines if re.fullmatch(r"[A-Z]{3}\d+(?:[.,]\d{1,2})?", line)), "")
    name = lines[5] if len(lines) > 5 else ""
    rows = []
    iban = iban_compact(iban_line) if iban_line else ""
    chips = []
    if iban:
        ok, status, country, bank, _, _ = describe_iban(iban)
        rows.append(("IBAN", grouped(iban)))
        if not ok:
            rows.append(("Check", status))
        if bank:
            rows.append(("Bank", bank))
    after = lines[lines.index(amount_line) + 1:] if amount_line else lines[8:]
    if lines[3] == "UCT" and after and re.fullmatch(r"\d{8,10}", after[0]):
        rows.append(("Tax code", after[0]))
        after = after[1:]
    if lines[4] and lines[3] == "SCT":
        rows.append(("BIC", lines[4]))
    purpose = next((line for line in reversed(after) if len(line) > 3), "")
    if purpose:
        rows.append(("Purpose", purpose))
    value = ""
    if amount_line:
        value = f"{amount_line[3:].replace(',', '.')} {amount_line[:3]}"
    actions = [Action("Copy IBAN", "copy", iban)] if iban else []
    if value:
        actions.append(Action("Copy amount", "copy", amount_line[3:]))
    actions.append(Action("Copy all", "copy", "\n".join(f"{k}: {v}" for k, v in [("Name", name), *rows,
                                                                                ("Amount", value)] if v)))
    return TextCard(title=name or "Payment", value=value, chips=chips, rows=rows, actions=actions)


def nbu(data):
    token = data.split("/qr/", 1)[1].split("?")[0].strip("/")
    try:
        text = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        try:
            text = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("cp1251")
        except ValueError:
            return None
    return payment(text.split("\n")) if text.startswith("BCD") else None


def vcard(data):
    name, phones, emails, org, url = "", [], [], "", ""
    if data.upper().startswith("MECARD:"):
        f = {}
        for part in re.split(r"(?<!\\);", data[7:]):
            key, _, value = part.partition(":")
            f.setdefault(key.upper(), []).append(value.replace("\\", ""))
        raw = (f.get("N") or [""])[0]
        name = " ".join(reversed(raw.split(","))) if "," in raw else raw
        phones, emails, org, url = f.get("TEL", []), f.get("EMAIL", []), (f.get("ORG") or [""])[0], (f.get("URL") or [""])[0]
    else:
        for line in re.split(r"\r?\n", data):
            key, _, value = line.partition(":")
            key = key.split(";")[0].upper()
            if key == "FN":
                name = value
            elif key == "N" and not name:
                name = " ".join(p for p in reversed(value.split(";")[:2]) if p)
            elif key == "TEL":
                phones.append(value)
            elif key == "EMAIL":
                emails.append(value)
            elif key == "ORG":
                org = value.replace(";", ", ")
            elif key == "URL":
                url = value
    rows = [("Phone", p) for p in phones[:3]] + [("Email", e) for e in emails[:2]] + ([("Website", url)] if url else [])
    actions = []
    if phones:
        actions.append(Action("Call", "open", "tel:" + re.sub(r"[^\d+]", "", phones[0])))
    if emails:
        actions.append(Action("Email", "open", "mailto:" + emails[0]))
    content = data if data.upper().startswith("BEGIN:VCARD") else (
        "BEGIN:VCARD\nVERSION:3.0\nFN:" + name + "".join(f"\nTEL:{p}" for p in phones)
        + "".join(f"\nEMAIL:{e}" for e in emails) + (f"\nORG:{org}" if org else "") + "\nEND:VCARD\n")
    actions.append(Action("Save contact", "save", content, filename=(re.sub(r"\W+", "-", name) or "contact") + ".vcf"))
    return TextCard(title=name or "Contact", definition=org, rows=rows, actions=actions)


def ean_ok(digits):
    payload, check = digits[:-1], int(digits[-1])
    total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(payload)))
    return (10 - total % 10) % 10 == check


def product(code):
    digits = code.data
    chips = [code.format]
    rows = []
    if digits.isdigit() and len(digits) in (8, 12, 13):
        padded = digits.zfill(13)
        if not ean_ok(digits):
            rows.append(("Check digit", "Wrong"))
        prefix = int(padded[:3])
        origin = next((name for (lo, hi), name in GS1 if lo <= prefix <= hi), "")
        if origin:
            rows.append(("Registered in" if prefix < 977 else "Type", origin))
        if padded[:3] in ("978", "979"):
            isbn10 = ""
            if padded.startswith("978"):
                body = padded[3:12]
                check = (11 - sum((10 - i) * int(d) for i, d in enumerate(body)) % 11) % 11
                isbn10 = body + ("X" if check == 10 else str(check))
                rows.append(("ISBN-10", isbn10))
            actions = [Action("Find book", "open", f"https://openlibrary.org/isbn/{padded}"),
                       Action("Copy ISBN", "copy", padded)]
            return TextCard(title=padded, chips=chips, rows=rows, actions=actions)
    actions = [Action("Search product", "open", "https://www.google.com/search?q=" + urllib.parse.quote_plus(digits)),
               Action("Copy number", "copy", digits)]
    return TextCard(title=digits, chips=chips, rows=rows, actions=actions)


def plain(code):
    data = code.data.strip()
    route = default_router().route(data)
    card = resolve(route) if route.kind not in ("term", "entity", "foreign_text") or len(data) < 40 else None
    if card is not None:
        return card
    return CodeTextCard(title=data[:600], chips=[code.format], actions=[Action("Copy text", "copy", data)])


@resolver("barcode")
def barcode_card(route):
    code = route.value
    data = code.data
    upper = data[:16].upper()
    if upper.startswith("WIFI:"):
        return wifi(data)
    if upper.startswith("OTPAUTH://"):
        return otp(data)
    if upper.startswith("BCD\n") or upper.startswith("BCD\r"):
        return payment(re.split(r"\r?\n", data))
    if re.match(r"https?://bank\.gov\.ua/qr/", data, re.I):
        return nbu(data)
    if upper.startswith(("BEGIN:VCARD", "MECARD:")):
        return vcard(data)
    if upper.startswith("MATMSG:") or upper.startswith("MAILTO:"):
        address = re.search(r"(?:TO:|mailto:)([^;?]+)", data, re.I)
        data = address.group(1) if address else data
        code = type(code)(code.format, data)
    elif upper.startswith(("TEL:", "SMSTO:", "SMS:")):
        code = type(code)(code.format, data.split(":", 2)[1])
    elif upper.startswith("GEO:"):
        m = re.match(r"geo:(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", data, re.I)
        if m:
            from circlesearch.plugins.places import place_card
            return place_card(f"{m.group(1)}, {m.group(2)}", float(m.group(1)), float(m.group(2)), 15)
    if code.format in ("EAN-13", "EAN-8", "UPC-A", "UPC-E", "ITF", "Code 128", "Code 39", "DataBar") \
            and data.isdigit():
        return product(code)
    return plain(code)


def is_sensitive(data):
    return data.upper().startswith(tuple(s.upper() for s in SENSITIVE))


def label(code):
    return f"{code.format} code" if is_sensitive(code.data) else code.data


def route_for(code):
    return Route("barcode", text=label(code), value=code)
