"""Tests for the battery level BlueZ publishes beside each paired device.

It arrives in the same GetManagedObjects call the device list already makes, so
the cost is a dictionary lookup -- and a device that does not implement the
battery service must lose a word, never a row.
"""

from vt.sources import bluetooth

ADAPTER = "/org/bluez/hci0"
HEADSET = "/org/bluez/hci0/dev_AA_BB"
MOUSE = "/org/bluez/hci0/dev_CC_DD"


def objects(headset_battery=None, mouse_battery=None):
    tree = {
        ADAPTER: {bluetooth.ADAPTER_IFACE: {"Powered": True, "Alias": "This PC"}},
        HEADSET: {bluetooth.DEVICE_IFACE: {
            "Paired": True, "Connected": True, "Alias": "Headset",
            "Address": "AA:BB", "Icon": "audio-headset",
        }},
        MOUSE: {bluetooth.DEVICE_IFACE: {
            "Paired": True, "Connected": True, "Alias": "Mouse",
            "Address": "CC:DD", "Icon": "input-mouse",
        }},
    }
    if headset_battery is not None:
        tree[HEADSET][bluetooth.BATTERY_IFACE] = {"Percentage": headset_battery}
    if mouse_battery is not None:
        tree[MOUSE][bluetooth.BATTERY_IFACE] = {"Percentage": mouse_battery}
    return tree


def rows(monkeypatch, **kwargs):
    monkeypatch.setattr(bluetooth, "_managed_objects", lambda: objects(**kwargs))
    monkeypatch.setattr(bluetooth, "_adapter_path", lambda objs=None: ADAPTER)
    return {t.title: t for t in bluetooth.get_bluetooth_targets()}


def test_a_device_that_reports_its_battery_shows_it(monkeypatch):
    found = rows(monkeypatch, headset_battery=42)
    assert found["Headset"].status == "connected · 42%"


def test_a_device_that_reports_nothing_just_says_connected(monkeypatch):
    found = rows(monkeypatch, headset_battery=70)
    assert found["Mouse"].status == "connected"


def test_a_nonsense_reading_is_dropped(monkeypatch):
    found = rows(monkeypatch, headset_battery=254)
    assert found["Headset"].status == "connected"


def test_a_reading_that_is_not_a_number_is_dropped(monkeypatch):
    found = rows(monkeypatch, headset_battery="full")
    assert found["Headset"].status == "connected"


def test_an_empty_battery_is_not_the_same_as_no_battery(monkeypatch):
    """0% is a reading, and it is the one worth seeing."""
    found = rows(monkeypatch, headset_battery=0)
    assert found["Headset"].status == "connected · 0%"
