class Registry:
    def __init__(self, what):
        self.what = what
        self._items = {}

    def add(self, key, item, order=100):
        self._items.pop(key, None)
        self._items[key] = (order, item)
        return item

    def get(self, key, default=None):
        entry = self._items.get(key)
        return entry[1] if entry else default

    def __contains__(self, key):
        return key in self._items

    def keys(self):
        return [key for key, _ in sorted(self._items.items(), key=lambda kv: kv[1][0])]

    def __iter__(self):
        return iter([item for _, (_, item) in sorted(self._items.items(), key=lambda kv: kv[1][0])])

    def __repr__(self):
        return f"<{self.what} registry: {', '.join(map(str, self.keys()))}>"
