import json
import os
import re
import time

from circlesearch.core import settings

LIMIT = 300
SHORT = 80


def path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "circle-search", "history.jsonl")


def enabled():
    return settings.HISTORY


def tidy(text):
    return " ".join(text.split()).strip("\"'()[]{}<>.,;:!?«»“”‘’")


def add(kind, text):
    text = tidy(text)
    if not enabled() or not text or len(text) > 2000:
        return
    entries = load(LIMIT * 2)
    if entries and entries[0]["text"] == text and entries[0]["kind"] == kind:
        return
    entries.insert(0, {"t": round(time.time()), "kind": kind, "text": text})
    _write(entries)


def _write(entries):
    os.makedirs(os.path.dirname(path()), exist_ok=True)
    tmp = path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for e in reversed(entries[:LIMIT]):
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    os.replace(tmp, path())


def load(limit=LIMIT):
    try:
        with open(path(), encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("text"):
            out.append(e)
        if len(out) >= limit:
            break
    return out


def recent(limit=8, query=""):
    seen, out = set(), []
    q = " ".join(query.lower().split())
    for e in load():
        text = tidy(e["text"])
        key = text.lower()
        if not key or key == q or key in seen or len(key) > SHORT or \
                (q and not re.search(r"(?:^|\W)" + re.escape(q), key)):
            continue
        seen.add(key)
        out.append({**e, "text": text})
        if len(out) >= limit:
            break
    return out


def remove(text):
    if os.path.exists(path()):
        _write([e for e in load(LIMIT * 2) if e["text"] != text])


def clear():
    try:
        os.unlink(path())
    except OSError:
        pass


def restore(entries):
    if entries:
        _write(load() + entries)
