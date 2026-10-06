import sys
import time

from circlesearch.core import locale
from circlesearch.core.pipeline import Pipeline


def main(args):
    try:
        from circlesearch.ui.qtlocale import QtLocale
        locale.install(QtLocale.detect())
    except ImportError:
        pass
    pipeline = Pipeline()
    for text in args or ["idempotent"]:
        start = time.perf_counter()
        extras = []
        timing = {}

        def routed(route, placeholder):
            timing["routed"] = time.perf_counter()
            print(f"{text!r}: {route.kind} (known word: {route.known_word}) via {pipeline.router.name}, "
                  f"routed in {(timing['routed'] - start) * 1000:.1f} ms")

        def card(info):
            print(f"  card in {(time.perf_counter() - start) * 1000:.0f} ms: {info}")

        pipeline.run(text, routed, card, extras.append)
        for info in extras:
            print(f"  extra {info.kind}: {info.title}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
