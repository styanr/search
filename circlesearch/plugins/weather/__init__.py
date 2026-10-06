import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from circlesearch.core.cards import Card
from circlesearch.core.locale import current
from circlesearch.core.net import OPTIONAL_TIMEOUT, get_json, safe
from circlesearch.core.pipeline import enricher

WMO = [(0, "Clear"), (1, "Mostly clear"), (2, "Partly cloudy"), (3, "Cloudy"), (48, "Fog"), (57, "Drizzle"),
       (67, "Rain"), (77, "Snow"), (82, "Showers"), (86, "Snow showers"), (99, "Thunderstorm")]


@dataclass
class Day:
    label: str
    date: str
    hi: float
    lo: float
    rain: int | None
    text: str
    code: int


@dataclass(kw_only=True)
class WeatherCard(Card):
    kind = "weather"
    priority = 1

    place: str
    temperature: float
    feels: float
    condition: str
    code: int
    is_day: bool = True
    local_time: str = ""
    aqi: int | None = None
    sunrise: str = ""
    sunset: str = ""
    days: list[Day] = field(default_factory=list)


def condition(code):
    return next((w for c, w in WMO if (code or 0) <= c), "")


def forecast(lat, lon):
    return get_json("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode({
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "timezone": "auto", "forecast_days": 7,
        **({} if current().metric else {"temperature_unit": "fahrenheit"}),
        "current": "temperature_2m,weather_code,apparent_temperature,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"}))


def air_quality(lat, lon):
    data = get_json("https://air-quality-api.open-meteo.com/v1/air-quality?" + urllib.parse.urlencode(
        {"latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "current": "european_aqi"}), timeout=OPTIONAL_TIMEOUT)
    value = data["current"]["european_aqi"]
    return None if value is None else round(value)


@enricher("weather", needs={"lat", "lon"}, order=10)
def weather_week(facts):
    if facts.get("zoom", 15) < 9:
        return [], {}
    with ThreadPoolExecutor(1) as pool:
        aqi_f = pool.submit(safe, air_quality, facts["lat"], facts["lon"])
        data = forecast(facts["lat"], facts["lon"])
        aqi = aqi_f.result()
    d, cur = data["daily"], data["current"]
    days = []
    for i, day in enumerate(d["time"]):
        dt = date.fromisoformat(day)
        days.append(Day("Today" if i == 0 else dt.strftime("%a"), dt.strftime("%A %-d %B"),
                        d["temperature_2m_max"][i], d["temperature_2m_min"][i],
                        (d["precipitation_probability_max"] or [None] * 7)[i], condition(d["weather_code"][i]),
                        d["weather_code"][i]))
    local = datetime.now(timezone.utc).timestamp() + data.get("utc_offset_seconds", 0)
    place = facts.get("title", "this place")
    card = WeatherCard(title=f"Weather in {place}", place=place, temperature=cur["temperature_2m"],
                       feels=cur.get("apparent_temperature", cur["temperature_2m"]),
                       condition=condition(cur["weather_code"]), code=cur["weather_code"],
                       is_day=bool(cur.get("is_day", 1)),
                       local_time=datetime.fromtimestamp(local, timezone.utc).strftime("%H:%M"), aqi=aqi,
                       sunrise=d["sunrise"][0][-5:], sunset=d["sunset"][0][-5:], days=days, source="Open-Meteo",
                       url=f"https://open-meteo.com/en/docs#latitude={facts['lat']:.4f}&longitude={facts['lon']:.4f}")
    return [card], {"timezone": data.get("timezone", "")}
