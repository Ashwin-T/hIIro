"""Scheduler skill — run tools at scheduled times, optionally speak results."""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

_JOBS_FILE = Path("config/schedules.json")

TOOLS = [
    {
        "name": "set_schedule",
        "description": (
            "Schedule a tool to run at a specific time, or set a reminder that speaks a message. "
            "For reminders like 'remind me to X in 5 minutes', set message and leave skill_name empty. "
            "Can be one-shot or recurring."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Name of the tool/skill to run (e.g. 'smarthome_control'). Omit for reminders."},
                "skill_args": {"type": "object", "description": "Arguments to pass to the skill", "default": {}},
                "message": {"type": "string", "description": "Message to speak aloud when the schedule fires. Use for reminders/alarms."},
                "run_at": {"type": "string", "description": "When to run, as YYYY-MM-DDTHH:MM or HH:MM (24h). For relative times like 'in 5 minutes', add the minutes to the current time from the system prompt and pass the result."},
                "repeat_minutes": {"type": "integer", "description": "Repeat every N minutes. Omit or 0 for one-shot."},
                "silent": {"type": "boolean", "description": "If true, run without speaking the result. Default false.", "default": False},
            },
            "required": ["run_at"],
        },
    },
    {
        "name": "list_schedules",
        "description": "List all pending scheduled tasks.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_schedule",
        "description": "Cancel a scheduled task by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {"schedule_id": {"type": "string", "description": "The ID of the schedule to cancel"}},
            "required": ["schedule_id"],
        },
    },
]


class Scheduler:
    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._agent = None
        self._tts = None
        self._lock = threading.Lock()

    def start(self, agent, tts) -> None:
        """Wire up agent and TTS after they're created in main, then reload saved jobs."""
        self._agent = agent
        self._tts = tts
        self._load()

    def _parse_time(self, run_at: str) -> datetime:
        """Parse ISO datetime or HH:MM into a datetime."""
        now = datetime.now()
        # Try HH:MM
        for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
            try:
                t = datetime.strptime(run_at.strip(), fmt).time()
                dt = datetime.combine(now.date(), t)
                if dt <= now:
                    dt += timedelta(days=1)
                return dt
            except ValueError:
                continue
        # Try full ISO
        return datetime.fromisoformat(run_at)

    def set_schedule(self, run_at: str, skill_name: str = "",
                     skill_args: Optional[dict] = None, message: str = "",
                     repeat_minutes: int = 0, silent: bool = False) -> dict:
        dt = self._parse_time(run_at)
        job_id = uuid.uuid4().hex[:8]
        job = {
            "id": job_id,
            "skill_name": skill_name,
            "skill_args": skill_args or {},
            "message": message,
            "run_at": dt.isoformat(),
            "repeat_minutes": repeat_minutes,
            "silent": silent,
        }
        with self._lock:
            self._jobs[job_id] = job
            self._save()
        self._arm(job_id, dt)
        label = message if message else skill_name
        return {"scheduled": job_id, "run_at": dt.strftime("%Y-%m-%d %H:%M"), "label": label}

    def list_schedules(self) -> dict:
        with self._lock:
            if not self._jobs:
                return {"schedules": [], "message": "No scheduled tasks."}
            return {"schedules": list(self._jobs.values())}

    def cancel_schedule(self, schedule_id: str) -> dict:
        with self._lock:
            if schedule_id not in self._jobs:
                return {"error": f"No schedule with ID {schedule_id}"}
            del self._jobs[schedule_id]
            self._save()
            timer = self._timers.pop(schedule_id, None)
        if timer:
            timer.cancel()
        return {"cancelled": schedule_id}

    def _save(self) -> None:
        """Persist jobs to disk."""
        try:
            _JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
            _JOBS_FILE.write_text(json.dumps(list(self._jobs.values()), indent=2))
        except Exception as e:
            log.error("Failed to save schedules: %s", e)

    def _load(self) -> None:
        """Reload saved jobs from disk and re-arm timers."""
        if not _JOBS_FILE.exists():
            return
        try:
            jobs = json.loads(_JOBS_FILE.read_text())
        except Exception as e:
            log.error("Failed to load schedules: %s", e)
            return
        now = datetime.now()
        for job in jobs:
            dt = datetime.fromisoformat(job["run_at"])
            # Skip expired one-shots
            if dt <= now and not job.get("repeat_minutes"):
                continue
            # For expired recurring jobs, advance to next future run
            if dt <= now and job.get("repeat_minutes"):
                interval = timedelta(minutes=job["repeat_minutes"])
                while dt <= now:
                    dt += interval
                job["run_at"] = dt.isoformat()
            with self._lock:
                self._jobs[job["id"]] = job
            self._arm(job["id"], dt)
        # Clean expired one-shots from disk
        self._save()
        log.info("Reloaded %d scheduled job(s) from disk", len(self._jobs))

    def _arm(self, job_id: str, dt: datetime) -> None:
        delay = max(0, (dt - datetime.now()).total_seconds())
        timer = threading.Timer(delay, self._fire, args=[job_id])
        timer.daemon = True
        with self._lock:
            old = self._timers.pop(job_id, None)
            if old:
                old.cancel()
            self._timers[job_id] = timer
        timer.start()
        log.debug("Armed job %s in %.0fs", job_id, delay)

    def _fire(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            self._timers.pop(job_id, None)

        skill_name = job.get("skill_name", "")
        skill_args = job.get("skill_args", {})
        message = job.get("message", "")
        silent = job.get("silent", False)
        repeat = job.get("repeat_minutes", 0)

        # Reminder-only (no skill to run, just speak the message)
        if message and not skill_name:
            log.debug("Reminder fired: %s", message)
            if self._tts:
                self._tts.speak(f"Reminder: {message}")
        else:
            # Execute the skill directly
            result: Any = {"error": "agent not connected"}
            if self._agent:
                fn = self._agent._fns.get(skill_name)
                if fn:
                    try:
                        result = fn(**skill_args)
                    except Exception as e:
                        log.error("Scheduled skill %s failed: %s", skill_name, e)
                        result = {"error": str(e)}
                else:
                    result = {"error": f"unknown skill: {skill_name}"}

            log.debug("Scheduled job %s fired: %s → %s", job_id, skill_name, str(result)[:120])

            # Speak the result through Claude if not silent
            if not silent and self._agent and self._tts:
                prompt = (
                    f"I scheduled '{skill_name}' to run at {job['run_at']} and it just ran. "
                    f"Here are the results: {result}. "
                    f"Summarize this for me conversationally as a quick spoken update."
                )
                try:
                    response = self._agent.run(prompt)
                    self._tts.speak(response)
                except Exception as e:
                    log.error("Failed to speak scheduled result: %s", e)

        # Re-arm if recurring, otherwise clean up
        if repeat and repeat > 0:
            next_dt = datetime.now() + timedelta(minutes=repeat)
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["run_at"] = next_dt.isoformat()
                self._save()
            self._arm(job_id, next_dt)
        else:
            with self._lock:
                self._jobs.pop(job_id, None)
                self._save()


# Module-level instance so build() and start() share state
_scheduler = Scheduler()


def build(cfg) -> list[tuple[dict, object]]:
    return [
        (TOOLS[0], _scheduler.set_schedule),
        (TOOLS[1], _scheduler.list_schedules),
        (TOOLS[2], _scheduler.cancel_schedule),
    ]
