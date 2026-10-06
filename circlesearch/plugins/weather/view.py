from PyQt6.QtCore import QRectF, Qt

from circlesearch.plugins.weather import WeatherCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, Chip, view
from circlesearch.ui.shapes import STARS, draw_weather_icon, star_path
from circlesearch.ui.theme import C, type_font

AQI_STATUS = [(20, "Good", "#0ca30c"), (40, "Fair", "#0ca30c"), (60, "Moderate", "#fab219"),
              (80, "Poor", "#ec835a"), (10 ** 6, "Very poor", "#d03b3b")]


@view(WeatherCard)
class WeatherView(CardView):
    def tint(self):
        return T.SKY_DAY if self.card.is_day else T.SKY_NIGHT

    def layout(self, p, targets):
        card, pad = self.card, self.PAD
        y = self.header(p, pad, card.place, Chip(f"{card.local_time} local", "quiet", icon="clock") if card.local_time else None)
        icon = QRectF(pad - 4, y, 104, 104)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
            p.drawPath(star_path(icon, *STARS["cookie9"]))
            draw_weather_icon(p, card.code, icon.adjusted(22, 22, -22, -22), card.is_day)
        tx = icon.right() + 18
        tw = self.inner - (tx - pad)
        self.text(p, f"{round(card.temperature)}°", tx, y - 8, tw, "display_large", wdth=105)
        self.text(p, card.condition, tx, y + 70, tw, "title", weight=580)
        today = card.days[0]
        self.text(p, f"Feels {round(card.feels)}°  ·  H {round(today.hi)}°  L {round(today.lo)}°", tx, y + 92, tw,
                  "body_small", self.c["on_surface_variant"])
        y = icon.bottom() + T.SECTION
        y = self.forecast(p, card.days, QRectF(pad, y, self.inner, 0)) + T.SECTION
        chips = []
        if card.aqi is not None:
            word, dot = next((word, dot) for limit, word, dot in AQI_STATUS if card.aqi <= limit)
            chips.append(Chip(f"Air {word} · {card.aqi}", dot=dot))
        chips += [Chip(card.sunrise, icon="sunrise"), Chip(card.sunset, icon="sunset")]
        y = self.chip_row(p, chips, y)
        return self.footer(p, y, targets)

    def forecast(self, p, days, area):
        c = self.c
        n = len(days); col = area.width() / n
        lo, hi = min(d.lo for d in days), max(d.hi for d in days)
        span = max(hi - lo, 1.0)
        day_h, icon_h, top_l, bars_h, bot_l = 18, 26, 18, 70, 18
        y0 = area.top() + day_h + 4 + icon_h + 4 + top_l
        y1 = y0 + bars_h
        ty = lambda t: y1 - (t - lo) / span * bars_h
        hot = max(range(n), key=lambda i: days[i].hi); cold = min(range(n), key=lambda i: days[i].lo)
        bottom = y1 + bot_l
        if not p:
            return bottom
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(self.tile()))
        p.drawRoundedRect(QRectF(area.left() + 2, area.top() - 4, col - 4, bottom - area.top() + 6), T.RADIUS["tile"], T.RADIUS["tile"])
        for i, d in enumerate(days):
            cx = area.left() + col * (i + 0.5)
            p.setFont(type_font("caption", 640 if i == 0 else 520)); p.setPen(c["on_surface"] if i == 0 else c["on_surface_variant"])
            p.drawText(QRectF(cx - col / 2, area.top(), col, day_h), Qt.AlignmentFlag.AlignCenter, d.label if i else "Now")
            draw_weather_icon(p, d.code, QRectF(cx - icon_h / 2, area.top() + day_h + 4, icon_h, icon_h), True)
            bar = QRectF(cx - 5, ty(d.hi), 10, max(10.0, ty(d.lo) - ty(d.hi)))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(C(T.LINE)); p.drawRoundedRect(bar, 5, 5)
            p.setFont(type_font("label", 600)); p.setPen(c["on_surface"])
            if i == hot:
                p.drawText(QRectF(cx - col / 2, bar.top() - top_l, col, top_l - 2), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"{round(d.hi)}°")
            if i == cold:
                p.drawText(QRectF(cx - col / 2, bar.bottom() + 2, col, bot_l), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{round(d.lo)}°")
        return bottom
