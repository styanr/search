import json
import os
import time

from circlesearch.core import settings

LIMIT = 300


def path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "circle-search", "history.jsonl")


def enabled():
    return settings.HISTORY


def add(kind, text):
    text = " ".join(text.split())
    if not enabled() or not text or len(text) > 2000:
        return
    entries = load(LIMIT * 2)
    if entries and entries[0]["text"] == text and entries[0]["kind"] == kind:
        return
    entries.insert(0, {"t": round(time.time()), "kind": kind, "text": text})
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
    q = query.lower().strip()
    for e in load():
        key = e["text"].lower()
        if key in seen or (q and q not in key):
            continue
        seen.add(key)
        out.append(e)
        if len(out) >= limit:
            break
    return out


def remove(text):
    entries = [e for e in load(LIMIT * 2) if e["text"] != text]
    if not os.path.exists(path()):
        return
    with open(path(), "w", encoding="utf-8") as f:
        for e in reversed(entries):
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def clear():
    try:
        os.unlink(path())
    except OSError:
        pass
