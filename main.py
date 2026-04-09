"""
hiro — voice-locked agentic assistant.

Flow:
  Mic -> pyaudio -> webrtcvad -> resemblyzer (speaker ID) -> Groq Whisper -> Claude -> Orpheus TTS

Usage:
  uv run main.py                  # voice mode (default)
  uv run main.py --mode terminal  # text mode
  uv run main.py --enroll         # re-record voice profile
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hiro", description="hiro — voice-locked agentic assistant")
    p.add_argument("--mode", choices=["voice", "terminal"], default="voice")
    p.add_argument("--name", help="Override assistant name")
    p.add_argument("--enroll", action="store_true", help="Re-record voice profile")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


# ══════════════════════════════════════════════════════════════════════════════
# VOICE MODE
# ══════════════════════════════════════════════════════════════════════════════

FOLLOWUP_WINDOW = 6.0       # seconds to wait for follow-up after a response
SLEEP_COOLDOWN  = 2.0       # seconds to ignore mic after a sleep command

_SLEEP_PHRASES = {"goodbye", "bye", "go to sleep", "sleep", "stop", "quiet", "go away", "good night"}
_RESET_PHRASES = {"forget everything", "start over", "clear history", "new conversation", "reset"}

def _is_sleep(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _SLEEP_PHRASES)


def _is_reset(text: str) -> bool:
    t = text.lower()
    return any(p in t for p in _RESET_PHRASES)


def voice_loop(cfg, agent, tts):
    """Main voice loop: listen -> agent -> speak."""
    from stt import listen_for_command

    name = cfg.name
    print(f"\n{'=' * 50}")
    print(f"  {name} — always-on listening")
    print(f"{'=' * 50}\n")

    last_sleep = 0.0

    while True:
        # Cooldown after sleep command
        if time.monotonic() - last_sleep < SLEEP_COOLDOWN:
            time.sleep(0.1)
            continue

        # Block until speaker-verified speech -> transcript
        text = listen_for_command()
        if not text:
            continue

        log.info("User: %s", text)

        # Built-in commands
        if _is_sleep(text):
            tts.speak("Okay, going to sleep!")
            last_sleep = time.monotonic()
            continue

        if _is_reset(text):
            agent.clear()
            tts.speak("Memory cleared. What's next?")
            continue

        # Agent
        response = agent.run(text)
        log.info("%s: %s", name, response)
        tts.speak(response)

        # Follow-up window
        last_sleep = _followup(cfg, agent, tts)


def _followup(cfg, agent, tts):
    """Listen for follow-up questions (still speaker-verified)."""
    from stt import listen_for_command

    deadline = time.monotonic() + FOLLOWUP_WINDOW
    log.debug("Follow-up window open...")

    while time.monotonic() < deadline:
        text = listen_for_command()
        if not text:
            return 0.0  # silence — end follow-up window

        log.info("User (follow-up): %s", text)

        if _is_sleep(text):
            tts.speak("Okay, going to sleep!")
            return time.monotonic()

        if _is_reset(text):
            agent.clear()
            tts.speak("Memory cleared.")
            continue

        response = agent.run(text)
        log.info("%s: %s", cfg.name, response)
        tts.speak(response)
        deadline = time.monotonic() + FOLLOWUP_WINDOW

    return 0.0


# ══════════════════════════════════════════════════════════════════════════════
# TERMINAL MODE
# ══════════════════════════════════════════════════════════════════════════════

def terminal_loop(cfg, agent):
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt

    c = Console()
    name = cfg.name

    c.print(f"\n[bold cyan]{'─' * 50}")
    c.print(f"[bold cyan]  {name} — terminal mode")
    c.print(f"[bold cyan]{'─' * 50}\n")
    c.print("[dim]Commands: clear · history · exit[/dim]\n")

    while True:
        try:
            text = Prompt.ask("[bold blue]You[/bold blue]").strip()
        except (EOFError, KeyboardInterrupt):
            c.print("\n[cyan]Goodbye![/cyan]")
            break

        if not text:
            continue
        low = text.lower()
        if low in {"exit", "quit", "bye"}:
            c.print("\n[cyan]Goodbye![/cyan]")
            break
        if low == "clear":
            agent.clear()
            c.print("[green]✓[/green] Cleared")
            continue
        if low == "history":
            for i, m in enumerate(agent.history, 1):
                role = "[blue]You[/blue]" if m["role"] == "user" else f"[green]{name}[/green]"
                c.print(f"  {i}. {role}: {m['content']}")
            continue

        with c.status("[cyan]Thinking...[/cyan]", spinner="dots"):
            resp = agent.run(text)
        c.print(Panel(Markdown(resp), title=f"[bold green]{name}[/bold green]", border_style="green"))


# ══════════════════════════════════════════════════════════════════════════════
# ENROLLMENT
# ══════════════════════════════════════════════════════════════════════════════

def enroll_voice(cfg):
    """Force re-enrollment by deleting existing profile and triggering init."""
    profile = Path(cfg.speaker_profile)
    if profile.exists():
        profile.unlink()
        print("[deleted old voice profile]")
    from stt import init
    init(cfg)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY
# ══════════════════════════════════════════════════════════════════════════════

def main():
    args = _parser().parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
    )

    # Apply CLI overrides before loading config
    if args.name:
        os.environ["ASSISTANT_NAME"] = args.name

    from config import cfg
    cfg.validate()

    if args.enroll:
        enroll_voice(cfg)
        sys.exit(0)

    # ── Build the agent and register skills ───────────────────────────────
    prompt = ""
    if Path("system_prompt.txt").exists():
        prompt = Path("system_prompt.txt").read_text()

    from agent import Agent
    from skills import load_all

    agent = Agent(cfg, system_prompt=prompt)
    for tool_def, fn in load_all(cfg):
        agent.register(tool_def, fn)
    log.info("Registered %d skills", len(agent._tools))

    # ── Launch ────────────────────────────────────────────────────────────
    from skills.core.scheduler import _scheduler
    from skills.core.dnd import start as dnd_start

    if args.mode == "terminal":
        _scheduler.start(agent, None)
        terminal_loop(cfg, agent)
    else:
        from stt import init as stt_init
        from tts import TTS

        stt_init(cfg)  # loads profile, enrolls on first run
        tts_v = TTS(groq_api_key=cfg.groq_api_key)

        _scheduler.start(agent, tts_v)
        dnd_start(tts_v)
        voice_loop(cfg, agent, tts_v)


if __name__ == "__main__":
    main()
