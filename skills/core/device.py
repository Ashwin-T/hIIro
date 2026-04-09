"""Device health + audio skills — CPU, temp, memory, disk, uptime, IP, volume, audio test."""
from __future__ import annotations

import shutil
import socket
import subprocess
import time

TOOLS = [
    {"name": "device_status", "description": "Get device health: CPU %, temperature, memory, disk usage, and uptime.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "audio_test", "description": "Play a test tone through the speaker to verify audio output is working.",
     "input_schema": {"type": "object", "properties": {
         "duration": {"type": "integer", "description": "Duration in seconds (1-10). Default 2.", "default": 2},
         "frequency": {"type": "integer", "description": "Tone frequency in Hz. Default 440.", "default": 440},
     }}},
    {"name": "set_volume", "description": "Set the speaker volume level.",
     "input_schema": {"type": "object", "properties": {
         "percent": {"type": "integer", "description": "Volume level 0-100."},
     }, "required": ["percent"]}},
    {"name": "get_volume", "description": "Get the current speaker volume level.",
     "input_schema": {"type": "object", "properties": {}}},
]


def _read(path: str, fallback: str = "") -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return fallback


def _cpu_percent(interval: float = 0.5) -> float:
    """Sample CPU usage over a short interval from /proc/stat."""
    def read_idle():
        fields = _read("/proc/stat").splitlines()[0].split()
        total = sum(int(f) for f in fields[1:])
        idle = int(fields[4])
        return total, idle

    t1, i1 = read_idle()
    time.sleep(interval)
    t2, i2 = read_idle()
    dt, di = t2 - t1, i2 - i1
    if dt == 0:
        return 0.0
    return round((1 - di / dt) * 100, 1)


def _device_status() -> dict:
    info: dict = {}

    # CPU
    info["cpu_percent"] = _cpu_percent()

    # Temperature (Raspberry Pi thermal zone)
    raw = _read("/sys/class/thermal/thermal_zone0/temp")
    if raw:
        info["temp_c"] = round(int(raw) / 1000, 1)

    # Memory from /proc/meminfo
    meminfo = _read("/proc/meminfo")
    if meminfo:
        mem = {}
        for line in meminfo.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                mem[parts[0].rstrip(":")] = int(parts[1])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        if total:
            used = total - avail
            info["memory"] = {
                "total_mb": round(total / 1024),
                "used_mb": round(used / 1024),
                "percent": round(used / total * 100, 1),
            }

    # Disk
    usage = shutil.disk_usage("/")
    info["disk"] = {
        "total_gb": round(usage.total / (1 << 30), 1),
        "used_gb": round(usage.used / (1 << 30), 1),
        "percent": round(usage.used / usage.total * 100, 1),
    }

    # IP address
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        info["ip"] = s.getsockname()[0]
        s.close()
    except OSError:
        pass

    # Uptime
    raw = _read("/proc/uptime")
    if raw:
        secs = int(float(raw.split()[0]))
        days, rem = divmod(secs, 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
        info["uptime"] = f"{days}d {hours}h {mins}m"

    return info


def _audio_test(duration: int = 2, frequency: int = 440) -> dict:
    duration = max(1, min(10, duration))
    try:
        proc = subprocess.Popen(
            ["speaker-test", "-t", "sine", "-f", str(frequency),
             "-D", "plughw:2,0", "-l", "1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(duration)
        proc.kill()
        proc.wait()
        return {"played": True, "frequency": frequency, "duration": duration}
    except Exception as e:
        return {"error": str(e)}


def _set_volume(percent: int) -> dict:
    percent = max(0, min(100, percent))
    try:
        subprocess.run(
            ["amixer", "-c", "2", "sset", "PCM", f"{percent}%"],
            capture_output=True, check=True,
        )
        return {"volume": percent}
    except Exception as e:
        return {"error": str(e)}


def _get_volume() -> dict:
    try:
        result = subprocess.run(
            ["amixer", "-c", "2", "sget", "PCM"],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.splitlines():
            if "%" in line:
                # Extract percentage from e.g. "[100%]"
                start = line.index("[") + 1
                end = line.index("%")
                return {"volume": int(line[start:end])}
        return {"volume": "unknown"}
    except Exception as e:
        return {"error": str(e)}


def build(cfg) -> list[tuple[dict, object]]:
    return [
        (TOOLS[0], _device_status),
        (TOOLS[1], _audio_test),
        (TOOLS[2], _set_volume),
        (TOOLS[3], _get_volume),
    ]
