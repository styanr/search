import sys
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable

from circlesearch.core import plugins
from circlesearch.core.net import safe
from circlesearch.core.registry import Registry
from circlesearch.core.routing import Route, default_router

ENRICH_DEADLINE = 6.0


@dataclass
class Resolver:
    kind: str
    run: Callable
    placeholder: bool = False


resolvers = Registry("resolver")


def resolver(*kinds, placeholder=False):
    def register(run):
        for kind in kinds:
            resolvers.add(kind, Resolver(kind, run, placeholder))
        return run
    return register


@dataclass
class Enricher:
    name: str
    needs: frozenset
    run: Callable


enrichers = Registry("enricher")


def enricher(name, needs, order=100):
    def register(run):
        enrichers.add(name, Enricher(name, frozenset(needs), run), order)
        return run
    return register


def resolve(route):
    r = resolvers.get(route.kind)
    if r is None or not route.text:
        return None
    return safe(r.run, route)


def enrich(facts, emit, deadline=ENRICH_DEADLINE, cancelled=lambda: False, using=None):
    facts = dict(facts)
    pending = list(enrichers if using is None else using)
    end = time.monotonic() + deadline
    pool = ThreadPoolExecutor(6)
    running = {}

    def launch():
        for e in [e for e in pending if e.needs <= facts.keys()]:
            pending.remove(e)
            running[pool.submit(safe, e.run, dict(facts))] = e

    try:
        launch()
        while running and time.monotonic() < end and not cancelled():
            done, _ = wait(running, timeout=max(0.0, end - time.monotonic()), return_when=FIRST_COMPLETED)
            for f in done:
                running.pop(f)
                result = f.result()
                if not result:
                    continue
                cards, new_facts = result
                facts.update(new_facts or {})
                for card in cards:
                    if not cancelled():
                        emit(card)
            launch()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


class Job:
    def __init__(self):
        self._cancelled = threading.Event()

    def cancel(self):
        self._cancelled.set()

    @property
    def cancelled(self):
        return self._cancelled.is_set()


class Pipeline:
    def __init__(self, router=None):
        self._router = router

    @property
    def router(self):
        if self._router is None:
            plugins.load()
            self._router = default_router()
        return self._router

    def route(self, text):
        try:
            return self.router.route(text)
        except Exception as e:
            print(f"context: router {self.router.name!r} failed: {e}", file=sys.stderr)
            return Route("not_text")

    def run(self, text, on_route, on_card, on_extra, job=None):
        job = job or Job()
        route = self.route(text)
        r = resolvers.get(route.kind)
        if job.cancelled:
            return
        on_route(route, bool(r and r.placeholder))
        try:
            card = resolve(route)
        except Exception:
            traceback.print_exc()
            card = None
        if card is None:
            print(f"context: no card for {text!r} (routed as {route.kind}, text {route.text!r})", file=sys.stderr)
        if job.cancelled:
            return
        on_card(card)
        if card is not None and card.facts:
            enrich(card.facts, on_extra, cancelled=lambda: job.cancelled)

    def start(self, text, on_route, on_card, on_extra):
        job = Job()
        threading.Thread(target=self.run, args=(text, on_route, on_card, on_extra, job), daemon=True).start()
        return job
