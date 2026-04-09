"""Configuration — single source of truth, loaded from config/.env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

for _p in (Path.cwd() / ".env", Path.cwd() / "config" / ".env"):
    if _p.exists():
        load_dotenv(_p)
        break


@dataclass
class Config:
    # Identity
    name: str = field(default_factory=lambda: os.getenv("ASSISTANT_NAME", "hiro"))

    # LLM
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    model: str             = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001"))
    max_tokens: int        = field(default_factory=lambda: int(os.getenv("MAX_TOKENS", "512")))
    max_history: int       = field(default_factory=lambda: int(os.getenv("MAX_HISTORY", "10")))

    # STT / Voice pipeline
    groq_api_key: str          = field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    speaker_threshold: float   = field(default_factory=lambda: float(os.getenv("SPEAKER_THRESHOLD", "0.40")))
    speaker_profile: str       = field(default_factory=lambda: os.getenv("SPEAKER_PROFILE", "config/voice_profile.npy"))

    # Skills
    openweather_api_key: str   = field(default_factory=lambda: os.getenv("OPENWEATHER_API_KEY", ""))
    default_location: str      = field(default_factory=lambda: os.getenv("DEFAULT_LOCATION", "Mountain View,CA,USA"))
    finnhub_api_key: str       = field(default_factory=lambda: os.getenv("FINNHUB_API_KEY", ""))
    spotify_client_id: str     = field(default_factory=lambda: os.getenv("SPOTIFY_CLIENT_ID", ""))
    spotify_client_secret: str = field(default_factory=lambda: os.getenv("SPOTIFY_CLIENT_SECRET", ""))
    spotify_redirect_uri: str  = field(default_factory=lambda: os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"))
    mqtt_broker: str           = field(default_factory=lambda: os.getenv("MQTT_BROKER", "localhost"))
    mqtt_port: int             = field(default_factory=lambda: int(os.getenv("MQTT_PORT", "1883")))

    def validate(self) -> None:
        if not self.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required — add it to config/.env")


cfg = Config()
