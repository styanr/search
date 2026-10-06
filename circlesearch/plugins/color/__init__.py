import colorsys
import math
import re
from dataclasses import dataclass, field

from circlesearch.core.cards import Card
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer
from circlesearch.core.text import fmt

HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$", re.I)
FUNC = re.compile(r"^(rgba?|hsla?)\(\s*([^)]*)\)$", re.I)


@dataclass(kw_only=True)
class ColorCard(Card):
    kind = "color"

    swatch: str
    contrast: str = ""
    formats: list[tuple[str, str]] = field(default_factory=list)


@recognizer("color", order=30)
def parse_color(text):
    t = text.strip().rstrip(";,")
    m = HEX.match(t)
    if m and (t.startswith("#") or len(m.group(1)) in (6, 8) and re.search(r"\d", t) and re.search(r"[a-f]", t, re.I)):
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
        return r, g, b, a
    m = FUNC.match(t)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(2)) if p]
    if len(parts) < 3:
        return None

    def num(p, scale):
        return float(p[:-1]) / 100 * scale if p.endswith("%") else float(p.rstrip("deg"))
    a = num(parts[3], 1.0) if len(parts) > 3 else 1.0
    if m.group(1).lower().startswith("rgb"):
        r, g, b = (round(min(255, max(0, num(p, 255)))) for p in parts[:3])
    else:
        def unit(p):
            return min(1.0, max(0.0, num(p, 1.0) if p.endswith("%") else num(p, 1.0) / 100))
        rgb = colorsys.hls_to_rgb((num(parts[0], 360) % 360) / 360, unit(parts[2]), unit(parts[1]))
        r, g, b = (round(c * 255) for c in rgb)
    return r, g, b, a


def luminance(r, g, b):
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def oklch(r, g, b):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    A = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    B = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    C = math.hypot(A, B)
    H = math.degrees(math.atan2(B, A)) % 360 if C > 1e-4 else 0
    return L, C, H


@resolver("color")
def color_card(route):
    r, g, b, a = route.value
    hex_ = f"#{r:02X}{g:02X}{b:02X}" + (f"{round(a * 255):02X}" if a < 1 else "")
    hue, light, sat = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    L, C, H = oklch(r, g, b)
    lum = luminance(r, g, b)
    on_white, on_black = (1.05) / (lum + 0.05), (lum + 0.05) / 0.05
    better = ("white", on_white) if on_white >= on_black else ("black", on_black)
    grade = "AAA" if better[1] >= 7 else "AA" if better[1] >= 4.5 else "AA large" if better[1] >= 3 else "low"
    alpha = f" / {fmt(a, 2)}" if a < 1 else ""
    formats = [("HEX", hex_),
               ("RGB", f"rgb({r} {g} {b}{alpha})"),
               ("HSL", f"hsl({round(hue * 360) % 360} {round(sat * 100)}% {round(light * 100)}%{alpha})"),
               ("OKLCH", f"oklch({L * 100:.1f}% {C:.3f} {H:.1f}{alpha})")]
    return ColorCard(title=hex_, swatch=hex_, formats=formats, contrast=f"{better[1]:.1f}:1 on {better[0]} ({grade})")
