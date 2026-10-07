import threading
import time

from circlesearch.core.cards import Action, Detail, Section
from circlesearch.core.net import get_json
from circlesearch.plugins.wikidata import work_extra

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
    return rows, actions, None, [Section("Tracks", lambda: tracklist(group))]


def tracklist(group):
    releases = (musicbrainz(f"release?release-group={group}&inc=recordings&limit=1") or {}).get("releases") or []
    items = []
    for medium in (releases[0].get("media") or []) if releases else []:
        for track in medium.get("tracks") or []:
            ms = track.get("length") or (track.get("recording") or {}).get("length") or 0
            items.append((len(items) + 1, track.get("title", ""), f"{ms // 60000}:{ms // 1000 % 60:02d}" if ms else ""))
    return Detail("tracks", items) if items else None
