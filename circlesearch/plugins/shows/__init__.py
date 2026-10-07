import urllib.parse

from circlesearch.core.cards import Action
from circlesearch.core.net import get_json
from circlesearch.plugins.wikidata import work_extra

API = "https://api.tvmaze.com/"


@work_extra("series")
def series(info):
    ids = info["facts"]
    if ids.get("tvmaze"):
        url = f"{API}shows/{ids['tvmaze']}?embed=nextepisode"
    elif ids.get("imdb"):
        url = f"{API}lookup/shows?" + urllib.parse.urlencode({"imdb": ids["imdb"]})
    else:
        return None
    show = get_json(url)
    if not show:
        return None
    rows = []
    channel = (show.get("network") or show.get("webChannel") or {}).get("name")
    for label, value in (("Status", show.get("status")), ("Network", channel)):
        if value:
            rows.append((label, value))
    average = (show.get("rating") or {}).get("average")
    if average:
        rows.append(("Rating", f"{average:.1f} ★"))
    nxt = (show.get("_embedded") or {}).get("nextepisode") or {}
    if nxt.get("airdate"):
        rows.append(("Next episode", f"{nxt['airdate']}" + (f" · {nxt['name']}" if nxt.get("name") else "")))
    actions = [Action("TVmaze", "open", show["url"])] if show.get("url") else []
    if show.get("officialSite"):
        actions.insert(0, Action("Watch", "open", show["officialSite"]))
    poster = (show.get("image") or {}).get("medium")
    return rows, actions, poster
