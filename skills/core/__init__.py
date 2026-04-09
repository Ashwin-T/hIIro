"""Core skills — built-in tools that don't need external API keys."""
from __future__ import annotations

_CORE_MODULES = [
    "skills.core.device",
    "skills.core.dnd",
    "skills.core.scheduler",
    "skills.core.speedtest",
]


def build_all(cfg) -> list[tuple[dict, object]]:
    import importlib
    pairs: list[tuple[dict, object]] = []
    for mod_name in _CORE_MODULES:
        mod = importlib.import_module(mod_name)
        pairs.extend(mod.build(cfg))
    return pairs
