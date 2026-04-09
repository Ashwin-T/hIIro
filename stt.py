"""
Speech-to-text pipeline — Pi 5 optimized.

mic -> pyaudio -> webrtcvad (speech?) -> SpeechBrain (your voice?) -> Groq Whisper -> trigger word check

On first run, prompts user to speak for 10 seconds to enroll their voice.
"""
from __future__ import annotations

import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import pyaudio
import torch
import webrtcvad

from config import Config

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit PCM
FRAME_MS = 30  # webrtcvad requires 10, 20, or 30 ms
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000)  # 480 samples
FRAME_BYTES = FRAME_SIZE * SAMPLE_WIDTH  # 960 bytes

VAD_MODE = 2  # 0-3, higher = more aggressive noise rejection
SILENCE_LIMIT = 50  # frames of silence to stop (~1.5 s at 30 ms)
MIN_SPEECH_FRAMES = 10  # ~300 ms minimum to count as real speech
MAX_RECORD_SEC = 10.0


# ══════════════════════════════════════════════════════════════════════════════
# Module-level state (initialized once via init())
# ══════════════════════════════════════════════════════════════════════════════

_pa: pyaudio.PyAudio | None = None
_vad: webrtcvad.Vad | None = None
_verifier = None  # SpeechBrain EncoderClassifier
_profile: np.ndarray | None = None
_groq_client = None
_speaker_threshold: float = 0.75
_profile_path: Path = Path("voice_profile.npy")


def init(cfg: Config) -> None:
    """One-time init of PyAudio, VAD, SpeechBrain, Groq, and voice profile."""
    global _pa, _vad, _verifier, _profile, _groq_client, _speaker_threshold, _profile_path

    if _pa is not None:
        return  # already initialized

    _speaker_threshold = cfg.speaker_threshold
    _profile_path = Path(cfg.speaker_profile)

    # PyAudio
    _pa = pyaudio.PyAudio()

    # WebRTC VAD
    _vad = webrtcvad.Vad(VAD_MODE)

    # SpeechBrain ECAPA-TDNN
    from speechbrain.inference.speaker import EncoderClassifier
    _verifier = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir="pretrained_models/spkrec-ecapa-voxceleb",
        run_opts={"device": "cpu"},
    )
    print("[SpeechBrain ECAPA-TDNN loaded]")

    # Groq
    if not cfg.groq_api_key:
        raise ValueError("GROQ_API_KEY is required — add it to config/.env")
    from groq import Groq
    _groq_client = Groq(api_key=cfg.groq_api_key)

    # Voice profile — enroll if missing
    if _profile_path.exists():
        _profile = np.load(_profile_path)
        print(f"[voice profile loaded from {_profile_path}]")
    else:
        print("[no voice profile found — starting enrollment]")
        _enroll()


# ══════════════════════════════════════════════════════════════════════════════
# Enrollment
# ══════════════════════════════════════════════════════════════════════════════

def _enroll() -> None:
    """Record 10 seconds, extract ECAPA-TDNN embedding, save and exit."""
    global _profile

    print("\n" + "=" * 50)
    print("  Voice Enrollment")
    print("=" * 50)
    print("\nSpeak naturally for 10 seconds so I can learn your voice.")
    input("Press Enter when ready... ")

    print("[recording 10s] ", end="", flush=True)
    stream = _pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=1024,
    )
    frames: list[bytes] = []
    for _ in range(int(SAMPLE_RATE / 1024 * 10)):
        frames.append(stream.read(1024, exception_on_overflow=False))
    stream.stop_stream()
    stream.close()
    print("done!")

    audio_f32 = (
        np.frombuffer(b"".join(frames), dtype=np.int16).astype(np.float32) / 32768.0
    )

    _profile = _embed(audio_f32)
    _profile_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(_profile_path, _profile)
    print(f"[voice profile saved to {_profile_path}]")
    print("[restart to begin normal operation]")
    raise SystemExit(0)


# ══════════════════════════════════════════════════════════════════════════════
# Speaker embedding + verification
# ══════════════════════════════════════════════════════════════════════════════

def _embed(audio_f32: np.ndarray) -> np.ndarray:
    """Extract a 192-dim ECAPA-TDNN embedding from float32 audio."""
    tensor = torch.from_numpy(audio_f32).unsqueeze(0)  # (1, samples)
    with torch.no_grad():
        emb = _verifier.encode_batch(tensor)  # (1, 1, 192)
    return emb.squeeze().numpy()


def _verify_speaker(audio_int16: np.ndarray) -> tuple[bool, float]:
    """Compare audio against saved profile. Returns (pass, similarity)."""
    if _profile is None:
        return True, 1.0

    audio_f32 = audio_int16.astype(np.float32) / 32768.0
    if len(audio_f32) < SAMPLE_RATE * 0.3:  # less than 300ms
        return False, 0.0

    emb = _embed(audio_f32)
    sim = float(
        np.dot(emb, _profile)
        / (np.linalg.norm(emb) * np.linalg.norm(_profile) + 1e-10)
    )
    return sim >= _speaker_threshold, sim


# ══════════════════════════════════════════════════════════════════════════════
# Groq Whisper transcription
# ══════════════════════════════════════════════════════════════════════════════

def _transcribe(audio_int16: np.ndarray) -> str | None:
    """Send int16 mono audio to Groq Whisper. Returns transcript or None."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            with wave.open(f.name, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_int16.tobytes())
            with open(f.name, "rb") as af:
                resp = _groq_client.audio.transcriptions.create(
                    file=("command.wav", af.read()),
                    model="whisper-large-v3-turbo",
                    response_format="json",
                    language="en",
                    temperature=0.0,
                )
        text = resp.text.strip()
        return text if text else None
    except Exception as e:
        print(f"[groq error: {e}]")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# Trigger word detection
# ══════════════════════════════════════════════════════════════════════════════

def _load_triggers() -> list[str]:
    """Load trigger phrases from config/triggers.txt, one per line."""
    path = Path("config/triggers.txt")
    lines = path.read_text().splitlines()
    return [l.strip().lower() for l in lines if l.strip() and not l.startswith("#")]


_triggers = _load_triggers()


def _strip_trigger(text: str) -> str | None:
    """If text starts with a trigger phrase, return the command after it. Else None."""
    low = text.lower().strip()
    for trigger in sorted(_triggers, key=len, reverse=True):  # longest match first
        if low.startswith(trigger):
            cmd = text[len(trigger):].strip().lstrip(".,!?").strip()
            return cmd if cmd else None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def listen_for_command() -> str | None:
    """
    Block until speech detected -> speaker verified -> transcript returned.
    Drop-in replacement for any existing record_until_silence() call.
    Must call init(cfg) before first use.
    """
    if _pa is None:
        raise RuntimeError("stt.init(cfg) must be called before listen_for_command()")

    stream = _pa.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=FRAME_SIZE,
    )
    print("[listening]")

    try:
        while True:
            data = stream.read(FRAME_SIZE, exception_on_overflow=False)

            if not _vad.is_speech(data, SAMPLE_RATE):
                continue

            # Speech started — capture full utterance
            frames: list[bytes] = [data]
            silence_count = 0
            speech_count = 1
            max_frames = int(MAX_RECORD_SEC * 1000 / FRAME_MS)

            for _ in range(max_frames):
                data = stream.read(FRAME_SIZE, exception_on_overflow=False)
                frames.append(data)

                if _vad.is_speech(data, SAMPLE_RATE):
                    speech_count += 1
                    silence_count = 0
                else:
                    silence_count += 1
                    if silence_count >= SILENCE_LIMIT:
                        break

            if speech_count < MIN_SPEECH_FRAMES:
                continue

            audio = np.frombuffer(b"".join(frames), dtype=np.int16)

            # 1) Speaker verify — is it your voice?
            t0 = time.monotonic()
            ok, sim = _verify_speaker(audio)
            t1 = time.monotonic()
            if not ok:
                print(f"[rejected sim={sim:.2f} {t1-t0:.2f}s]")
                continue

            # 2) Transcribe — what did you say?
            text = _transcribe(audio)
            t2 = time.monotonic()
            if not text:
                continue

            print(f"[you ({sim:.2f}): {text} | {t2-t0:.2f}s]")

            # 3) Trigger word check — fuzzy match "hiro" at the start
            cmd = _strip_trigger(text)
            if cmd is None:
                continue  # didn't say the trigger word

            print(f"[command: {cmd}]")
            return cmd
    finally:
        stream.stop_stream()
        stream.close()
