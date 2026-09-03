"""Tests for running several short read-only commands together.

The point of `run_all` is latency, so one test measures it: three sleeps that
take a second in a queue must take about a third of that when they wait
together. The rest pin the shape of the results, because every caller treats a
failure exactly like a command that had nothing to say.
"""

import time

from vt.procs import run_all


def test_results_come_back_in_the_order_asked():
    results = run_all([["echo", "first"], ["echo", "second"], ["echo", "third"]])
    assert [out.strip() for _, out in results] == ["first", "second", "third"]


def test_a_failing_command_keeps_its_place():
    results = run_all([["echo", "ok"], ["false"], ["echo", "also ok"]])
    assert [code for code, _ in results] == [0, 1, 0]
    assert results[1][1] == ""


def test_a_missing_binary_is_not_an_exception():
    assert run_all([["definitely-not-a-real-binary-9134"]]) == [(1, "")]


def test_a_command_that_hangs_is_killed_at_the_timeout():
    started = time.monotonic()
    results = run_all([["sleep", "5"]], timeout=0.3)
    assert results == [(1, "")]
    assert time.monotonic() - started < 3


def test_they_wait_together_rather_than_in_a_queue():
    started = time.monotonic()
    run_all([["sleep", "0.3"], ["sleep", "0.3"], ["sleep", "0.3"]])
    elapsed = time.monotonic() - started
    assert elapsed < 0.7, f"{elapsed:.2f}s looks like a queue, not a batch"


def test_nothing_to_run_is_not_an_error():
    assert run_all([]) == []
