import re
from dataclasses import dataclass

from circlesearch.core.cards import TextCard
from circlesearch.core.locale import current
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer
from circlesearch.core.text import fmt, parse_number

TO_METRIC = [
    (r"mi|miles?", "km", 1.609344), (r"ft|feet|foot", "m", 0.3048), (r"in|inch(?:es)?|″|\"", "cm", 2.54),
    (r"yd|yards?", "m", 0.9144), (r"lbs?|pounds?", "kg", 0.45359237), (r"oz|ounces?", "g", 28.349523125),
    (r"fl\.?\s?oz", "ml", 29.5735295625), (r"gal(?:lons?)?", "L", 3.785411784), (r"qt|quarts?", "L", 0.946352946),
    (r"cups?", "ml", 240.0), (r"mph", "km/h", 1.609344), (r"sq\.?\s?ft|ft²|square\s+feet", "m²", 0.09290304),
    (r"acres?", "ha", 0.40468564224),
    (r"°\s?F|degrees?\s+fahrenheit|fahrenheit", "°C", lambda f: (f - 32) * 5 / 9),
]
TO_IMPERIAL = [
    (r"km|kilomet(?:er|re)s?", "mi", 0.621371), (r"m|met(?:er|re)s?", "ft", 3.28084), (r"cm|centimet(?:er|re)s?", "in", 0.393701),
    (r"kg|kilos?|kilograms?", "lb", 2.20462), (r"g|grams?", "oz", 0.035274), (r"l|litres?|liters?", "gal", 0.264172),
    (r"ml|millilit(?:er|re)s?", "fl oz", 0.033814), (r"km/h|kph", "mph", 0.621371), (r"m²|sq\.?\s?m", "sq ft", 10.7639),
    (r"ha|hectares?", "acres", 2.47105), (r"°\s?C|degrees?\s+celsius|celsius", "°F", lambda c: c * 9 / 5 + 32),
]
QUANTITY = re.compile(r"^(?P<num>-?\d[\d,]*(?:\.\d+)?)\s?(?P<unit>.+)$", re.I)
FEET_INCHES = re.compile(r"^(\d+)\s?(?:'|′|ft|feet)\s?(\d+(?:\.\d+)?)\s?(?:\"|″|in|inches)?$", re.I)


@dataclass(kw_only=True)
class QuantityCard(TextCard):
    kind = "quantity"
    title_role = "query"


@recognizer("quantity", order=80)
def parse_quantity(text):
    t = text.strip()
    metric = current().metric
    m = FEET_INCHES.match(t)
    if m and metric:
        return float(m.group(1)) * 30.48 + float(m.group(2)) * 2.54, "cm"
    m = QUANTITY.match(t)
    if not m:
        return None
    for pattern, unit, conv in (TO_METRIC if metric else TO_IMPERIAL):
        if re.fullmatch(pattern, m.group("unit").strip(), re.I):
            n = parse_number(m.group("num")) if "," in m.group("num") else float(m.group("num"))
            return conv(n) if callable(conv) else n * conv, unit
    return None


@resolver("quantity")
def quantity_card(route):
    value, unit = route.value
    shown = f"{fmt(value, 1 if unit in ('°C', '°F', 'cm', 'in') else 2)} {unit}"
    rows = []
    if unit == "cm" and value >= 100:
        rows.append(("Metres", f"{fmt(value / 100, 2)} m"))
    if unit == "km":
        rows.append(("Metres", f"{fmt(value * 1000, 0)} m"))
    return QuantityCard(title=route.text, value=shown, rows=rows)
