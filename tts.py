"""Text-to-speech — Groq Orpheus (cloud) with pyttsx3 fallback."""
from __future__ import annotations

import logging
import subprocess
import tempfile
import threading

log = logging.getLogger(__name__)


class TTS:
    def __init__(self, groq_api_key: str = "") -> None:
        self._groq = None
        self._local = None
        self._dnd = False
        self._dnd_timer: threading.Timer | None = None

        if groq_api_key:
            try:
                from groq import Groq
                self._groq = Groq(api_key=groq_api_key)
                log.info("TTS ready (Groq Orpheus)")
            except Exception as e:
                log.warning("Groq TTS init failed: %s, falling back to pyttsx3", e)
                self._init_local()
        else:
            self._init_local()

    def _init_local(self) -> None:
        import pyttsx3  # type: ignore
        self._local = pyttsx3.init()
        self._local.setProperty("rate", 175)
        log.info("TTS ready (pyttsx3 fallback)")

    def speak(self, text: str) -> None:
        if not text:
            return
        if self._dnd:
            log.debug("TTS suppressed (DND): '%s…'", text[:60])
            return

        if self._groq:
            if self._speak_groq(text):
                return
            log.warning("Groq TTS failed, falling back to pyttsx3")
            if not self._local:
                self._init_local()

        if self._local:
            self._speak_local(text)

    def _speak_groq(self, text: str) -> bool:
        try:
            # Orpheus has a 200 char limit — split long text into chunks
            chunks = self._chunk(text, 200)
            for chunk in chunks:
                resp = self._groq.audio.speech.create(
                    model="canopylabs/orpheus-v1-english",
                    voice="autumn",
                    input=chunk,
                    response_format="wav",
                )
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(resp.read())
                    f.flush()
                    subprocess.run(["aplay", "-q", f.name], check=True, timeout=30)
            return True
        except Exception as e:
            log.error("Groq TTS error: %s", e)
            return False

    @staticmethod
    def _chunk(text: str, limit: int) -> list[str]:
        """Split text into chunks at sentence boundaries, respecting the char limit."""
        if len(text) <= limit:
            return [text]
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Find last sentence break within limit
            cut = -1
            for sep in (". ", "! ", "? ", ", "):
                i = text.rfind(sep, 0, limit)
                if i > cut:
                    cut = i + len(sep)
            if cut <= 0:
                # No sentence break — hard cut at space
                cut = text.rfind(" ", 0, limit)
                if cut <= 0:
                    cut = limit
            chunks.append(text[:cut].strip())
            text = text[cut:].strip()
        return chunks

    def _speak_local(self, text: str) -> None:
        log.debug("TTS (local): '%s…'", text[:60])
        self._local.say(text)
        self._local.runAndWait()

    def set_dnd(self, enabled: bool, duration_minutes: float = 0) -> None:
        """Enable or disable Do Not Disturb. If duration > 0, auto-disables after that time."""
        if self._dnd_timer:
            self._dnd_timer.cancel()
            self._dnd_timer = None
        self._dnd = enabled
        if enabled and duration_minutes > 0:
            self._dnd_timer = threading.Timer(duration_minutes * 60, self._end_dnd)
            self._dnd_timer.daemon = True
            self._dnd_timer.start()
        log.info("DND %s%s", "ON" if enabled else "OFF",
                 f" for {duration_minutes}m" if enabled and duration_minutes else "")

    def _end_dnd(self) -> None:
        self._dnd = False
        self._dnd_timer = None
        log.info("DND auto-disabled")
