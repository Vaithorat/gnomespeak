"""Things the PC should do in a while: a sleep timer, and its relatives.

"Suspend in thirty minutes" is the one automation a remote can offer honestly:
the machine that runs the job is the machine holding the timer, so nothing
depends on the phone still being there, the tab still being open, or the
network surviving. The phone sets it and can walk away.

Jobs live in memory and die with the server, which is the truthful lifetime: a
timer that survived a restart would fire against a desktop that has been doing
something else for an hour. They are checked by the collector that already runs
once a second, so nothing here holds a thread of its own.
"""

import threading
import time

# A timer nobody can see is a timer nobody trusts; a handful is plenty, and the
# cap is what stops a phone with a stuck button from filling memory.
MAX_JOBS = 8

# The longest a job may sit. A "wake me in nine hours" timer is a cron job
# wearing a phone's clothes, and it belongs in cron.
MAX_SECONDS = 12 * 3600


class Scheduler:
    """Jobs waiting to run, and the clock that decides when."""

    def __init__(self, runner=None):
        # Injected so tests never touch the desktop, and so the server can
        # route execution through its own single worker thread.
        self._runner = runner
        self._jobs: list = []
        self._seq = 0
        self._lock = threading.Lock()

    def add(self, target: str, action: str, seconds: float, label: str = "") -> dict:
        """Schedule one action. Returns the usual result dict, plus the job."""
        try:
            seconds = float(seconds)
        except (TypeError, ValueError):
            return {"ok": False, "message": "That is not a number of minutes"}
        if seconds <= 0:
            return {"ok": False, "message": "A timer has to be in the future"}
        if seconds > MAX_SECONDS:
            hours = int(MAX_SECONDS // 3600)
            return {"ok": False, "message": f"The longest timer is {hours} hours"}
        if not target or not action:
            return {"ok": False, "message": "A timer needs something to do"}

        with self._lock:
            if len(self._jobs) >= MAX_JOBS:
                return {"ok": False, "message": f"There are already {MAX_JOBS} timers"}
            self._seq += 1
            job = {
                "id": self._seq,
                "target": target,
                "action": action,
                "label": label or f"{action} {target}",
                "due": time.time() + seconds,
            }
            self._jobs.append(job)
        return {"ok": True, "message": f"{job['label']} {in_words(seconds)}", "job": dict(job)}

    def cancel(self, job_id) -> dict:
        try:
            job_id = int(job_id)
        except (TypeError, ValueError):
            return {"ok": False, "message": "That is not a timer"}
        with self._lock:
            for index, job in enumerate(self._jobs):
                if job["id"] == job_id:
                    del self._jobs[index]
                    return {"ok": True, "message": f"Cancelled: {job['label']}"}
        return {"ok": False, "message": "That timer is not there any more"}

    def cancel_all(self) -> int:
        with self._lock:
            count = len(self._jobs)
            self._jobs = []
            return count

    def jobs(self) -> list:
        """Pending jobs, soonest first, each with the seconds left on it."""
        now = time.time()
        with self._lock:
            pending = sorted(self._jobs, key=lambda j: j["due"])
        return [dict(job, remaining=max(0.0, job["due"] - now)) for job in pending]

    def run_due(self, now: float = None) -> list:
        """Run whatever is due. Returns (job, result) pairs for what ran.

        Called from the collector rather than a timer thread: the collector is
        already running once a second, and a job that fires a second late is a
        job that fired.
        """
        now = time.time() if now is None else now
        with self._lock:
            due = [job for job in self._jobs if job["due"] <= now]
            self._jobs = [job for job in self._jobs if job["due"] > now]

        results = []
        for job in sorted(due, key=lambda j: j["due"]):
            try:
                result = self._run(job)
            except Exception as e:
                result = {"ok": False, "message": f"Error: {e}"}
            results.append((job, result))
        return results

    def _run(self, job: dict) -> dict:
        if self._runner is not None:
            return self._runner(job["target"], job["action"])
        from vt.actions import execute_action

        return execute_action(job["target"], job["action"])


def in_words(seconds: float) -> str:
    """"in 30 minutes", for a message a phone shows next to a button."""
    minutes = int(round(seconds / 60.0))
    if minutes < 1:
        return "in under a minute"
    if minutes < 60:
        return f"in {minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(minutes, 60)
    if rest:
        return f"in {hours}h {rest}m"
    return f"in {hours} hour{'s' if hours != 1 else ''}"


def remaining_words(seconds: float) -> str:
    """"28 min left", for the row that shows a pending timer."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute left"
    if minutes < 60:
        return f"{minutes} min left"
    hours, rest = divmod(minutes, 60)
    return f"{hours}h {rest}m left"


_scheduler = None
_scheduler_lock = threading.Lock()


def scheduler() -> Scheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = Scheduler()
    return _scheduler
