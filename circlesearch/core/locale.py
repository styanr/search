import locale as pylocale
import os
from dataclasses import dataclass

from circlesearch.core import settings

IMPERIAL = {"US", "LR", "MM"}
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
ISO639_2 = {"en": "eng", "uk": "ukr", "de": "deu", "fr": "fra", "es": "spa", "it": "ita", "pl": "pol", "pt": "por",
            "nl": "nld", "cs": "ces", "ru": "rus", "ja": "jpn", "ko": "kor", "el": "ell", "tr": "tur"}


@dataclass
class Locale:
    ui_language: str = "en"
    language: str = "en"
    currency: str = "USD"
    metric: bool = True
    country: str = ""

    def currency_symbol(self):
        return self.currency

    def format_money(self, amount, symbol):
        return f"{symbol}{amount:,.2f}"

    def format_number(self, value, decimals):
        return f"{value:.{decimals}f}"

    def language_name(self, code):
        return code

    def currency_name(self, code):
        return code

    def month_names(self, language):
        return {name: i for i, name in enumerate(MONTHS, 1)} | {name[:3]: i for i, name in enumerate(MONTHS, 1)}

    def ocr_language(self, code):
        return ISO639_2.get(code, code)


def env_locale(*variables):
    for name in variables:
        value = os.environ.get(name, "").split(":")[0].split(".")[0]
        if value and value not in ("C", "POSIX"):
            return value
    return ""


def _monetary_code(name):
    saved = pylocale.setlocale(pylocale.LC_MONETARY)
    try:
        pylocale.setlocale(pylocale.LC_MONETARY, name + ".UTF-8")
        return pylocale.localeconv()["int_curr_symbol"].strip()
    except (pylocale.Error, ValueError):
        return ""
    finally:
        pylocale.setlocale(pylocale.LC_MONETARY, saved)


def detect():
    ui = env_locale("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG") or "en_US"
    regional = env_locale("LC_ALL", "LC_ADDRESS", "LC_MONETARY", "LC_TELEPHONE", "LANG") or ui
    money = env_locale("LC_ALL", "LC_MONETARY", "LANG") or ui
    measure = env_locale("LC_ALL", "LC_MEASUREMENT", "LANG") or ui
    language = settings.LANGUAGE or regional.split("_")[0] or ui.split("_")[0]
    currency = (settings.CURRENCY or _monetary_code(money) or "USD").upper()
    country = regional.partition("_")[2][:2].upper()
    metric = settings.UNITS != "imperial" if settings.UNITS else measure.partition("_")[2][:2].upper() not in IMPERIAL
    return Locale("en", language.lower(), currency, metric, country)


_current = None


def install(locale):
    global _current
    _current = locale


def current():
    global _current
    if _current is None:
        _current = detect()
    return _current
