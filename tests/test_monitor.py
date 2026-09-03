"""Tests for the machine's own row: CPU, memory, disk, uptime, temperature.

Every value is a read, so the tests are about what is *not* shown: a CPU figure
that would be a lie on the first tick, a sensor reporting nonsense, and a
machine with no sensors at all.
"""

import time

from vt.sources import monitor


class FakeMemory:
    percent, total, available = 32.0, 24 * 1024 ** 3, 16 * 1024 ** 3


class FakeDisk:
    percent, free = 41.0, 280 * 1024 ** 3


def fake_psutil(monkeypatch, cpu=12.0, disk=FakeDisk):
    class Fake:
        @staticmethod
        def cpu_percent(interval=None):
            return cpu

        @staticmethod
        def virtual_memory():
            return FakeMemory

        @staticmethod
        def disk_usage(path):
            return disk

        @staticmethod
        def getloadavg():
            return (0.5, 0.4, 0.3)

        @staticmethod
        def boot_time():
            return time.time() - 3700

    monkeypatch.setattr(monitor, "psutil", Fake)
    monkeypatch.setattr(monitor, "_primed", True)
    monkeypatch.setattr(monitor, "_temperature", ("54°C", time.monotonic()))
    # The numbers are cached so the row does not change every second; a test
    # that wants this call's values has to start from an empty cache.
    monkeypatch.setattr(monitor, "_stats", ({}, 0.0))
    return Fake


def test_the_row_reads_as_a_glance(monkeypatch):
    fake_psutil(monkeypatch)
    row = monitor.get_monitor_targets()[0]
    assert row.id == "system:machine"
    # Rounded to the nearest five: an idle machine flickering between 2% and 3%
    # would be a patch to every phone, every second.
    assert row.status == "CPU 10% · RAM 30%"
    assert "280 GB free" in row.subtitle
    assert "up 1h 1m" in row.subtitle


def test_the_first_tick_shows_no_cpu_figure(monkeypatch):
    """psutil's first answer is "since boot", which is not what the row claims."""
    fake_psutil(monkeypatch)
    monkeypatch.setattr(monitor, "_primed", False)
    assert monitor._cpu_percent() is None


def test_the_numbers_are_not_re_read_every_second(monkeypatch):
    """A row that changed every tick would be the 1 Hz poll wearing a socket."""
    reads = []

    class Fake:
        @staticmethod
        def cpu_percent(interval=None):
            reads.append(1)
            return 12.0

        @staticmethod
        def virtual_memory():
            return FakeMemory

        @staticmethod
        def disk_usage(path):
            return FakeDisk

        @staticmethod
        def getloadavg():
            return (0.5, 0.4, 0.3)

        @staticmethod
        def boot_time():
            return time.time() - 60

    monkeypatch.setattr(monitor, "psutil", Fake)
    monkeypatch.setattr(monitor, "_primed", True)
    monkeypatch.setattr(monitor, "_stats", ({}, 0.0))

    monitor.machine_stats()
    monitor.machine_stats()
    monitor.machine_stats()

    assert len(reads) == 1


def test_a_nearly_full_disk_says_so(monkeypatch):
    class Full:
        percent, free = 97.0, 900 * 1024 ** 2

    fake_psutil(monkeypatch, disk=Full)
    row = monitor.get_monitor_targets()[0]
    assert row.icon == "🔥"
    assert "nearly full" in row.note


def test_no_psutil_means_no_row(monkeypatch):
    monkeypatch.setattr(monitor, "psutil", None)
    assert monitor.get_monitor_targets() == []
    assert monitor.machine_stats() == {}


def test_a_sensor_reporting_nonsense_is_ignored(monkeypatch, tmp_path):
    """A disconnected sensor reads 217 °C, and the row would believe it."""
    (tmp_path / "hot").write_text("217000\n")
    (tmp_path / "real").write_text("48000\n")
    monkeypatch.setattr(monitor, "_zones", [str(tmp_path / "hot"), str(tmp_path / "real")])
    monkeypatch.setattr(monitor, "_temperature", ("", 0.0))
    assert monitor._hottest() == "48°C"


def test_a_machine_with_no_sensors_says_nothing(monkeypatch):
    monkeypatch.setattr(monitor, "_zones", [])
    monkeypatch.setattr(monitor, "_temperature", ("", 0.0))
    assert monitor._hottest() == ""


def test_the_temperature_is_not_read_every_second(monkeypatch, tmp_path):
    """It costs file reads and moves slowly; the snapshot runs at 1 Hz."""
    path = tmp_path / "zone"
    path.write_text("40000\n")
    monkeypatch.setattr(monitor, "_zones", [str(path)])
    monkeypatch.setattr(monitor, "_temperature", ("", 0.0))
    assert monitor._hottest() == "40°C"

    path.write_text("90000\n")
    assert monitor._hottest() == "40°C", "the cached reading should still stand"


def test_sizes_are_readable_on_a_phone():
    assert monitor._human_bytes(900) == "900 B"
    assert monitor._human_bytes(1536) == "1.5 KB"
    assert monitor._human_bytes(24 * 1024 ** 3) == "24 GB"
