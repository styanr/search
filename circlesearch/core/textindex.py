class TextIndex:
    def __init__(self):
        self.screen = None
        self.regions = []
        self.words = None

    @property
    def ready(self):
        return self.words is not None

    def set_screen(self, words):
        self.screen = words
        self._rebuild()

    def add_region(self, area, words):
        self.regions.append((area, words))
        self._rebuild()

    def _rebuild(self):
        covered, out = [], []
        for area, words in reversed(self.regions):
            out += [w for w in words if not any(c.contains(w.rect.center()) for c in covered)]
            covered.append(area)
        for w in self.screen or []:
            if not any(c.contains(w.rect.center()) for c in covered):
                out.append(w)
        self.words = sorted(out, key=lambda w: w.order)

    def covered(self, area):
        return any(r.contains(area) for r, _ in self.regions)

    def in_region(self, point):
        return any(r.contains(point) for r, _ in self.regions)

    def word_at(self, point):
        return next((w for w in self.words or [] if w.rect.adjusted(-3, -3, 3, 3).contains(point)), None)

    def words_in(self, area):
        return [w for w in self.words or [] if area.contains(w.rect.center())]
