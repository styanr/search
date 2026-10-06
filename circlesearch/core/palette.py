def _distance(a, b):
    return (a[0] - b[0]) ** 2 * 0.3 + (a[1] - b[1]) ** 2 * 0.59 + (a[2] - b[2]) ** 2 * 0.11


def dominant(pixels, k=6, rounds=8, min_share=0.05):
    pixels = [p[:3] for p in pixels]
    if not pixels:
        return []
    centres = [pixels[len(pixels) // 2]]
    while len(centres) < k:
        far = max(pixels, key=lambda p: min(_distance(p, c) for c in centres))
        if min(_distance(far, c) for c in centres) < 64:
            break
        centres.append(far)
    for _ in range(rounds):
        groups = [[] for _ in centres]
        for p in pixels:
            groups[min(range(len(centres)), key=lambda i: _distance(p, centres[i]))].append(p)
        centres = [tuple(sum(ch) / len(g) for ch in zip(*g)) if g else c for g, c in zip(groups, centres)]
    sized = sorted(((len(g), c) for g, c in zip(groups, centres) if len(g) >= len(pixels) * min_share), reverse=True)
    out = []
    for _, c in sized:
        c = tuple(round(v) for v in c)
        if all(_distance(c, o) >= 400 for o in out):
            out.append(c)
    return ["#%02X%02X%02X" % c for c in out]
