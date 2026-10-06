import os

CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "circle-search")
CARDS = os.environ.get("CIRCLE_SEARCH_CARDS", "1") != "0"
DEBUG = os.environ.get("CIRCLE_SEARCH_DEBUG", "0") == "1"
ROUTER = os.environ.get("CIRCLE_SEARCH_ROUTER", "local")
CONTACT = os.environ.get("CIRCLE_SEARCH_CONTACT", "").strip()
OCR_LANGUAGES = os.environ.get("CIRCLE_SEARCH_OCR_LANGUAGES", "")
LANGUAGE = os.environ.get("CIRCLE_SEARCH_LANGUAGE", "")
CURRENCY = os.environ.get("CIRCLE_SEARCH_CURRENCY", "")
UNITS = os.environ.get("CIRCLE_SEARCH_UNITS", "").lower()
