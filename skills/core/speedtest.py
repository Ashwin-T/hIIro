"""Internet speed test skill — runs a lightweight speed check."""
from __future__ import annotations

import logging
import subprocess
import time

log = logging.getLogger(__name__)

TOOLS = [
    {
        "name": "speed_test",
        "description": (
            "Run an internet speed test and return download/upload speeds and ping. "
            "Use when the user asks 'how fast is my internet', 'run a speed test', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _speed_test() -> dict:
    """Run speed test using speedtest-cli (pip) or curl fallback."""
    # Try speedtest-cli first
    try:
        result = subprocess.run(
            ["speedtest-cli", "--simple"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            parsed = {}
            for line in lines:
                if line.startswith("Ping:"):
                    parsed["ping"] = line.split(":")[1].strip()
                elif line.startswith("Download:"):
                    parsed["download"] = line.split(":")[1].strip()
                elif line.startswith("Upload:"):
                    parsed["upload"] = line.split(":")[1].strip()
            return parsed
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("speedtest-cli failed: %s", e)

    # Fallback: curl-based download test
    try:
        url = "http://speedtest.tele2.net/1MB.zip"
        start = time.monotonic()
        result = subprocess.run(
            ["curl", "-o", "/dev/null", "-s", "-w", "%{speed_download}", url],
            capture_output=True, text=True, timeout=30,
        )
        elapsed = time.monotonic() - start
        speed_bytes = float(result.stdout.strip())
        speed_mbps = (speed_bytes * 8) / 1_000_000
        return {
            "download": f"{speed_mbps:.1f} Mbit/s",
            "method": "curl (1MB test file)",
            "time": f"{elapsed:.1f}s",
        }
    except Exception as e:
        return {"error": f"Speed test failed: {e}"}


def build(cfg) -> list[tuple[dict, object]]:
    return [(TOOLS[0], _speed_test)]
