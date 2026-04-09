# hIIRO

The direct evolution of hiro: Ashwin's customizable smart room system.

Key new features:
Voice or terminal interfaces.
Agentic AI choosing to respond over pure text matching.
Only responds to **your voice** — everyone else gets ignored.
Core + Scalable skills

```
Mic → VAD → Speaker Verify → Transcribe → Claude → Speak
      (webrtcvad) (SpeechBrain ECAPA-TDNN) (Groq Whisper) (Haiku) (Groq Orpheus)
```

## Features

- **Voice-locked** — biometric speaker verification via [SpeechBrain ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) (0.69% EER). Only the enrolled voice gets through.
- **Always-on listening** — webrtcvad detects speech, buffers it, stops after 1.5s of silence. No wake word needed.
- **Agentic** — Claude Haiku runs a tool-use loop, calling skills (weather, stocks, Spotify, smart home, scheduling, etc.) autonomously until it has a full answer.
- **Fast** — Haiku for LLM, Groq Whisper for STT, Groq Orpheus for TTS. All cloud, ~2s end-to-end.
- **Extensible** — drop a Python file in `skills/`, add one line to the registry, done.
- **Scheduler** — schedule any skill or reminder to run at a time or on a recurring interval, persisted to disk.
- **Do Not Disturb** — mute all speech for a set duration.
- **Audio controls** — volume control, test tone, device status via voice commands.

## Quick start

```bash
# Prerequisites (Raspberry Pi OS)
sudo apt install portaudio19-dev libsndfile1 tmux

# Clone and install
git clone <repo-url> && cd hIIro
uv sync

# Configure
cp .env.example config/.env
# Edit config/.env — set ANTHROPIC_API_KEY and GROQ_API_KEY

# Run (first run auto-enrolls your voice — speak for 10 seconds)
uv run main.py                     # voice mode
uv run main.py --mode terminal     # text mode

# Run in background (survives SSH disconnect)
tmux new -s hiro "uv run main.py"
# Detach: Ctrl+B, D | Reattach: tmux attach -t hiro
```

## Requirements

- Raspberry Pi 5 (64-bit Pi OS) or any Linux with a mic
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) package manager
- A USB microphone
- A USB speaker/audio output
- An Anthropic API key
- A Groq API key

## Configuration

All settings live in `config/.env`. See [.env.example](.env.example) for the full list.

Key settings:
- `SPEAKER_THRESHOLD` — cosine similarity threshold for speaker verification (default 0.40, higher = stricter)
- `SPEAKER_PROFILE` — path to voice embedding file (default `config/voice_profile.npy`)

## Project structure

```
main.py           Entry point — voice loop, terminal mode, --enroll
agent.py          Claude Haiku agentic tool-use loop
config.py         Config dataclass, loads config/.env
stt.py            Full STT pipeline: pyaudio + webrtcvad + SpeechBrain + Groq Whisper
tts.py            Groq Orpheus TTS (cloud) with pyttsx3 fallback, DND support
skills/           Skill modules — auto-registered as Claude tools
  __init__.py     Skill registry (loads core + external skills)
  core/           Built-in skills (no API keys needed)
    device.py     CPU %, temp, memory, disk, uptime, audio test, volume
    dnd.py        Do Not Disturb — mute speech for a duration
    scheduler.py  Run skills or reminders on a schedule (persisted to disk)
    speedtest.py  Internet speed test
  time_tools/     Current time/date
  weather/        OpenWeatherMap current + forecast
  search/         DuckDuckGo instant answers
  stocks/         Finnhub quotes + news
  spotify/        Playback control via spotipy
  smarthome/      Zigbee2MQTT device control
config/
  .env            Secrets and settings (gitignored)
  voice_profile.npy  Enrolled speaker embedding (auto-created on first run)
  schedules.json  Persisted scheduled tasks
```

## Voice mode flow

1. **Listen** — pyaudio reads 30ms frames, webrtcvad detects speech
2. **Capture** — buffer speech frames, stop after 1.5s of consecutive silence
3. **Speaker verify** — SpeechBrain ECAPA-TDNN extracts a 192-dim embedding, compares cosine similarity against your enrolled profile
4. **Transcribe** — Groq Whisper (`whisper-large-v3-turbo`) converts speech to text
5. **Agent** — Claude Haiku processes the transcript, calling tools as needed in a loop
6. **Speak** — Groq Orpheus TTS speaks the response
7. **Follow-up window** — 6 seconds to ask a follow-up without needing to re-verify

## Speaker enrollment

On first run, hIIro detects no voice profile and prompts you to speak for 10 seconds. The ECAPA-TDNN embedding is saved to `config/voice_profile.npy`.

To re-enroll:
```bash
uv run main.py --enroll
```

## Adding a skill

1. Create `skills/my_skill.py`:

```python
TOOLS = [{
    "name": "my_tool",
    "description": "What this tool does.",
    "input_schema": {
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "..."},
        },
        "required": ["param"],
    },
}]

def _my_tool(param: str) -> dict:
    return {"result": f"got {param}"}

def build(cfg) -> list[tuple[dict, object]]:
    return [(TOOLS[0], _my_tool)]
```

2. Add `"skills.my_skill"` to the `_MODULES` list in `skills/__init__.py`

That's it — the agent will automatically offer the tool to Claude.

## CLI options

```
uv run main.py [OPTIONS]

  --mode {voice,terminal}   Interface mode (default: voice)
  --name NAME               Override assistant name
  --enroll                  Re-record voice profile
  --log-level LEVEL         DEBUG, INFO, WARNING, ERROR (default: INFO)
```

## License

MIT
