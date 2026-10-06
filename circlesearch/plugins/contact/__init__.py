import re
import urllib.parse
from dataclasses import dataclass

from circlesearch.core.cards import Action, TextCard
from circlesearch.core.locale import current
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer

TLDS = "com|org|net|io|dev|app|ai|ua|eu|de|uk|pl|fr|gov|edu|co|me|info|xyz|tech|site|page"
LINK = re.compile(rf"^(?:https?://\S+|www\.[\w-]+(?:\.[\w-]+)+\S*|[\w-]+(?:\.[\w-]+)*\.(?:{TLDS})(?:/\S*)?)$", re.I)
EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
PHONE = re.compile(r"^\+?[\d\s().-]{9,20}$")
UA_OPERATORS = {**dict.fromkeys(["50", "66", "95", "99", "75"], "Vodafone"),
                **dict.fromkeys(["67", "68", "96", "97", "98", "77"], "Kyivstar"),
                **dict.fromkeys(["63", "73", "93"], "lifecell")}


@dataclass(kw_only=True)
class LinkCard(TextCard):
    kind = "link"


@dataclass(kw_only=True)
class EmailCard(TextCard):
    kind = "email"


@dataclass(kw_only=True)
class PhoneCard(TextCard):
    kind = "phone"


@recognizer("link", order=10)
def parse_link(text):
    t = text.strip().rstrip(".,;)")
    return t if LINK.match(t) and " " not in t else None


@recognizer("email", order=20)
def parse_email(text):
    t = text.strip().strip("<>").rstrip(".,;")
    return t if EMAIL.match(t) else None


@recognizer("phone", order=90)
def parse_phone(text):
    t = text.strip()
    if not PHONE.match(t) or re.match(r"^\d{4}-\d{2}-\d{2}$", t):
        return None
    digits = re.sub(r"\D", "", t)
    if t.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    if len(digits) == 10 and digits.startswith("0") and current().country == "UA":
        return "+38" + digits
    if len(digits) == 12 and digits.startswith("380"):
        return "+" + digits
    return None


@resolver("link")
def link_card(route):
    t = route.value
    url = t if re.match(r"^https?://", t, re.I) else "https://" + t
    parts = urllib.parse.urlsplit(url)
    path = (parts.path + ("?" + parts.query if parts.query else "")).strip("/")
    return LinkCard(title=parts.netloc, definition=path,
                    actions=[Action("Open", "open", url), Action("Copy link", "copy", url)])


@resolver("email")
def email_card(route):
    t = route.value
    return EmailCard(title=t, actions=[Action("Write email", "open", "mailto:" + t), Action("Copy", "copy", t)])


@resolver("phone")
def phone_card(route):
    number = route.value
    chips = []
    if number.startswith("+380") and len(number) == 13:
        shown = f"+380 {number[4:6]} {number[6:9]} {number[9:11]} {number[11:]}"
        if number[4:6] in UA_OPERATORS:
            chips.append(UA_OPERATORS[number[4:6]])
        chips.append("Ukraine")
    else:
        shown = number
    return PhoneCard(title=shown, chips=chips,
                     actions=[Action("Call", "open", "tel:" + number), Action("Copy", "copy", number)])
