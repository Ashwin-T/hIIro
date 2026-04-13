"""
Hub — central session manager and request queue.

One shared Agent brain, multiple thin clients. Requests are queued and
processed sequentially so concurrent mic inputs don't collide.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from server import protocol as proto

if TYPE_CHECKING:
    from agent import Agent
    from config import Config
    from tts import TTS
    from fastapi import WebSocket

log = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    device_id: str
    room: str
    name: str
    websocket: "WebSocket"
    mode: str = "voice"  # "voice" or "text"
    connected_at: datetime = field(default_factory=datetime.now)

    def summary(self) -> dict:
        return {
            "device_id": self.device_id,
            "room": self.room,
            "name": self.name,
            "mode": self.mode,
            "connected_at": self.connected_at.isoformat(),
        }


@dataclass
class _Request:
    device_id: str
    text: str | None = None
    audio_bytes: bytes | None = None


class Hub:
    def __init__(self, agent: "Agent", tts: "TTS", cfg: "Config") -> None:
        self.agent = agent
        self.tts = tts
        self.cfg = cfg
        self.devices: dict[str, DeviceInfo] = {}
        self._queue: asyncio.Queue[_Request] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

        # Wire agent debug events to broadcast
        self.agent.set_debug_callback(self._on_agent_debug)
        self._current_device_id: str | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_event_loop()
        self._worker = asyncio.create_task(self._process_queue())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()

    # ── Device management ────────────────────────────────────────────────

    async def register(self, ws: "WebSocket", device_id: str, room: str, name: str, mode: str = "voice") -> None:
        # If this device ID already exists, close the stale connection
        old = self.devices.get(device_id)
        if old:
            try:
                await old.websocket.close()
            except Exception:
                pass
        self.devices[device_id] = DeviceInfo(
            device_id=device_id, room=room, name=name, websocket=ws, mode=mode,
        )
        log.info("Device registered: %s (%s / %s)", device_id, room, name)
        await self._broadcast_device_list()

    async def set_mode(self, device_id: str, mode: str) -> None:
        dev = self.devices.get(device_id)
        if dev:
            dev.mode = mode
            log.info("Device %s switched to %s mode", device_id, mode)

    async def unregister(self, device_id: str) -> None:
        self.devices.pop(device_id, None)
        log.info("Device unregistered: %s", device_id)
        await self._broadcast_device_list()

    async def _broadcast_device_list(self) -> None:
        msg = proto.device_list([d.summary() for d in self.devices.values()])
        for dev in list(self.devices.values()):
            try:
                await dev.websocket.send_json(msg)
            except Exception:
                pass

    # ── Incoming requests ────────────────────────────────────────────────

    async def handle_text(self, device_id: str, text: str) -> None:
        await self._queue.put(_Request(device_id=device_id, text=text))

    async def handle_audio(self, device_id: str, audio_b64: str) -> None:
        audio_bytes = base64.b64decode(audio_b64)
        await self._queue.put(_Request(device_id=device_id, audio_bytes=audio_bytes))

    # ── Queue worker ─────────────────────────────────────────────────────

    async def _process_queue(self) -> None:
        loop = asyncio.get_event_loop()
        while True:
            req = await self._queue.get()
            self._current_device_id = req.device_id
            try:
                await self._handle_request(req, loop)
            except Exception as e:
                log.error("Request failed: %s", e)
                await self._send(req.device_id, proto.error(str(e)))
            finally:
                self._current_device_id = None
                self._queue.task_done()

    async def _handle_request(self, req: _Request, loop: asyncio.AbstractEventLoop) -> None:
        text = req.text

        # Audio → transcribe
        if req.audio_bytes:
            await self._send_debug(req.device_id, "stt_start", {})
            t0 = time.monotonic()
            wav_bytes = await self._convert_audio(req.audio_bytes)
            text = await loop.run_in_executor(None, self._transcribe, wav_bytes)
            stt_ms = int((time.monotonic() - t0) * 1000)
            if not text:
                await self._send(req.device_id, proto.error("Could not transcribe audio"))
                return
            await self._send_debug(req.device_id, "stt_done", {"text": text, "latency_ms": stt_ms})
            await self._send(req.device_id, proto.transcript(text))

        if not text:
            return

        # Get device info for context
        dev = self.devices.get(req.device_id)
        room_ctx = f" [from {dev.room}]" if dev and dev.room else ""

        # Agent response (blocking — run in executor)
        await self._send_debug(req.device_id, "llm_start", {})
        t0 = time.monotonic()
        response_text = await loop.run_in_executor(
            None, self.agent.run, text, req.device_id
        )
        llm_ms = int((time.monotonic() - t0) * 1000)
        await self._send_debug(req.device_id, "llm_done", {"latency_ms": llm_ms})

        # Send text response
        await self._send(req.device_id, proto.response(response_text))

        # Synthesize and send audio — only in voice mode
        dev = self.devices.get(req.device_id)
        if dev and dev.mode == "voice":
            await self._send_debug(req.device_id, "tts_start", {})
            t0 = time.monotonic()
            wav_data = await loop.run_in_executor(None, self.tts.synthesize, response_text)
            tts_ms = int((time.monotonic() - t0) * 1000)
            await self._send_debug(req.device_id, "tts_done", {"latency_ms": tts_ms})

            if wav_data:
                audio_b64 = base64.b64encode(wav_data).decode()
                await self._send(req.device_id, proto.audio(audio_b64))

    # ── Audio conversion ─────────────────────────────────────────────────

    async def _convert_audio(self, raw_bytes: bytes) -> bytes:
        """Convert browser audio (webm/opus) to 16kHz mono WAV via ffmpeg."""
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", "pipe:0",
            "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=raw_bytes)
        if proc.returncode != 0:
            log.error("ffmpeg error: %s", stderr.decode()[-200:])
            raise RuntimeError("Audio conversion failed")
        return stdout

    def _transcribe(self, wav_bytes: bytes) -> str | None:
        from stt import transcribe_bytes
        return transcribe_bytes(wav_bytes)

    # ── Send helpers ─────────────────────────────────────────────────────

    async def _send(self, device_id: str, msg: dict) -> None:
        dev = self.devices.get(device_id)
        if dev:
            try:
                await dev.websocket.send_json(msg)
            except Exception:
                log.warning("Failed to send to %s", device_id)

    async def _send_debug(self, device_id: str, event: str, data: dict) -> None:
        await self._send(device_id, proto.debug_event(event, data))

    def _on_agent_debug(self, event: str, data: dict) -> None:
        """Sync callback from Agent — schedule async send on the main event loop."""
        dev_id = self._current_device_id
        if dev_id and hasattr(self, "_loop"):
            try:
                self._loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._send_debug(dev_id, event, data),
                )
            except Exception:
                pass
