"""WebSocket message protocol definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Client → Server ──────────────────────────────────────────────────────────

@dataclass
class RegisterMsg:
    device_id: str
    room: str = ""
    name: str = ""

@dataclass
class TextMsg:
    content: str
    device_id: str = ""

@dataclass
class AudioMsg:
    data: str          # base64-encoded audio
    format: str = "webm-opus"
    device_id: str = ""


# ── Server → Client ─────────────────────────────────────────────────────────

def registered(device_id: str) -> dict:
    return {"type": "registered", "device_id": device_id}

def transcript(text: str, speaker_score: float = 0.0) -> dict:
    return {"type": "transcript", "text": text, "speaker_score": speaker_score}

def response(text: str) -> dict:
    return {"type": "response", "text": text}

def audio(data_b64: str, fmt: str = "wav") -> dict:
    return {"type": "audio", "format": fmt, "data": data_b64}

def debug_event(event: str, data: dict[str, Any]) -> dict:
    return {"type": "debug", "event": event, "data": data}

def error(message: str) -> dict:
    return {"type": "error", "message": message}

def pong() -> dict:
    return {"type": "pong"}

def device_list(devices: list[dict]) -> dict:
    return {"type": "devices", "devices": devices}
