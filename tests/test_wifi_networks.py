"""Tests for joining a saved Wi-Fi network from the phone.

Two things are load-bearing. The name comes from a snapshot the phone may have
been holding for a while, so it is checked against NetworkManager's own list
before `nmcli` sees it; and the list is cached, because it changes about once a
month and the snapshot is collected once a second.
"""

import time

from vt.sources import network


class Result:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


LISTING = (
    "4A:802-11-wireless:yes\n"
    "lo:loopback:yes\n"
    "Cafe: free:802-11-wireless:no\n"
    "netplan-enp1s0:802-3-ethernet:no\n"
)


def stub_nmcli(monkeypatch, listing=LISTING, up=Result()):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["nmcli", "-t"]:
            return Result(listing)
        return up

    monkeypatch.setattr(network.subprocess, "run", run)
    monkeypatch.setattr(network, "_networks", ([], 0.0))
    return calls


def test_only_wireless_connections_are_networks(monkeypatch):
    stub_nmcli(monkeypatch)
    assert [n["name"] for n in network.saved_networks()] == ["4A", "Cafe: free"]


def test_a_name_with_a_colon_survives(monkeypatch):
    """"Cafe: free" is a legal SSID and splitting from the left loses it."""
    stub_nmcli(monkeypatch)
    assert "Cafe: free" in [n["name"] for n in network.saved_networks()]


def test_the_one_in_use_comes_first(monkeypatch):
    stub_nmcli(monkeypatch, listing="Other:802-11-wireless:no\n4A:802-11-wireless:yes\n")
    assert [n["name"] for n in network.saved_networks()] == ["4A", "Other"]


def test_the_list_is_not_read_every_second(monkeypatch):
    calls = stub_nmcli(monkeypatch)
    network.saved_networks()
    network.saved_networks()
    assert len(calls) == 1


def test_the_cache_expires(monkeypatch):
    calls = stub_nmcli(monkeypatch)
    network.saved_networks()
    monkeypatch.setattr(network, "_networks",
                        (network._networks[0], time.monotonic() - network.NETWORKS_TTL - 1))
    network.saved_networks()
    assert len(calls) == 2


def test_nmcli_missing_is_an_empty_list_not_an_error(monkeypatch):
    def missing(argv, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(network.subprocess, "run", missing)
    monkeypatch.setattr(network, "_networks", ([], 0.0))
    assert network.saved_networks() == []


def test_the_row_offers_the_networks_you_are_not_on(monkeypatch):
    stub_nmcli(monkeypatch)
    monkeypatch.setattr(network, "_properties",
                        lambda: {"WirelessEnabled": True, "Connectivity": 4})
    row = network.get_network_targets()[0]
    assert row.status == "4A"
    assert [a.label for a in row.actions] == ["Turn off", "Join Cafe: free"]


def test_no_networks_are_offered_while_the_radio_is_off(monkeypatch):
    stub_nmcli(monkeypatch)
    monkeypatch.setattr(network, "_properties",
                        lambda: {"WirelessEnabled": False, "Connectivity": 0})
    row = network.get_network_targets()[0]
    assert [a.id for a in row.actions] == ["wifi_on"]


def test_joining_runs_nmcli_with_the_name(monkeypatch):
    calls = stub_nmcli(monkeypatch)
    assert network.connect_network("Cafe: free")["ok"] is True
    assert ["nmcli", "connection", "up", "id", "Cafe: free"] in calls


def test_a_network_that_is_not_saved_never_reaches_nmcli(monkeypatch):
    calls = stub_nmcli(monkeypatch)
    result = network.connect_network("Evil Twin")
    assert result["ok"] is False
    assert all(argv[:2] != ["nmcli", "connection"] for argv in calls)


def test_nmcli_refusing_is_reported(monkeypatch):
    stub_nmcli(monkeypatch, up=Result(returncode=4, stderr="Error: Timeout expired.\n"))
    result = network.connect_network("Cafe: free")
    assert result["ok"] is False and "Timeout expired" in result["message"]


def test_the_dispatcher_joins_by_position(monkeypatch):
    calls = stub_nmcli(monkeypatch)
    assert network.execute("wifi", "join_1")["ok"] is True
    assert ["nmcli", "connection", "up", "id", "Cafe: free"] in calls


def test_a_stale_position_is_refused(monkeypatch):
    stub_nmcli(monkeypatch)
    assert network.execute("wifi", "join_9")["ok"] is False


def test_a_position_that_is_not_a_number_is_refused(monkeypatch):
    stub_nmcli(monkeypatch)
    assert network.execute("wifi", "join_all")["ok"] is False
