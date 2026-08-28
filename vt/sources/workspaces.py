"""Workspace switching through the GNOME extension.

Mutter owns the workspace list, and only code running inside the compositor can
read or change it -- hence the extension. `List()` reports the active
workspace's windows and nothing else, so without this source there is no way to
tell from the remote that other workspaces exist at all.
"""

from vt.model import Target, Action
from vt.sources.windows import shell_interface, workspace_info

try:
    import dbus
except ImportError:
    dbus = None


def get_workspace_targets() -> list[Target]:
    """One target per workspace, or [] when there is only one to be on."""
    spaces = workspace_info()
    count = int(spaces.get("count", 0) or 0)
    active = int(spaces.get("active", -1))

    # A single workspace is not a choice, and a row that cannot change anything
    # is just noise on a phone screen.
    if count < 2:
        return []

    targets = []
    for index in range(count):
        is_active = index == active
        targets.append(Target(
            id=f"workspace:{index}",
            kind="workspace",
            title=f"Workspace {index + 1}",
            icon="▦" if is_active else "▧",
            status="active" if is_active else "",
            # The active workspace keeps an empty action list rather than a
            # disabled button: switching to where you already are is a no-op
            # that still reports success, which reads as a bug.
            actions=[] if is_active else [Action(id="switch", label="Switch")],
        ))
    return targets


def execute(target_spec: str, action_id: str) -> dict:
    """Switch to a workspace, addressed by its zero-based index."""
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; workspaces are unavailable"}
    if action_id != "switch":
        return {"ok": False, "message": f"Unknown workspace action: {action_id}"}

    try:
        index = int(target_spec)
    except (TypeError, ValueError):
        return {"ok": False, "message": f"Invalid workspace: {target_spec}"}

    spaces = workspace_info()
    count = int(spaces.get("count", 0) or 0)
    if not count:
        # Absent and out-of-date look identical from here -- an older build
        # answers the bus and not this method -- and the fix is the same.
        return {"ok": False, "message": (
            "Workspace control needs the current GNOME extension. Run "
            "`vt install-extension`, then log out and back in to reload it."
        )}
    if not 0 <= index < count:
        return {"ok": False, "message": f"No workspace {index + 1}; there are {count}"}

    try:
        shell_interface().SwitchWorkspace(dbus.UInt32(index))
        return {"ok": True, "message": f"Switched to workspace {index + 1}"}
    except Exception as e:
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
        return {"ok": False, "message": f"GNOME extension error: {detail}"}
