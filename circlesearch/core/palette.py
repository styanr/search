from collections import Counter


def _distance(a, b):
    return (a[0] - b[0]) ** 2 * 0.3 + (a[1] - b[1]) ** 2 * 0.59 + (a[2] - b[2]) ** 2 * 0.11


def _distances(colours, centre):
    cr, cg, cb = centre
    return [(r - cr) ** 2 * 0.3 + (g - cg) ** 2 * 0.59 + (b - cb) ** 2 * 0.11 for r, g, b in colours]


def dominant(pixels, k=6, rounds=8, min_share=0.05):
    pixels = [p[:3] for p in pixels]
    if not pixels:
        return []
    counts = Counter(pixels)
    colours, weights = list(counts), list(counts.values())
    centres = [pixels[len(pixels) // 2]]
    near = _distances(colours, centres[0])
    while len(centres) < k:
        reach = max(near)
        if reach < 64:
            break
        far = colours[near.index(reach)]
        centres.append(far)
        near = list(map(min, near, _distances(colours, far)))
    owner = None
    for _ in range(rounds):
        spans = [_distances(colours, c) for c in centres]
        last, owner = owner, [d.index(min(d)) for d in zip(*spans)]
        if owner == last:
            break
        sums = [[0, 0, 0, 0] for _ in centres]
        for (r, g, b), w, i in zip(colours, weights, owner):
            s = sums[i]
            s[0] += r * w
            s[1] += g * w
            s[2] += b * w
            s[3] += w
        sizes = [s[3] for s in sums]
        centres = [(s[0] / s[3], s[1] / s[3], s[2] / s[3]) if s[3] else c for s, c in zip(sums, centres)]
    sized = sorted(((n, c) for n, c in zip(sizes, centres) if n >= len(pixels) * min_share), reverse=True)
    out = []
    for _, c in sized:
        c = tuple(round(v) for v in c)
        if all(_distance(c, o) >= 400 for o in out):
            out.append(c)
    return ["#%02X%02X%02X" % c for c in out]
