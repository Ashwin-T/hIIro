"""hIIro web server — FastAPI app factory."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

from server.hub import Hub
from server.ws import websocket_endpoint

if TYPE_CHECKING:
    from agent import Agent
    from config import Config
    from tts import TTS


def create_app(cfg: "Config", agent: "Agent", tts: "TTS") -> FastAPI:
    app = FastAPI(title="hIIro Hub")
    hub = Hub(agent, tts, cfg)

    @app.on_event("startup")
    async def startup() -> None:
        await hub.start()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await hub.stop()

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket_endpoint(websocket, hub)

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "devices": len(hub.devices),
            "device_list": [d.summary() for d in hub.devices.values()],
        }

    # Serve static files (web UI) — must be last so it doesn't shadow /ws or /health
    app.mount("/", StaticFiles(directory="static", html=True), name="static")

    return app
