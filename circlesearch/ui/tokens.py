def hx(c): c = c.lstrip("#"); return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
def mixh(a, b, t):
    a, b = hx(a), hx(b); return "#%02X%02X%02X" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))
def lum(c):
    def ch(v):
        v /= 255; return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = hx(c); return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)
def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True); return (la + 0.05) / (lb + 0.05)

SURFACE, SURFACE_HIGH, ON_SURFACE, ON_VAR, PRIMARY = "#1B1C21", "#2B2D35", "#ECEDF3", "#A6A9B4", "#A8C7FA"
ON_PRIMARY = "#062E6F"
BLUE, RED, YELLOW, GREEN = "#4285F4", "#EA4335", "#FBBC05", "#34A853"
GOOGLE = [BLUE, RED, YELLOW, GREEN]
SCRIM = "#06080E"
HIGHLIGHT_LIGHT, HIGHLIGHT_DARK = "#C2D7FB", "#24406E"
TINT = {
    "blue": mixh(SURFACE, BLUE, 0.11), "green": mixh(SURFACE, GREEN, 0.10),
    "red": mixh(SURFACE, RED, 0.09), "amber": mixh(SURFACE, YELLOW, 0.08), "neutral": SURFACE}
TILE = {k: mixh(v, "#FFFFFF", 0.06) for k, v in TINT.items()}
PRIMARY_CONTAINER, ON_PRIMARY_CONTAINER = "#0842A0", "#D3E3FD"
TERTIARY_CONTAINER, ON_TERTIARY_CONTAINER = "#0F5223", "#C4EED0"
ERROR_CONTAINER, ON_ERROR_CONTAINER = "#8C1D18", "#F9DEDC"
AMBER_CONTAINER, ON_AMBER_CONTAINER = "#5C4300", "#FFDF9E"
NEUTRAL_CONTAINER = "#3A3C45"
FAMILY = {
    "blue": (PRIMARY_CONTAINER, ON_PRIMARY_CONTAINER), "green": (TERTIARY_CONTAINER, ON_TERTIARY_CONTAINER),
    "red": (ERROR_CONTAINER, ON_ERROR_CONTAINER), "amber": (AMBER_CONTAINER, ON_AMBER_CONTAINER),
    "neutral": (NEUTRAL_CONTAINER, ON_SURFACE)}
LINE = BLUE

TYPE = {
    "display_large": (72, 430), "display": (52, 520), "headline": (28, 640), "subhead": (18, 580),
    "title": (16, 620), "body": (14.5, 430), "body_small": (13, 480), "label": (12.5, 560),
    "caption": (11.5, 520), "button": (13, 600)}
PAD, GAP, SECTION = 20, 8, 14
RADIUS = {"hero": 32, "card": 24, "media": 20, "tile": 16, "chip": 8}
CHIP_H, CHIP_SMALL_H, BUTTON_H, ICON_BUTTON = 30, 26, 40, 36
HOVER_ALPHA, PRESS_ALPHA, BORDER_ALPHA = 16, 14, 16
SPRING_EFFECTS, SPRING_SPATIAL = (1600, 1.0), (800, 0.6)
SKY_DAY, SKY_NIGHT = mixh(SURFACE, BLUE, 0.22), mixh(SURFACE, "#5B4FC7", 0.16)

if __name__ == "__main__":
    rows = []
    for name, bg in [*(("tint " + k, v) for k, v in TINT.items()), *(("tile " + k, v) for k, v in TILE.items()),
                     ("sky day", SKY_DAY), ("sky night", SKY_NIGHT)]:
        rows.append((name, bg, contrast(ON_SURFACE, bg), contrast(ON_VAR, bg), contrast(PRIMARY, bg), contrast(BLUE, bg)))
    print(f"{'container':16s} {'hex':8s} on_surface on_var primary mark#4285F4")
    for r in rows:
        print(f"{r[0]:16s} {r[1]:8s} {r[2]:6.2f}   {r[3]:6.2f} {r[4]:6.2f}  {r[5]:6.2f}" + ("" if r[3] >= 4.5 and r[5] >= 3 else "   <-- check"))
    for n, bg, fg in [("primary container", PRIMARY_CONTAINER, ON_PRIMARY_CONTAINER),
                      ("tertiary container", TERTIARY_CONTAINER, ON_TERTIARY_CONTAINER),
                      ("error container", ERROR_CONTAINER, ON_ERROR_CONTAINER)]:
        print(f"{n:20s} {bg} text {fg}: {contrast(fg, bg):.2f}")
