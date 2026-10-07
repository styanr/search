import os
import sys

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

CONFIG_PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "circle-search",
                           "config.toml")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "circle-search")

DEFAULTS = {
    "contact": "",
    "cards": True,
    "history": True,
    "gpu": "auto",
    "router": "local",
    "debug": False,
    "locale": {"language": "", "currency": "", "units": ""},
    "ocr": {"languages": []},
}
CHOICES = {"gpu": ("auto", "lite"), "locale.units": ("", "metric", "imperial")}


def warn(message):
    print(f"settings: {message}", file=sys.stderr)


def read(path):
    if not os.path.exists(path):
        return {}
    if tomllib is None:
        warn(f"reading {path} needs Python 3.11 or the tomli package, using the defaults")
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        warn(f"{path}: {e}, using the defaults")
        return {}


def valid(name, value, default):
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if type(value) is not type(default):
        return False
    return name not in CHOICES or value.lower() in CHOICES[name]


def merge(data, defaults, prefix=""):
    for key in data.keys() - defaults.keys():
        warn(f"unknown setting {prefix}{key}")
    result = {}
    for key, default in defaults.items():
        name = prefix + key
        value = data.get(key, default)
        if isinstance(default, dict):
            if not isinstance(value, dict):
                warn(f"{name} should be a table like [{name}]")
                value = {}
            result[key] = merge(value, default, name + ".")
        elif valid(name, value, default):
            result[key] = value
        else:
            hint = " or ".join(f'"{c}"' for c in CHOICES.get(name, ()) if c)
            warn(f"{name} = {value!r} is not valid{' (use ' + hint + ')' if hint else ''}, using the default")
            result[key] = default
    return result


def load(path=CONFIG_PATH):
    legacy = sorted(name for name in os.environ if name.startswith("CIRCLE_SEARCH_"))
    if legacy:
        warn(f"environment variables are no longer read ({', '.join(legacy)}), put them in {path}")
    return merge(read(path), DEFAULTS)


config = load()
CONTACT = config["contact"].strip()
CARDS = config["cards"]
HISTORY = config["history"]
GPU = config["gpu"].lower()
ROUTER = config["router"]
DEBUG = config["debug"]
LANGUAGE = config["locale"]["language"]
CURRENCY = config["locale"]["currency"]
UNITS = config["locale"]["units"].lower()
OCR_LANGUAGES = config["ocr"]["languages"]
