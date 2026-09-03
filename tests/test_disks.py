"""Tests for removable drives.

Nothing removable is plugged into the machine these run on, which is the point:
the listing has to be built from the kernel's own answers, so a fake /sys tree
and a fake partition list are the whole test surface. The one thing that must
never happen is a device name from the phone reaching `udisksctl` unchecked.
"""

from vt.actions import execute_action
from vt.sources import disks


class Partition:
    def __init__(self, device, mountpoint, fstype="ext4"):
        self.device, self.mountpoint, self.fstype = device, mountpoint, fstype


class Usage:
    def __init__(self, free=2 * 1024 ** 3, total=8 * 1024 ** 3):
        self.free, self.total = free, total


def fake_sys(tmp_path, monkeypatch, **removable):
    """A /sys/block with the disks and removable flags a test wants."""
    for disk, flag in removable.items():
        (tmp_path / disk).mkdir()
        (tmp_path / disk / "removable").write_text("1\n" if flag else "0\n")
    monkeypatch.setattr(disks, "SYS_BLOCK", tmp_path)


def fake_partitions(monkeypatch, *partitions):
    class Fake:
        @staticmethod
        def disk_partitions(all=False):
            return list(partitions)

        @staticmethod
        def disk_usage(path):
            return Usage()

    monkeypatch.setattr(disks, "psutil", Fake)


def test_a_partition_maps_to_its_disk(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True, nvme0n1=False, mmcblk0=True)
    assert disks.parent_disk("/dev/sdb1") == "sdb"
    assert disks.parent_disk("/dev/nvme0n1p2") == "nvme0n1"
    assert disks.parent_disk("/dev/mmcblk0p1") == "mmcblk0"


def test_a_device_that_is_not_there_has_no_disk(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True)
    assert disks.parent_disk("/dev/sdz9") == ""
    assert disks.parent_disk("") == ""


def test_the_kernel_decides_what_is_removable(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True, nvme0n1=False)
    assert disks.is_removable("/dev/sdb1") is True
    assert disks.is_removable("/dev/nvme0n1p2") is False


def test_only_removable_drives_are_listed(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True, nvme0n1=False)
    fake_partitions(
        monkeypatch,
        Partition("/dev/nvme0n1p2", "/"),
        Partition("/dev/sdb1", "/media/vaibhav/PHOTOS"),
    )
    listed = disks.removable_disks()
    assert [d["device"] for d in listed] == ["/dev/sdb1"]
    assert listed[0]["name"] == "PHOTOS"


def test_snap_loopbacks_are_not_drives(tmp_path, monkeypatch):
    """Twenty of them would bury the one row worth acting on."""
    fake_sys(tmp_path, monkeypatch, loop0=True)
    fake_partitions(monkeypatch, Partition("/dev/loop0", "/snap/firefox/8754", "squashfs"))
    assert disks.removable_disks() == []


def test_the_row_shows_the_free_space(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True)
    fake_partitions(monkeypatch, Partition("/dev/sdb1", "/media/vaibhav/PHOTOS"))
    row = disks.get_disk_targets()[0]
    assert row.id == "disk:sdb1"
    assert "2.0 GB free" in row.subtitle
    assert [a.id for a in row.actions] == ["eject"]


def test_no_removable_media_means_no_rows(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, nvme0n1=False)
    fake_partitions(monkeypatch, Partition("/dev/nvme0n1p2", "/"))
    assert disks.get_disk_targets() == []


def test_ejecting_unmounts_then_powers_down(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True)
    fake_partitions(monkeypatch, Partition("/dev/sdb1", "/media/vaibhav/PHOTOS"))
    calls = []

    class Result:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(disks.subprocess, "run",
                        lambda argv, **kw: calls.append(argv) or Result())

    assert disks.eject("sdb1")["ok"] is True
    assert [argv[1] for argv in calls] == ["unmount", "power-off"]
    assert calls[0][3] == "/dev/sdb1"
    assert calls[1][3] == "/dev/sdb"


def test_a_drive_that_will_not_unmount_is_an_error(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True)
    fake_partitions(monkeypatch, Partition("/dev/sdb1", "/media/vaibhav/PHOTOS"))

    class Result:
        returncode, stdout = 1, ""
        stderr = "Error unmounting: target is busy\n"

    monkeypatch.setattr(disks.subprocess, "run", lambda argv, **kw: Result())
    result = disks.eject("sdb1")
    assert result["ok"] is False and "busy" in result["message"]


def test_a_drive_that_unmounted_but_would_not_power_off_is_still_safe(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True)
    fake_partitions(monkeypatch, Partition("/dev/sdb1", "/media/vaibhav/PHOTOS"))
    seen = []

    class Ok:
        returncode, stdout, stderr = 0, "", ""

    class Fail:
        returncode, stdout, stderr = 1, "", "not authorized\n"

    def run(argv, **kw):
        seen.append(argv[1])
        return Ok() if argv[1] == "unmount" else Fail()

    monkeypatch.setattr(disks.subprocess, "run", run)
    result = disks.eject("sdb1")
    assert result["ok"] is True and "safe to remove" in result["message"]


def test_a_device_name_from_the_phone_is_checked(tmp_path, monkeypatch):
    fake_sys(tmp_path, monkeypatch, sdb=True)
    fake_partitions(monkeypatch, Partition("/dev/sdb1", "/media/vaibhav/PHOTOS"))
    monkeypatch.setattr(disks.subprocess, "run", _must_not_run)

    assert disks.eject("../../dev/nvme0n1")["ok"] is False
    assert disks.eject("sdb1; rm -rf ~")["ok"] is False
    assert disks.eject("nvme0n1p2")["ok"] is False, "not a removable drive"


def test_the_dispatcher_routes_a_drive(monkeypatch):
    monkeypatch.setattr(disks, "eject", lambda name: {"ok": True, "message": name})
    assert execute_action("disk:sdb1", "eject")["message"] == "sdb1"


def test_the_dispatcher_refuses_anything_but_eject():
    assert execute_action("disk:sdb1", "format")["ok"] is False


def _must_not_run(*args, **kwargs):
    raise AssertionError("udisksctl was called with something it should never see")
