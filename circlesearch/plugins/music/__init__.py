import threading
import time
import urllib.parse

from circlesearch.core.cards import Action, Detail, Section
from circlesearch.core.net import get_json
from circlesearch.core.cards import Link
from circlesearch.plugins.wikidata import album_card, work_extra

API = "https://musicbrainz.org/ws/2/"
INTERVAL = 1.1

_lock = threading.Lock()
_last = [0.0]


def musicbrainz(path):
    with _lock:
        wait = _last[0] + INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return get_json(API + path + ("&" if "?" in path else "?") + "fmt=json")
        finally:
            _last[0] = time.monotonic()


@work_extra("album")
def album(info):
    group = info["facts"].get("mb_rg")
    if not group:
        return None
    rows = []
    rating = (musicbrainz(f"release-group/{group}?inc=ratings") or {}).get("rating") or {}
    if rating.get("value") and rating.get("votes-count", 0) >= 3:
        rows.append(("Rating", f"{rating['value']:.1f} ★ ({rating['votes-count']:,})"))
    actions = [Action("MusicBrainz", "open", f"https://musicbrainz.org/release-group/{group}")]
    return rows, actions + listen(info), None, [Section("Tracks", lambda: tracklist(group))]


@work_extra("song")
def song(info):
    return [], listen(info)


def listen(info):
    query = " ".join(x for x in (info["name"], info["people"]) if x)
    return [Action("YouTube Music", "open", "https://music.youtube.com/search?" + urllib.parse.urlencode({"q": query}))] \
        if query else []


def tracklist(group):
    releases = (musicbrainz(f"release?release-group={group}&inc=recordings&limit=1") or {}).get("releases") or []
    items = []
    for medium in (releases[0].get("media") or []) if releases else []:
        for track in medium.get("tracks") or []:
            ms = track.get("length") or (track.get("recording") or {}).get("length") or 0
            items.append((len(items) + 1, track.get("title", ""), f"{ms // 60000}:{ms // 1000 % 60:02d}" if ms else ""))
    return Detail("tracks", items) if items else None


@work_extra("artist")
def artist(info):
    mbid = info["facts"].get("mb_artist")
    if not mbid:
        return None
    name = info["name"]
    return [], [Action("MusicBrainz", "open", f"https://musicbrainz.org/artist/{mbid}")], None, \
        [Section("Albums", lambda: discography(mbid, name))]


def discography(mbid, name, limit=12):
    groups = (musicbrainz(f"release-group?artist={mbid}&type=album&limit=100") or {}).get("release-groups") or []
    studio = [g for g in groups if not g.get("secondary-types") and g.get("title")]
    studio.sort(key=lambda g: g.get("first-release-date") or "", reverse=True)
    items = [Link(g["title"], (g.get("first-release-date") or "")[:4],
                  lambda title=g["title"]: album_card(title, name), 448) for g in studio[:limit]]
    return Detail("works", items) if items else None
