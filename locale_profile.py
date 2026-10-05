import os
from dataclasses import dataclass

from PyQt6.QtCore import QLocale


def _locale(*variables):
    for name in variables:
        value = os.environ.get(name, "")
        value = value.split(":")[0].split(".")[0]
        if value and value not in ("C", "POSIX"):
            return QLocale(value)
    return QLocale.system()


def _code(locale):
    return QLocale.languageToCode(locale.language()) or "en"


@dataclass
class Profile:
    ui_language: str
    language: str
    currency: str
    metric: bool
    country: str
    money: QLocale

    def language_name(self, code):
        name = QLocale.languageToString(QLocale(code).language())
        return name if name and name != "C" else code


def detect():
    ui = _locale("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")
    regional = _locale("LC_ALL", "LC_ADDRESS", "LC_MONETARY", "LC_TELEPHONE", "LANG")
    money = _locale("LC_ALL", "LC_MONETARY", "LANG")
    measure = _locale("LC_ALL", "LC_MEASUREMENT", "LANG")
    ui_language = "en"
    language = os.environ.get("CIRCLE_SEARCH_LANGUAGE") or _code(regional) or _code(ui)
    currency = (os.environ.get("CIRCLE_SEARCH_CURRENCY")
                or money.currencySymbol(QLocale.CurrencySymbolFormat.CurrencyIsoCode) or "USD").upper()
    units = os.environ.get("CIRCLE_SEARCH_UNITS", "").lower()
    metric = units != "imperial" if units else measure.measurementSystem() == QLocale.MeasurementSystem.MetricSystem
    country = QLocale.territoryToCode(regional.territory()) or ""
    return Profile(ui_language, language.lower(), currency, metric, country, money)


PROFILE = detect()
