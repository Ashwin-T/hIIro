"""Weather skill — OpenWeatherMap."""
from __future__ import annotations
from datetime import datetime, timedelta
from typing import Optional
import requests


TOOLS = [{
    "name": "get_weather",
    "description": "Get current or forecast weather. Leave location empty for default. when: now|tomorrow|tonight|weekend|week|day-name",
    "input_schema": {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "City name e.g. 'Paris'"},
            "when": {"type": "string", "description": "now, tomorrow, tonight, weekend, week, monday…", "default": "now"},
        },
    },
}]


def _make(api_key: str, default_loc: str):
    def get_weather(location: Optional[str] = None, when: str = "now") -> dict:
        if not api_key:
            return {"error": "OPENWEATHER_API_KEY not set"}
        loc = location if location and location.lower() not in {"", "current location", "here"} else default_loc
        w = (when or "now").lower().strip()

        try:
            if w in {"now", "current", "today", "right now"}:
                r = requests.get("http://api.openweathermap.org/data/2.5/weather",
                                 params={"q": loc, "appid": api_key, "units": "imperial"}, timeout=5)
                if r.status_code != 200:
                    return {"error": f"No weather for {loc}"}
                d = r.json()
                return {"location": d["name"], "temp": round(d["main"]["temp"]),
                        "feels_like": round(d["main"]["feels_like"]),
                        "condition": d["weather"][0]["description"],
                        "humidity": d["main"]["humidity"], "wind": round(d["wind"]["speed"])}

            r = requests.get("http://api.openweathermap.org/data/2.5/forecast",
                             params={"q": loc, "appid": api_key, "units": "imperial"}, timeout=5)
            if r.status_code != 200:
                return {"error": f"No forecast for {loc}"}
            data = r.json()
            today = datetime.now().date()
            days = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]

            if w in {"tomorrow","tmrw"}:       targets = [today + timedelta(1)]; label = "tomorrow"
            elif w in {"tonight","evening"}:   targets = [today]; label = "tonight"
            elif w in {"weekend"}:
                sat = today + timedelta((5 - today.weekday()) % 7 or 7)
                targets = [sat, sat + timedelta(1)]; label = "weekend"
            elif w in days:
                ahead = (days.index(w) - today.weekday()) % 7 or 7
                targets = [today + timedelta(ahead)]; label = w.capitalize()
            else:
                targets = [today + timedelta(i) for i in range(1, 6)]; label = "next 5 days"

            items = []
            for fc in data["list"]:
                dt = datetime.fromtimestamp(fc["dt"])
                if dt.date() in targets:
                    if w in {"tonight","evening"} and dt.hour < 18:
                        continue
                    items.append({"time": dt.strftime("%A %I%p"), "temp": round(fc["main"]["temp"]),
                                  "condition": fc["weather"][0]["description"]})
            return {"location": data["city"]["name"], "period": label, "forecasts": items[:8]}
        except requests.Timeout:
            return {"error": "Weather API timed out"}
        except Exception as e:
            return {"error": str(e)}
    return get_weather


def build(cfg) -> list[tuple[dict, object]]:
    return [(TOOLS[0], _make(cfg.openweather_api_key, cfg.default_location))]
