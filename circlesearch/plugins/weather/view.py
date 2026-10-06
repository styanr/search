from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFontMetrics

from circlesearch.plugins.weather import WeatherCard
from circlesearch.ui import tokens as T
from circlesearch.ui.cards import CardView, view
from circlesearch.ui.shapes import STARS, draw_weather_icon, glyph, star_path
from circlesearch.ui.theme import card_font

AQI_STATUS = [(20, "Good", "#0ca30c"), (40, "Fair", "#0ca30c"), (60, "Moderate", "#fab219"),
              (80, "Poor", "#ec835a"), (10 ** 6, "Very poor", "#d03b3b")]


@view(WeatherCard)
class WeatherView(CardView):
    def tint(self):
        return T.SKY_DAY if self.card.is_day else T.SKY_NIGHT

    def layout(self, p, targets):
        card, c, pad = self.card, self.c, self.PAD
        width = self.inner
        y = pad
        self.text(p, card.place, 15, 620, c["on_surface"], pad, y, width)
        if card.local_time:
            local = card.local_time + " local"
            tw = QFontMetrics(card_font(12.5, 520)).horizontalAdvance(local)
            if p:
                glyph(p, "clock", QRectF(pad + width - tw - 19, y + 2, 14, 14), c["on_surface_variant"])
            self.text(p, local, 12.5, 520, c["on_surface_variant"], pad, y + 1, width, align="right")
        y += 28
        icon = QRectF(pad - 4, y, 104, 104)
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 20))
            p.drawPath(star_path(icon, *STARS["cookie9"]))
            draw_weather_icon(p, card.code, icon.adjusted(22, 22, -22, -22), card.is_day)
        tx = icon.right() + 18
        self.text(p, f"{round(card.temperature)}°", 72, 430, c["on_surface"], tx, y - 8, 200, rond=100, wdth=105)
        self.text(p, card.condition, 16, 580, c["on_surface"], tx, y + 70, width - (tx - pad))
        today = card.days[0]
        sub = f"Feels {round(card.feels)}°  ·  H {round(today.hi)}°  L {round(today.lo)}°"
        self.text(p, sub, 13, 500, c["on_surface_variant"], tx, y + 92, width - (tx - pad))
        y = icon.bottom() + 14
        y = self.forecast(p, card.days, QRectF(pad, y, width, 0), targets) + 12
        x = pad
        if card.aqi is not None:
            word, dot = next((word, dot) for limit, word, dot in AQI_STATUS if card.aqi <= limit)
            x += self.pill(p, f"Air {word} · {card.aqi}", x, y, self.tile(), c["on_surface"], dot=dot) + 6
        for name, value in (("sunrise", card.sunrise), ("sunset", card.sunset)):
            x += self.pill(p, value, x, y, self.tile(), c["on_surface"], icon=name) + 6
        y += 30 + 14
        return self.source(p, y, targets) + pad - 4

    def forecast(self, p, days, area, targets):
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
        if p:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 255, 255, 16))
            p.drawRoundedRect(QRectF(area.left() + 2, area.top() - 4, col - 4, bottom - area.top() + 6), 16, 16)
        for i, d in enumerate(days):
            cx = area.left() + col * (i + 0.5)
            targets[f"day{i}"] = (QRectF(area.left() + col * i, area.top(), col, bottom - area.top()), None)
            if not p:
                continue
            p.setFont(card_font(12, 640 if i == 0 else 520)); p.setPen(c["on_surface"] if i == 0 else c["on_surface_variant"])
            p.drawText(QRectF(cx - col / 2, area.top(), col, day_h), Qt.AlignmentFlag.AlignCenter, d.label if i else "Now")
            draw_weather_icon(p, d.code, QRectF(cx - icon_h / 2, area.top() + day_h + 4, icon_h, icon_h), True)
            bar = QRectF(cx - 5, ty(d.hi), 10, max(10.0, ty(d.lo) - ty(d.hi)))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(self.MARK); p.drawRoundedRect(bar, 5, 5)
            p.setFont(card_font(12.5, 600)); p.setPen(c["on_surface"])
            if i == hot:
                p.drawText(QRectF(cx - col / 2, bar.top() - top_l, col, top_l - 2), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, f"{round(d.hi)}°")
            if i == cold:
                p.drawText(QRectF(cx - col / 2, bar.bottom() + 2, col, bot_l), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{round(d.lo)}°")
        return bottom
