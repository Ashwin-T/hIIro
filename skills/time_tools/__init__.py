"""Time/date skill."""
from datetime import datetime

TOOLS = [{
    "name": "get_current_time",
    "description": "Get the current local time and date.",
    "input_schema": {"type": "object", "properties": {}},
}]


def _get_time() -> dict:
    now = datetime.now()
    return {"time": now.strftime("%I:%M %p"), "date": now.strftime("%B %d, %Y"), "day": now.strftime("%A")}


def build(cfg) -> list[tuple[dict, object]]:
    return [(TOOLS[0], _get_time)]
