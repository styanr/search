import math
import statistics
from dataclasses import dataclass

from circlesearch.core.registry import Registry


@dataclass
class Table:
    rows: list[list[str]]

    @property
    def columns(self):
        return max((len(r) for r in self.rows), default=0)

    def tsv(self):
        return "\n".join("\t".join(cell.replace("\t", " ") for cell in row) for row in self.rows)

    def markdown(self):
        if not self.rows:
            return ""
        n = self.columns
        rows = [row + [""] * (n - len(row)) for row in self.rows]

        def line(cells):
            return "| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |"
        return "\n".join([line(rows[0]), "| " + " | ".join("---" for _ in range(n)) + " |", *map(line, rows[1:])])


layouts = Registry("layout recognizer")


def layout(kind, order=100):
    def register(detect):
        layouts.add(kind, (kind, detect), order)
        return detect
    return register


def detect(text, words):
    if not words:
        return None
    for kind, find in layouts:
        try:
            value = find(text, words)
        except (ValueError, ZeroDivisionError, IndexError):
            continue
        if value is not None:
            return kind, value
    return None


def _height(words):
    return statistics.median(w.rect.h for w in words)


def char_width(words):
    chars = sum(len(w.text) for w in words)
    return sum(w.rect.w for w in words) / chars if chars else _height(words) * 0.5


def rows(words):
    if not words:
        return []
    tolerance = _height(words) * 0.55
    out = []
    for w in sorted(words, key=lambda w: (w.rect.y + w.rect.h / 2, w.rect.x)):
        cy = w.rect.y + w.rect.h / 2
        if out and abs(out[-1][0] - cy) <= tolerance:
            centre, members = out[-1]
            members.append(w)
            out[-1] = ((centre * (len(members) - 1) + cy) / len(members), members)
        else:
            out.append((cy, [w]))
    return [sorted(members, key=lambda w: w.rect.x) for _, members in out]


def gutters(lines, min_gap):
    spans = sorted((w.rect.x, w.rect.right) for line in lines for w in line)
    found, reach = [], spans[0][1]
    for start, end in spans[1:]:
        if start - reach >= min_gap:
            found.append((reach, start))
        reach = max(reach, end)
    return found


def table(words, min_rows=2, min_columns=2):
    lines = rows(words)
    if len(lines) < min_rows:
        return None
    h = _height(words)
    cuts = gutters(lines, max(h * 1.1, char_width(words) * 2.5))
    if len(cuts) + 1 < min_columns:
        return None
    edges = [(a + b) / 2 for a, b in cuts]
    grid = []
    for line in lines:
        cells = [[] for _ in range(len(edges) + 1)]
        for w in line:
            cells[sum(1 for e in edges if w.rect.x + w.rect.w / 2 > e)].append(w.text)
        grid.append([" ".join(c) for c in cells])
    filled = [sum(1 for c in row if c) for row in grid]
    if sum(1 for f in filled if f >= 2) < max(min_rows, len(grid) * 0.6):
        return None
    sizes = [len(c.split()) for row in grid for c in row if c]
    if statistics.mean(sizes) > 4.5:
        return None
    empty_columns = [i for i in range(len(edges) + 1) if not any(row[i] for row in grid)]
    grid = [[c for i, c in enumerate(row) if i not in empty_columns] for row in grid]
    return Table(grid) if len(grid[0]) >= min_columns else None


def grid(lines):
    words = [w for line in lines for w in line][:80]
    estimate = char_width(words) * 1.08
    left = min(w.rect.x for w in words)
    best = None
    for i in range(121):
        p = estimate * (0.85 + i * 0.003)
        for j in range(12):
            o = left - p * j / 12
            misses = 0.0
            for w in words:
                k = math.floor((w.rect.x - o) / p)
                over = w.rect.right - (o + (k + len(w.text)) * p)
                if over > p * 0.08:
                    misses += 1
                if len(w.text) >= 3:
                    misses += min(1.0, abs(w.rect.w - (len(w.text) - 0.3) * p) / p)
            score = (round(misses, 3), abs(p - estimate))
            if best is None or score < best[0]:
                best = (score, p, o)
    return best[1], best[2]


def code(words):
    lines = rows(words)
    if not lines:
        return ""
    p, o = grid(lines)
    h = _height(words)

    def cell(w):
        return math.floor((w.rect.x - o) / p)
    left = min(cell(line[0]) for line in lines)
    out = []
    previous_bottom = None
    for line in lines:
        top = min(w.rect.y for w in line)
        if previous_bottom is not None and top - previous_bottom > h * 1.4:
            out.append("")
        previous_bottom = max(w.rect.bottom for w in line)
        text = " " * max(0, cell(line[0]) - left)
        for prev, w in zip([None, *line], line):
            if prev is not None:
                text += " " * max(1, cell(w) - cell(prev) - len(prev.text))
            text += w.text
        out.append(text.rstrip())
    return "\n".join(out)
