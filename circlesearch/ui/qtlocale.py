import os
from dataclasses import dataclass, field

from PyQt6.QtCore import QLocale

from circlesearch.core import settings
from circlesearch.core.locale import Locale


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
class QtLocale(Locale):
    money: QLocale = field(default_factory=QLocale)

    @classmethod
    def detect(cls, overrides=True):
        ui = _locale("LC_ALL", "LC_MESSAGES", "LANGUAGE", "LANG")
        regional = _locale("LC_ALL", "LC_ADDRESS", "LC_MONETARY", "LC_TELEPHONE", "LANG")
        money = _locale("LC_ALL", "LC_MONETARY", "LANG")
        measure = _locale("LC_ALL", "LC_MEASUREMENT", "LANG")
        language = overrides and settings.LANGUAGE or _code(regional) or _code(ui)
        currency = (overrides and settings.CURRENCY
                    or money.currencySymbol(QLocale.CurrencySymbolFormat.CurrencyIsoCode) or "USD").upper()
        metric = settings.UNITS != "imperial" if overrides and settings.UNITS else \
            measure.measurementSystem() == QLocale.MeasurementSystem.MetricSystem
        country = QLocale.territoryToCode(regional.territory()) or ""
        return cls("en", language.lower(), currency, metric, country, money)

    def currency_symbol(self):
        return self.money.currencySymbol()

    def format_money(self, amount, symbol, decimals=2):
        return self.money.toCurrencyString(amount, symbol, decimals)

    def format_number(self, value, decimals):
        return self.money.toString(float(value), "f", decimals)

    def language_name(self, code):
        name = QLocale.languageToString(QLocale(code).language())
        return name if name and name != "C" else code

    def month_names(self, language):
        loc = QLocale(QLocale.Language.English) if language == "en" else QLocale(language)
        names = {}
        for i in range(1, 13):
            for fmt in (QLocale.FormatType.LongFormat, QLocale.FormatType.ShortFormat):
                for name in (loc.monthName(i, fmt), loc.standaloneMonthName(i, fmt)):
                    if name:
                        names[name.lower().rstrip(".")] = i
        return names

    def ocr_language(self, code):
        return QLocale.languageToCode(QLocale(code).language(), QLocale.LanguageCodeType.ISO639Part2T)
