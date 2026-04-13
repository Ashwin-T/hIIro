"""
Skill registry.

Each skill module exposes a `build(cfg) -> list[tuple[dict, callable]]` function
that returns (tool_definition, executor) pairs ready for Agent.register().

To add a new skill:
  1. Create skills/my_skill.py with a build(cfg) function
  2. Add it to _MODULES below
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import Config

log = logging.getLogger(__name__)

_MODULES = [
    "skills.time_tools",
    "skills.weather",
    # "skills.search" — replaced by Claude's native web_search tool
    "skills.stocks",
    "skills.spotify",
    "skills.smarthome",
]


def load_all(cfg: "Config") -> list[tuple[dict, object]]:
    """Import all skill modules and return a flat list of (tool_def, fn) pairs."""
    import importlib
    from skills.core import build_all as build_core

    # Core skills first (device, dnd, etc.)
    pairs: list[tuple[dict, object]] = []
    try:
        core = build_core(cfg)
        pairs.extend(core)
        log.debug("Loaded %d core tool(s)", len(core))
    except Exception as e:
        log.warning("Core skills failed: %s", e)

    # External skills
    for mod_name in _MODULES:
        try:
            mod = importlib.import_module(mod_name)
            result = mod.build(cfg)
            pairs.extend(result)
            log.debug("Loaded %d tool(s) from %s", len(result), mod_name)
        except Exception as e:
            log.warning("Skipped %s: %s", mod_name, e)
    return pairs
