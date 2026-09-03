"""Tests for timers the PC keeps itself.

The design claim is that the machine running the job is the machine holding the
timer, so these tests never involve a phone: a job survives the connection
going away, and dies with the server rather than firing into a desktop that has
moved on.
"""

import time

from vt.actions import execute_action
from vt.schedule import MAX_JOBS, MAX_SECONDS, Scheduler, in_words, remaining_words
from vt.sources import system


def runner(seen):
    def run(target, action):
        seen.append((target, action))
        return {"ok": True, "message": "done"}
    return run


def test_a_job_runs_when_it_is_due():
    seen = []
    scheduler = Scheduler(runner=runner(seen))
    scheduler.add("system:power", "suspend", 60)

    assert scheduler.run_due(now=time.time() + 61)
    assert seen == [("system:power", "suspend")]


def test_a_job_that_is_not_due_stays_put():
    seen = []
    scheduler = Scheduler(runner=runner(seen))
    scheduler.add("system:power", "suspend", 600)

    assert scheduler.run_due() == []
    assert seen == []
    assert len(scheduler.jobs()) == 1


def test_a_job_runs_once():
    seen = []
    scheduler = Scheduler(runner=runner(seen))
    scheduler.add("system:power", "suspend", 1)
    later = time.time() + 5

    scheduler.run_due(now=later)
    scheduler.run_due(now=later)

    assert seen == [("system:power", "suspend")]


def test_a_cancelled_job_never_runs():
    seen = []
    scheduler = Scheduler(runner=runner(seen))
    job = scheduler.add("system:power", "suspend", 60)["job"]

    assert scheduler.cancel(job["id"])["ok"] is True
    scheduler.run_due(now=time.time() + 3600)
    assert seen == []


def test_cancelling_something_that_is_gone_says_so():
    scheduler = Scheduler(runner=runner([]))
    assert scheduler.cancel(41)["ok"] is False
    assert scheduler.cancel("not a number")["ok"] is False


def test_a_timer_in_the_past_is_refused():
    scheduler = Scheduler(runner=runner([]))
    assert scheduler.add("system:power", "suspend", 0)["ok"] is False
    assert scheduler.add("system:power", "suspend", -60)["ok"] is False


def test_a_timer_longer_than_half_a_day_is_refused():
    """That is a cron job wearing a phone's clothes."""
    scheduler = Scheduler(runner=runner([]))
    assert scheduler.add("system:power", "suspend", MAX_SECONDS + 1)["ok"] is False


def test_the_number_of_timers_is_capped():
    scheduler = Scheduler(runner=runner([]))
    for _ in range(MAX_JOBS):
        assert scheduler.add("system:power", "suspend", 600)["ok"] is True
    assert scheduler.add("system:power", "suspend", 600)["ok"] is False


def test_a_job_needs_something_to_do():
    scheduler = Scheduler(runner=runner([]))
    assert scheduler.add("", "suspend", 60)["ok"] is False
    assert scheduler.add("system:power", "", 60)["ok"] is False


def test_a_job_that_throws_does_not_stop_the_others():
    seen = []

    def explode(target, action):
        if target == "bad:one":
            raise RuntimeError("D-Bus went away")
        seen.append((target, action))
        return {"ok": True, "message": "done"}

    scheduler = Scheduler(runner=explode)
    scheduler.add("bad:one", "boom", 1)
    scheduler.add("system:power", "suspend", 2)

    results = scheduler.run_due(now=time.time() + 10)

    assert seen == [("system:power", "suspend")]
    assert results[0][1]["ok"] is False


def test_jobs_come_back_soonest_first():
    scheduler = Scheduler(runner=runner([]))
    scheduler.add("system:power", "suspend", 600, label="later")
    scheduler.add("system:power", "lock", 60, label="sooner")
    assert [j["label"] for j in scheduler.jobs()] == ["sooner", "later"]


def test_a_pending_job_says_how_long_is_left():
    scheduler = Scheduler(runner=runner([]))
    scheduler.add("system:power", "suspend", 900)
    assert 890 < scheduler.jobs()[0]["remaining"] <= 900


def test_the_words_are_ones_a_phone_can_show():
    assert in_words(1800) == "in 30 minutes"
    assert in_words(60) == "in 1 minute"
    assert in_words(3600) == "in 1 hour"
    assert in_words(5400) == "in 1h 30m"
    assert remaining_words(1680) == "28 min left"
    assert remaining_words(20) == "under a minute left"


# --- the rows the phone sees ------------------------------------------------

def test_the_power_row_offers_a_sleep_timer(monkeypatch):
    monkeypatch.setattr(system, "battery_summary", lambda: "")
    power = next(t for t in system.get_system_targets() if t.id == "system:power")
    assert "suspend_in_30" in [a.id for a in power.actions]


def test_setting_a_timer_from_the_power_row(monkeypatch):
    scheduler = Scheduler(runner=runner([]))
    monkeypatch.setattr("vt.schedule.scheduler", lambda: scheduler)

    result = system.execute("power", "suspend_in_30")

    assert result["ok"] is True
    assert [j["label"] for j in scheduler.jobs()] == ["Suspend"]


def test_a_timer_that_is_not_a_number_is_refused(monkeypatch):
    scheduler = Scheduler(runner=runner([]))
    monkeypatch.setattr("vt.schedule.scheduler", lambda: scheduler)
    assert system.execute("power", "suspend_in_soon")["ok"] is False


def test_a_pending_timer_gets_its_own_row(monkeypatch):
    scheduler = Scheduler(runner=runner([]))
    scheduler.add("system:power", "suspend", 900, label="Suspend")
    monkeypatch.setattr("vt.schedule.scheduler", lambda: scheduler)
    monkeypatch.setattr(system, "battery_summary", lambda: "")

    rows = {t.id: t for t in system.get_system_targets()}
    assert "timer:1" in rows
    assert rows["timer:1"].status.endswith("left")
    assert [a.id for a in rows["timer:1"].actions] == ["cancel"]


def test_the_dispatcher_cancels_a_timer(monkeypatch):
    scheduler = Scheduler(runner=runner([]))
    scheduler.add("system:power", "suspend", 900, label="Suspend")
    monkeypatch.setattr("vt.schedule.scheduler", lambda: scheduler)

    assert execute_action("timer:1", "cancel")["ok"] is True
    assert scheduler.jobs() == []


def test_the_dispatcher_refuses_an_unknown_timer_action(monkeypatch):
    scheduler = Scheduler(runner=runner([]))
    monkeypatch.setattr("vt.schedule.scheduler", lambda: scheduler)
    assert execute_action("timer:1", "postpone")["ok"] is False
