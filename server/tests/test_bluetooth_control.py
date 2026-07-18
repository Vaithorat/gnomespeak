import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handlers.bluetooth_control import BluetoothControl


class TestBluetoothControl:
    def setup_method(self):
        self.control = BluetoothControl()

    def test_status_reports_unsupported_when_radio_cmdlets_missing(self):
        self.control._radio_control_supported = lambda: False
        result = self.control.status()
        assert result["success"] is False
        assert "not supported" in result["message"].lower()

    def test_connect_reports_unsupported(self):
        result = self.control.connect("Headphones")
        assert result["success"] is False
        assert "not supported in this release" in result["message"]

    def test_disconnect_reports_unsupported(self):
        result = self.control.disconnect("Headphones")
        assert result["success"] is False
        assert "not supported in this release" in result["message"]
