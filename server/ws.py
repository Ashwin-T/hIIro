"""WebSocket endpoint handler."""
from __future__ import annotations

import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from server import protocol as proto
from server.hub import Hub

log = logging.getLogger(__name__)


async def websocket_endpoint(ws: WebSocket, hub: Hub) -> None:
    await ws.accept()
    device_id: str | None = None

    try:
        while True:
            msg = await ws.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "register":
                device_id = msg.get("device_id") or f"web-{uuid.uuid4().hex[:8]}"
                room = msg.get("room", "")
                name = msg.get("name", "Web Client")
                mode = msg.get("mode", "voice")
                await hub.register(ws, device_id, room, name, mode)
                await ws.send_json(proto.registered(device_id))

            elif msg_type == "mode":
                if not device_id:
                    await ws.send_json(proto.error("Register first"))
                    continue
                await hub.set_mode(device_id, msg.get("mode", "voice"))

            elif msg_type == "text":
                if not device_id:
                    await ws.send_json(proto.error("Register first"))
                    continue
                content = msg.get("content", "").strip()
                if content:
                    await hub.handle_text(device_id, content)

            elif msg_type == "audio":
                if not device_id:
                    await ws.send_json(proto.error("Register first"))
                    continue
                data = msg.get("data", "")
                if data:
                    await hub.handle_audio(device_id, data)

            elif msg_type == "ping":
                await ws.send_json(proto.pong())

            else:
                await ws.send_json(proto.error(f"Unknown message type: {msg_type}"))

    except WebSocketDisconnect:
        log.info("Client disconnected: %s", device_id)
    except Exception as e:
        log.error("WebSocket error for %s: %s", device_id, e)
    finally:
        if device_id:
            await hub.unregister(device_id)
