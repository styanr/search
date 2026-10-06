import math
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from circlesearch.core.cards import Action, HeroCard, MapTiles
from circlesearch.core.net import get_bytes, get_json, safe
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer

MAP_W, MAP_H, TILE = 416, 176, 256
ADDRESS = re.compile(
    r"\b(\d+[a-zа-я]?\s+[\w' .-]+\s(street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr|way|place|pl|square|sq)\b"
    r"|(вул\.?|вулиця|просп\.?|проспект|пл\.?|площа|бульв\.?|бульвар|пров\.?|провулок|узвіз)\s+[\w'’ .-]+,?\s*\d+"
    r"|\b\d{5}(-\d{4})?\b.*\b(USA|Ukraine|Україна|Deutschland|Germany|Poland|Polska)\b)", re.I)


@dataclass(kw_only=True)
class PlaceCard(HeroCard):
    kind = "place"


def map_tiles(lat, lon, zoom):
    n = 2 ** zoom
    cx = (lon + 180) / 360 * n * TILE
    lat_r = math.radians(lat)
    cy = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n * TILE
    x0, y0 = cx - MAP_W / 2, cy - MAP_H / 2
    tiles = [(tx, ty) for tx in range(int(x0 // TILE), int((x0 + MAP_W) // TILE) + 1)
             for ty in range(int(y0 // TILE), int((y0 + MAP_H) // TILE) + 1) if 0 <= ty < n]

    def fetch(t):
        tx, ty = t
        return tx * TILE - x0, ty * TILE - y0, get_bytes(f"https://tile.openstreetmap.org/{zoom}/{tx % n}/{ty}.png")

    with ThreadPoolExecutor(6) as pool:
        return MapTiles(MAP_W, MAP_H, list(pool.map(fetch, tiles)))


def zoom_for(description):
    full = (description or "").lower()
    head = re.split(r"\s+(?:in|of|on|near)\s+|,", full, maxsplit=1)[0]
    return _zoom_words(head) or _zoom_words(full) or 15


def _zoom_words(d):
    for words, zoom in ((("country", "sovereign"), 5), (("state of", "province", "oblast", "region", "island"), 7),
                        (("river", "lake", "mountain", "national park", "sea"), 9),
                        (("city", "capital", "town", "municipality", "village", "commune"), 11),
                        (("district", "neighbourhood", "neighborhood", "suburb"), 13)):
        if any(w in d for w in words):
            return zoom
    return None


def image_shape_for(description, zoom=15):
    d = (description or "").lower()
    if zoom <= 6:
        return "squircle"
    if any(w in d for w in ("software", "library", "framework", "programming language", "company", "organization",
                            "organisation", "brand", "website", "service")):
        return "logo_squircle"
    return "cookie9"


def place_actions(lat, lon, query, copy_text):
    q = query or f"{lat},{lon}"
    return [Action("Open in Maps", "open", "https://www.google.com/maps/search/?" + urllib.parse.urlencode({"api": 1, "query": q})),
            Action("Directions", "open", "https://www.google.com/maps/dir/?" + urllib.parse.urlencode({"api": 1, "destination": f"{lat},{lon}"})),
            Action("Copy", "copy", copy_text)]


def place_card(title, lat, lon, zoom, description="", definition="", source="", url="", query="", copy_text="",
               facts=None, image_url=None):
    with ThreadPoolExecutor(2) as pool:
        map_f = pool.submit(safe, map_tiles, lat, lon, zoom)
        img_f = pool.submit(safe, get_bytes, image_url) if image_url else None
        tiles, picture = map_f.result(), img_f.result() if img_f else None
    return PlaceCard(title=title, description=description, definition=definition,
                     image=picture, image_shape=image_shape_for(description, zoom), map=tiles,
                     actions=place_actions(lat, lon, query, copy_text or f"{lat:.5f}, {lon:.5f}"),
                     source=source, url=url,
                     facts={"lat": lat, "lon": lon, "title": title, "zoom": zoom, **(facts or {})})


@recognizer("address", order=110, max_chars=160, in_spans=False)
def parse_address(text):
    t = " ".join(text.split())
    return t if 8 <= len(t) <= 160 and ADDRESS.search(t) else None


@resolver("address", placeholder=True)
def address_card(route):
    q = route.value
    data = get_json("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 1, "accept-language": "uk,en"}))
    if not data:
        return None
    hit = data[0]
    parts = [s.strip() for s in hit["display_name"].split(",")]
    title = ", ".join(parts[:2]) if parts[0][:1].isdigit() else parts[0]
    zoom = {"building": 17, "house": 17, "road": 16, "street": 16, "suburb": 13, "city": 11,
            "town": 12, "village": 13}.get(hit.get("addresstype"), 16)
    return place_card(title, float(hit["lat"]), float(hit["lon"]), zoom,
                      description=", ".join(parts[2:4]), source="OpenStreetMap",
                      url=f"https://www.openstreetmap.org/?mlat={hit['lat']}&mlon={hit['lon']}#map={zoom}/{hit['lat']}/{hit['lon']}",
                      query=q, copy_text=hit["display_name"])
