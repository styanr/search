import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from math import asin, cos, radians, sin, sqrt

from circlesearch.core.cards import Card
from circlesearch.core.locale import current
from circlesearch.core.net import get_bytes, get_json, safe
from circlesearch.core.pipeline import enricher

EVENT_WORDS = re.compile(r"\b(battle|siege|war|uprising|massacre|pogrom|fire|election|treaty|offensive|attack|"
                         r"bombing|riot|protest|strike|crash|disaster|earthquake)\b", re.I)


@dataclass
class Place:
    title: str
    distance: str
    description: str
    image: bytes | None
    url: str


@dataclass(kw_only=True)
class NearbyCard(Card):
    kind = "nearby"
    priority = 6
    accent = "blue"

    blurb: str = ""
    places: list[Place] = field(default_factory=list)


def distance_km(lat1, lon1, lat2, lon2):
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def show_distance(d):
    if not current().metric:
        miles = d * 0.621371
        return f"{d * 3280.84:.0f} ft" if miles < 0.2 else f"{miles:.1f} mi"
    return f"{d * 1000:.0f} m" if d < 1 else f"{d:.1f} km"


@enricher("nearby", needs={"lat", "lon"}, order=50)
def nearby(facts):
    zoom = facts.get("zoom", 15)
    if zoom < 9:
        return [], {}
    radius = 10000 if zoom <= 12 else 1500
    with ThreadPoolExecutor(2) as pool:
        geo_f = pool.submit(get_json, "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "format": "json", "generator": "geosearch", "ggscoord": f"{facts['lat']}|{facts['lon']}",
            "ggsradius": radius, "ggslimit": 20, "prop": "pageimages|description|coordinates",
            "piprop": "thumbnail", "pithumbsize": 120, "pilimit": 20}))
        voyage_f = pool.submit(safe, get_json, "https://en.wikivoyage.org/api/rest_v1/page/summary/"
                               + urllib.parse.quote(facts.get("title", "").replace(" ", "_"))) if zoom <= 12 else None
        geo = geo_f.result()
        voyage = voyage_f.result() if voyage_f else None
    pages = list(((geo or {}).get("query") or {}).get("pages", {}).values())
    places = []
    for p in pages:
        desc = p.get("description", "")
        if p.get("title") == facts.get("title") or EVENT_WORDS.search(p.get("title", "") + " " + desc):
            continue
        if not p.get("thumbnail") or not p.get("coordinates"):
            continue
        c = p["coordinates"][0]
        places.append((distance_km(facts["lat"], facts["lon"], c["lat"], c["lon"]), p["title"], desc,
                       p["thumbnail"]["source"]))
    places.sort()
    places = places[:5]
    if len(places) < 2:
        return [], {}
    with ThreadPoolExecutor(5) as pool:
        images = list(pool.map(lambda pl: safe(get_bytes, pl[3]), places))
    found = [Place(title, show_distance(dist), desc, img,
                   "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")))
             for (dist, title, desc, _), img in zip(places, images)]
    blurb = ""
    if voyage and voyage.get("type") == "standard":
        blurb = re.split(r"(?<=[.!?])\s+", voyage.get("extract", ""))[0]
    title = facts.get("title", "")
    return [NearbyCard(title=f"Around {facts.get('title', 'here')}", blurb=blurb, places=found,
                       source="Wikipedia" + (", Wikivoyage" if blurb else ""),
                       url=f"https://en.wikivoyage.org/wiki/{urllib.parse.quote(title)}" if blurb else "")], {}
