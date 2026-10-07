import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from circlesearch.core import settings

USER_AGENT = "circle-search/0.1 (personal desktop prototype)"
CONTACT_HOSTS = ("wikipedia.org", "wiktionary.org", "wikidata.org", "wikivoyage.org", "wikimedia.org",
                 "openstreetmap.org", "openlibrary.org", "musicbrainz.org")
TIMEOUT = 2.5
OPTIONAL_TIMEOUT = 1.2


def user_agent(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    if not any(host == h or host.endswith("." + h) for h in CONTACT_HOSTS):
        return USER_AGENT
    contact = settings.CONTACT or "https://www.mediawiki.org/wiki/API:Etiquette"
    return f"circle-search/0.1 (personal desktop prototype; {contact})"


def get_json(url, headers=None, timeout=TIMEOUT, retry=True):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(url), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if retry and e.code in (502, 503, 504):
            time.sleep(0.15)
            return get_json(url, headers, timeout, retry=False)
        raise


def get_bytes(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers={"User-Agent": user_agent(url)})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def safe(fn, *args):
    try:
        return fn(*args)
    except (OSError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError, OverflowError) as e:
        print(f"context: {fn.__name__} failed: {e}", file=sys.stderr)
        return None
