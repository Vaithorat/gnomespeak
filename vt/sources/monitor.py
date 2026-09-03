"""What the machine is doing: CPU, memory, disk, uptime.

The page is opened to check on the PC as often as to control it -- "is the
render still going?", "did the disk fill up?" -- and every number here is a
read that psutil already has in memory or a single /proc file. Nothing here can
change the machine, so the worst failure is a row that is missing rather than
one that is wrong.

Cost matters more than completeness: this runs inside the once-a-second
snapshot, so anything that needs a second process or a walk of every PID stays
out. CPU percentage is the one value with a subtlety -- it is a delta since the
last call, so the first reading after startup is meaningless and is left off
rather than reported as zero.
"""

import glob
import time

from vt.model import Target

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a hard dependency in practice
    psutil = None

# Set on the first call, so the second call has something to measure against.
_primed = False


def _cpu_percent():
    """CPU use since the last snapshot, or None on the very first one."""
    global _primed
    if psutil is None:
        return None
    value = psutil.cpu_percent(interval=None)
    if not _primed:
        _primed = True
        # psutil's first answer is "since boot", which is not what the row
        # claims to show. One second later the real number arrives.
        return None
    return value


def _uptime() -> str:
    if psutil is None:
        return ""
    seconds = int(time.time() - psutil.boot_time())
    days, rest = divmod(seconds, 86400)
    hours, minutes = divmod(rest // 60, 60)
    if days:
        return f"up {days}d {hours}h"
    if hours:
        return f"up {hours}h {minutes}m"
    return f"up {minutes}m"


# psutil.sensors_temperatures() walks every hwmon device and reads a label for
# each one: 200 ms on this laptop, which is more than the whole snapshot budget
# for a number nobody watches change second by second. The thermal zones say
# the same thing from a handful of files, and the file list only needs finding
# once.
_ZONE_GLOB = "/sys/class/thermal/thermal_zone*/temp"
_zones = None
_temperature = ("", 0.0)      # last reading, and when it was taken
TEMPERATURE_TTL = 10.0


def _zone_paths() -> list:
    global _zones
    if _zones is None:
        try:
            _zones = sorted(glob.glob(_ZONE_GLOB))
        except Exception:
            _zones = []
    return _zones


def _hottest() -> str:
    """The warmest thermal zone, or "" on a machine that exposes none."""
    global _temperature
    reading, taken = _temperature
    now = time.monotonic()
    if taken and now - taken < TEMPERATURE_TTL:
        return reading

    hottest = 0.0
    for path in _zone_paths():
        try:
            with open(path) as handle:
                # Millidegrees, and occasionally a sensor that reports nonsense
                # like 217 °C when it is disconnected.
                value = int(handle.read().strip()) / 1000.0
        except (OSError, ValueError):
            continue
        if 0 < value < 150 and value > hottest:
            hottest = value

    reading = f"{hottest:.0f}°C" if hottest else ""
    _temperature = (reading, now)
    return reading


def _human_bytes(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if value >= 10 or unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


# How often the numbers are actually re-read. The live channel sends a patch
# whenever a target changes, so a row that changed every second would be the
# 1 Hz poll again wearing a socket -- and nobody watches a CPU figure at that
# resolution anyway. The percentages are also rounded to the nearest five, so
# an idle machine's row is stable rather than flickering between 2% and 3%.
REFRESH_SECONDS = 5.0
_stats = ({}, 0.0)


def _round5(value: float) -> int:
    return int(round(value / 5.0) * 5)


def machine_stats() -> dict:
    """Everything the row shows, as plain values. {} without psutil."""
    if psutil is None:
        return {}
    global _stats
    cached, taken = _stats
    if cached and time.monotonic() - taken < REFRESH_SECONDS:
        return cached
    _stats = (_machine_stats(), time.monotonic())
    return _stats[0]


def _machine_stats() -> dict:
    if psutil is None:
        return {}
    stats = {"cpu": _cpu_percent(), "uptime": _uptime(), "temperature": _hottest()}
    try:
        memory = psutil.virtual_memory()
        stats["memory_percent"] = memory.percent
        stats["memory_used"] = memory.total - memory.available
        stats["memory_total"] = memory.total
    except Exception:
        pass
    try:
        disk = psutil.disk_usage("/")
        stats["disk_percent"] = disk.percent
        stats["disk_free"] = disk.free
    except Exception:
        pass
    try:
        stats["load"] = psutil.getloadavg()[0]
    except (AttributeError, OSError):
        pass
    return stats


def get_monitor_targets() -> list[Target]:
    """One row for the machine itself, or none when psutil is missing."""
    stats = machine_stats()
    if not stats:
        return []

    headline = []
    if stats.get("cpu") is not None:
        headline.append(f"CPU {_round5(stats['cpu'])}%")
    if "memory_percent" in stats:
        headline.append(f"RAM {_round5(stats['memory_percent'])}%")
    if not headline:
        # The first tick after startup knows nothing worth a row yet.
        return []

    detail = []
    if "memory_used" in stats:
        detail.append(
            f"{_human_bytes(stats['memory_used'])} of {_human_bytes(stats['memory_total'])} used"
        )

    if "disk_free" in stats:
        detail.append(f"{_human_bytes(stats['disk_free'])} free")
    if stats.get("temperature"):
        detail.append(stats["temperature"])
    if stats.get("uptime"):
        detail.append(stats["uptime"])

    # A disk with almost nothing left is the one number here worth an icon
    # that says something is wrong, because it is the one that breaks things
    # quietly and hours later.
    tight = stats.get("disk_percent", 0) >= 95
    return [Target(
        id="system:machine",
        kind="system",
        title="This PC",
        subtitle=" · ".join(detail),
        icon="🔥" if tight else "📊",
        status=" · ".join(headline),
        note="The disk is nearly full." if tight else "",
    )]
