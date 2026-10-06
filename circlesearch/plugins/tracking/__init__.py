import re
from dataclasses import dataclass

from circlesearch.core.cards import Action, TextCard
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer

S10 = re.compile(r"^[A-Z]{2}\d{9}[A-Z]{2}$")
TRACKERS = {"Nova Poshta": "https://novaposhta.ua/tracking/{}/",
            "Ukrposhta": "https://track.ukrposhta.ua/tracking_UA.html?barcode={}"}
FALLBACK = "https://parcelsapp.com/en/tracking/{}"


@dataclass(kw_only=True)
class TrackingCard(TextCard):
    kind = "tracking"


@recognizer("tracking", order=40)
def parse_tracking(text):
    t = re.sub(r"\s", "", text.strip()).upper()
    if re.fullmatch(r"(20|59)\d{12}", t):
        return ("Nova Poshta", t)
    if S10.match(t):
        return ("Ukrposhta" if t.endswith("UA") else "International mail", t)
    return None


@resolver("tracking")
def tracking_card(route):
    carrier, number = route.value
    url = TRACKERS.get(carrier, FALLBACK).format(number)
    return TrackingCard(title=number, description=f"{carrier} parcel",
                        actions=[Action("Track parcel", "open", url), Action("Copy number", "copy", number)])
