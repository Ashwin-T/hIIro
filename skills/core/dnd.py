"""Do Not Disturb skill — mute all speech for a given duration."""
from __future__ import annotations

TOOLS = [
    {
        "name": "do_not_disturb",
        "description": "Enable or disable Do Not Disturb mode. When on, all speech is silenced.",
        "input_schema": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "description": "True to enable DND, false to disable."},
                "duration_minutes": {
                    "type": "number",
                    "description": "Auto-disable after this many minutes. 0 = indefinite until manually turned off.",
                    "default": 0,
                },
            },
            "required": ["enabled"],
        },
    },
]

_tts = None


def start(tts) -> None:
    """Wire up TTS reference after it's created in main."""
    global _tts
    _tts = tts


def _do_not_disturb(enabled: bool, duration_minutes: float = 0) -> dict:
    if _tts is None:
        return {"error": "TTS not connected — DND unavailable"}
    _tts.set_dnd(enabled, duration_minutes)
    if enabled:
        msg = "Do Not Disturb enabled"
        if duration_minutes:
            msg += f" for {duration_minutes} minutes"
        return {"status": msg}
    return {"status": "Do Not Disturb disabled"}


def build(cfg) -> list[tuple[dict, object]]:
    return [(TOOLS[0], _do_not_disturb)]
