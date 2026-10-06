import importlib
import importlib.util
import pkgutil
import threading
import traceback

PACKAGE = "circlesearch.plugins"

_lock = threading.RLock()
_loaded = set()
_failed = set()


def load(*parts):
    with _lock:
        package = importlib.import_module(PACKAGE)
        for info in pkgutil.iter_modules(package.__path__):
            base = f"{PACKAGE}.{info.name}"
            for part in ("", *parts):
                name = f"{base}.{part}" if part else base
                if name in _loaded or base in _failed:
                    continue
                _loaded.add(name)
                if part and not info.ispkg:
                    continue
                try:
                    if part and importlib.util.find_spec(name) is None:
                        continue
                    importlib.import_module(name)
                except Exception:
                    _failed.add(base)
                    print(f"plugins: {name} failed to load, skipping it", flush=True)
                    traceback.print_exc()
