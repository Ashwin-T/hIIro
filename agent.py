"""
Claude Haiku agentic loop.

Calls tools in a loop until Claude returns a final text response.
Skills register themselves as Anthropic tool-use definitions + callables.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

import anthropic

from config import Config

log = logging.getLogger(__name__)


class Agent:
    def __init__(self, cfg: Config, system_prompt: str = "") -> None:
        self.cfg = cfg
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        self.history: list[dict] = []
        self.system = system_prompt or (
            f"You are {cfg.name}, a fast and helpful voice assistant. "
            "Keep responses concise — 1-3 sentences. Use tools when they help. "
            "Respond in plain speech, no markdown or bullet points."
        )
        self._tools: list[dict] = []
        self._fns: dict[str, Callable] = {}

    # ── Skill registration ────────────────────────────────────────────────────

    def register(self, tool_def: dict, fn: Callable) -> None:
        self._tools.append(tool_def)
        self._fns[tool_def["name"]] = fn

    # ── Conversation ──────────────────────────────────────────────────────────

    def clear(self) -> None:
        self.history.clear()

    def _trim(self) -> None:
        limit = self.cfg.max_history * 2
        if len(self.history) > limit:
            self.history = self.history[-limit:]

    # ── Core loop ─────────────────────────────────────────────────────────────

    def run(self, user_input: str) -> str:
        """Full agentic turn: user text → tool calls → final response."""
        messages = list(self.history) + [{"role": "user", "content": user_input}]

        try:
            reply = self._loop(messages)
        except anthropic.APIError as e:
            log.error("API error: %s", e)
            return "Sorry, something went wrong."

        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": reply})
        self._trim()
        return reply

    def _loop(self, messages: list[dict]) -> str:
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        system = f"{self.system}\n\nCurrent date/time: {now}"

        kw: dict[str, Any] = dict(
            model=self.cfg.model,
            max_tokens=self.cfg.max_tokens,
            system=system,
            messages=messages,
        )
        if self._tools:
            kw["tools"] = self._tools

        for _ in range(10):  # guard against infinite loops
            resp = self.client.messages.create(**kw)

            # Done — extract text
            if resp.stop_reason == "end_turn":
                return self._text(resp)

            # Tool use — execute and feed back
            if resp.stop_reason == "tool_use":
                messages = list(kw["messages"])
                messages.append({"role": "assistant", "content": resp.content})

                results = []
                for block in resp.content:
                    if block.type != "tool_use":
                        continue
                    out = self._exec(block.name, block.input)
                    log.info("[skill] %s → %s", block.name, str(out)[:120])
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(out, default=str),
                    })

                messages.append({"role": "user", "content": results})
                kw["messages"] = messages
                continue

            # Anything else — return whatever we have
            return self._text(resp) or "I'm not sure how to answer that."

        return "I got stuck in a loop — please try again."

    def _exec(self, name: str, inputs: dict) -> Any:
        fn = self._fns.get(name)
        if not fn:
            return {"error": f"unknown skill: {name}"}
        try:
            return fn(**inputs)
        except Exception as e:
            log.error("Skill %s failed: %s", name, e)
            return {"error": str(e)}

    @staticmethod
    def _text(resp) -> str:
        for b in resp.content:
            if hasattr(b, "text"):
                return b.text
        return ""
