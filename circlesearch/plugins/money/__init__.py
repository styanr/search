import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from circlesearch.core.cards import Card
from circlesearch.core.locale import current
from circlesearch.core.net import OPTIONAL_TIMEOUT, get_json, safe
from circlesearch.core.pipeline import enricher, resolver
from circlesearch.core.routing import recognizer
from circlesearch.core.text import parse_number
from circlesearch.plugins.wikidata import sparql

SYMBOLS = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "₴": "UAH", "грн": "UAH", "¥": "JPY",
           "zł": "PLN", "kč": "CZK", "chf": "CHF", "c$": "CAD", "ca$": "CAD", "a$": "AUD", "₺": "TRY", "₾": "GEL"}
CODES = {"USD", "EUR", "GBP", "UAH", "PLN", "CHF", "CZK", "JPY", "CNY", "CAD", "AUD", "SEK", "NOK",
         "DKK", "HUF", "RON", "TRY", "GEL", "ILS", "MDL", "KZT", "BGN", "INR", "KRW", "SGD", "HKD"}
SYMBOL_OF = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "UAH": "₴", "PLN": "zł", "CHF": "CHF", "CZK": "Kč",
             "TRY": "₺", "GEL": "₾", "INR": "₹", "KRW": "₩", "CNY": "¥"}
MONEY = re.compile(r"^(?P<pre>[$€£₴¥₺₾]|US\$|CA\$|C\$|A\$|[A-Za-z]{3})?\s?"
                   r"(?P<num>\d{1,3}(?:[\s.,' \xa0]\d{3})*(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)\s?"
                   r"(?P<k>[kKmM](?![a-z]))?\s?(?P<post>[$€£₴¥₺₾]|zł|Kč|грн\.?|[A-Za-z]{3})?$")
FRANKFURTER = "https://api.frankfurter.dev/v1/"
CURRENCY_API = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/"


@dataclass(kw_only=True)
class MoneyCard(Card):
    kind = "money"
    priority = 3
    accent = "green"

    value: str
    unit: str = ""
    rate: str = ""
    conversions: list[tuple[str, str]] = field(default_factory=list)
    history: list[tuple[str, float]] | None = None


_rates = {}


def money_str(amount, code):
    loc = current()
    symbol = loc.currency_symbol() if code == loc.currency else SYMBOL_OF.get(code, code)
    return loc.format_money(amount, symbol)


def _currency(token):
    if not token:
        return None
    t = token.rstrip(".")
    return SYMBOLS.get(t.lower()) or SYMBOLS.get(t) or (t.upper() if t.upper() in CODES else None)


@recognizer("money", order=70)
def parse_money(text):
    m = MONEY.match(text.strip())
    if not m or bool(m.group("pre")) == bool(m.group("post")):
        return None
    code = _currency(m.group("pre") or m.group("post"))
    if not code:
        return None
    amount = parse_number(m.group("num")) * {"k": 1e3, "m": 1e6}.get((m.group("k") or "").lower(), 1)
    return amount, code


def home_rates():
    if _rates:
        return _rates
    home = current().currency
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
    home = current().currency.lower()
    if code not in rates and not rates.get("_extended"):
        rates["_extended"] = True
        data = safe(get_json, f"{CURRENCY_API}{home}.json")
        for c, r in ((data or {}).get(home, {}) or {}).items():
            if r and c.upper() not in rates:
                rates[c.upper()] = 1 / r
    return rates.get(code)


def rate_history(code, days):
    rates = home_rates()
    home = current().currency
    end = date.today()
    start = end - timedelta(days=days)
    if rates.get("_history") == "nbu":
        data = get_json("https://bank.gov.ua/NBU_Exchange/exchange_site?" + urllib.parse.urlencode(
            {"start": f"{start:%Y%m%d}", "end": f"{end:%Y%m%d}", "valcode": code.lower(), "sort": "exchangedate",
             "order": "asc", "json": ""}), timeout=OPTIONAL_TIMEOUT)
        return [(datetime.strptime(r["exchangedate"], "%d.%m.%Y").strftime("%-d %b"), r["rate_per_unit"]) for r in data]
    if rates.get("_history") == "frankfurter":
        data = get_json(f"{FRANKFURTER}{start:%Y-%m-%d}..{end:%Y-%m-%d}?base={code}&symbols={home}",
                        timeout=OPTIONAL_TIMEOUT)
        series = (data or {}).get("rates", {})
        return [(date.fromisoformat(d).strftime("%-d %b"), v[home]) for d, v in sorted(series.items()) if home in v]
    return None


@resolver("money")
def money_card(route):
    amount, code = route.value
    rates = home_rates()
    home = current().currency
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
    return MoneyCard(title=route.text, value=value,
                     conversions=[(current().currency_name(c), money_str(worth / rates[c], c)) for c in others],
                     rate=f"1 {code} = {money_str(rates[code], home)}" if code != home else "",
                     source=f"{rates['_source']}, {rates['_date']}", url=rates["_url"])


@enricher("currency", needs={"currency_qid"}, order=30)
def country_currency(facts):
    qid = facts["currency_qid"]
    rows = sparql(f"""SELECT ?code ?en ?mul WHERE {{
  wd:{qid} wdt:P498 ?code .
  OPTIONAL {{ wd:{qid} rdfs:label ?en FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ wd:{qid} rdfs:label ?mul FILTER(LANG(?mul) = "mul") }}
}}""")
    rates = home_rates()
    home = current().currency
    code = next((r["code"]["value"] for r in rows if rate_of(r["code"]["value"]) is not None), None)
    if code is None or code == home:
        return [], {}
    name = rows[0].get("en", {}).get("value") or rows[0].get("mul", {}).get("value") or code
    rate = rates[code]
    history = safe(rate_history, code, 30)
    return [MoneyCard(title=name[:1].upper() + name[1:], value=money_str(rate, home), unit=f"1 {code}",
                      history=history if history and len(history) > 2 else None,
                      conversions=[(f"100 {code}", money_str(100 * rate, home)), (f"1 {home}", money_str(1 / rate, code))],
                      source=f"{rates['_source']}, {rates['_date']}", url=rates["_url"])], {}
