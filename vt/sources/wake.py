"""Wake another PC on the network.

A remote cannot start the machine it runs on -- the server is asleep with it --
but the switcher already knows about the other machines, and one that is awake
can send the packet. That turns "this PC is not answering" into "wake it",
which is the only shape of this feature that was ever honest.

Wake-on-LAN is a broadcast UDP datagram: six 0xFF bytes followed by the target
MAC sixteen times. Nothing acknowledges it, so the answer here is "sent", never
"woken" -- the switcher's own reachability probe is what says whether it
worked, a few seconds later.
"""

import re
import socket

# The port does not matter to the hardware -- the NIC matches on the payload,
# not the header -- but 9 (discard) is what every other tool uses.
DEFAULT_PORT = 9
BROADCAST = "255.255.255.255"

_MAC = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def normalise_mac(mac: str) -> str:
    """The MAC in aa:bb:cc:dd:ee:ff form, or "" when it is not one."""
    candidate = (mac or "").strip()
    if not _MAC.match(candidate):
        return ""
    return candidate.replace("-", ":").lower()


def magic_packet(mac: str) -> bytes:
    """The wake payload for a MAC, or b"" when the MAC is not one."""
    normalised = normalise_mac(mac)
    if not normalised:
        return b""
    address = bytes.fromhex(normalised.replace(":", ""))
    return b"\xff" * 6 + address * 16


def wake(mac: str, broadcast: str = BROADCAST, port: int = DEFAULT_PORT) -> dict:
    """Send the packet. "Sent" is the strongest thing that can be said."""
    packet = magic_packet(mac)
    if not packet:
        return {"ok": False, "message": "That is not a MAC address"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(2)
            sock.sendto(packet, (broadcast, port))
    except OSError as e:
        return {"ok": False, "message": f"Could not send it: {e}"}
    return {
        "ok": True,
        # Deliberately not "woken": nothing answers a magic packet, and a
        # machine that ignores it looks identical from here.
        "message": f"Wake packet sent to {normalise_mac(mac)}",
    }
