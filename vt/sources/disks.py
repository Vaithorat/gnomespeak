"""Removable drives: what is plugged in, and how to get it out safely.

"Can you eject the USB stick?" is a question people walk across a room for. The
kernel already says which drives are removable, psutil already lists what is
mounted, and udisks already knows how to unmount and power down a drive without
root -- so this is those three joined up.

Only removable media. A row per mounted filesystem would bury the one thing
worth acting on under twenty snap loopbacks, and the internal disk is not
something anyone wants a one-tap "eject" for.
"""

import re
import subprocess
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a hard dependency in practice
    psutil = None

SYS_BLOCK = Path("/sys/block")

# A partition device name reduced to the disk it lives on: sdb1 -> sdb,
# mmcblk0p1 -> mmcblk0, nvme0n1p2 -> nvme0n1.
_PARTITION = re.compile(r"^(?P<disk>.+?)(?:p?\d+)$")

# Filesystems that are never a removable drive someone wants to eject.
_SKIP_TYPES = {"squashfs", "tmpfs", "devtmpfs", "overlay", "proc", "sysfs", "autofs"}


def parent_disk(device: str) -> str:
    """The whole-disk name behind a partition device path."""
    name = str(device or "").rsplit("/", 1)[-1]
    if not name:
        return ""
    if (SYS_BLOCK / name).exists():
        return name
    match = _PARTITION.match(name)
    if not match:
        return ""
    disk = match.group("disk")
    return disk if (SYS_BLOCK / disk).exists() else ""


def is_removable(device: str) -> bool:
    """Whether the kernel calls this device's disk removable."""
    disk = parent_disk(device)
    if not disk:
        return False
    try:
        return (SYS_BLOCK / disk / "removable").read_text().strip() == "1"
    except OSError:
        return False


def removable_disks() -> list:
    """Mounted removable filesystems as {device, mountpoint, name, free, total}."""
    if psutil is None:
        return []
    found = []
    try:
        partitions = psutil.disk_partitions(all=False)
    except Exception:
        return []
    for part in partitions:
        if part.fstype in _SKIP_TYPES or not part.device.startswith("/dev/"):
            continue
        if not is_removable(part.device):
            continue
        entry = {
            "device": part.device,
            "mountpoint": part.mountpoint,
            # The mount point's last component is what the desktop shows, and
            # it is usually the volume's own label.
            "name": part.mountpoint.rstrip("/").rsplit("/", 1)[-1] or part.device,
            "free": 0,
            "total": 0,
        }
        try:
            usage = psutil.disk_usage(part.mountpoint)
            entry["free"], entry["total"] = usage.free, usage.total
        except Exception:
            pass
        found.append(entry)
    return found


def _human(value: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if value >= 10 or unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def get_disk_targets() -> list:
    """A row per removable drive, or none when nothing is plugged in."""
    from vt.model import Action, Target

    targets = []
    for disk in removable_disks():
        detail = f"{_human(disk['free'])} free" if disk["total"] else disk["mountpoint"]
        targets.append(Target(
            id=f"disk:{disk['device'].rsplit('/', 1)[-1]}",
            kind="system",
            title=disk["name"],
            subtitle=detail,
            icon="💾",
            status="mounted",
            actions=[Action(id="eject", label="Eject")],
        ))
    return targets


def eject(device_name: str) -> dict:
    """Unmount a removable drive and power it down. `device_name` is "sdb1"."""
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", device_name or ""):
        return {"ok": False, "message": "That is not a drive"}
    known = {d["device"].rsplit("/", 1)[-1]: d for d in removable_disks()}
    disk = known.get(device_name)
    if disk is None:
        return {"ok": False, "message": "That drive is not mounted any more"}

    unmounted = _udisks("unmount", disk["device"])
    if not unmounted["ok"]:
        return unmounted

    # Powering the whole drive down is what makes the light go out and the
    # desktop stop showing it; failing that step still leaves it safe to pull,
    # so it is reported as a success with a caveat rather than an error.
    parent = parent_disk(disk["device"])
    if parent:
        powered = _udisks("power-off", f"/dev/{parent}")
        if not powered["ok"]:
            return {"ok": True,
                    "message": f"{disk['name']} is unmounted and safe to remove"}
    return {"ok": True, "message": f"{disk['name']} ejected"}


def _udisks(verb: str, block: str) -> dict:
    try:
        result = subprocess.run(
            ["udisksctl", verb, "-b", block, "--no-user-interaction"],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return {"ok": False, "message": "udisksctl not found (install udisks2)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"{verb} timed out"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        return {"ok": False, "message": detail[-1] if detail else f"{verb} failed"}
    return {"ok": True, "message": ""}
