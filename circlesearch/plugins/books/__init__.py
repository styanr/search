import urllib.parse

from circlesearch.core.cards import Action
from circlesearch.core.net import get_json
from circlesearch.plugins.wikidata import work_extra

FIELDS = "key,cover_i,ratings_average,ratings_count,number_of_pages_median"


@work_extra("book")
def open_library(info):
    if not info["name"]:
        return None
    query = {"title": info["name"], "limit": 1, "fields": FIELDS}
    if info["people"]:
        query["author"] = info["people"]
    docs = (get_json("https://openlibrary.org/search.json?" + urllib.parse.urlencode(query)) or {}).get("docs", [])
    if not docs:
        return None
    doc = docs[0]
    rows = []
    if doc.get("ratings_average") and doc.get("ratings_count", 0) >= 5:
        rows.append(("Rating", f"{doc['ratings_average']:.1f} ★ ({doc['ratings_count']:,})"))
    if doc.get("number_of_pages_median"):
        rows.append(("Pages", f"{doc['number_of_pages_median']:,}"))
    cover = f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-M.jpg" if doc.get("cover_i") else None
    return rows, [Action("Open Library", "open", "https://openlibrary.org" + doc["key"])], cover
