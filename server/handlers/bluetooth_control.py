import subprocess


class BluetoothControl:
    def _radio_control_supported(self) -> bool:
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "@(Get-Command Get-BluetoothRadio -ErrorAction SilentlyContinue, Get-Command Set-BluetoothRadio -ErrorAction SilentlyContinue).Count",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0 and result.stdout.strip() == "2"
        except Exception:
            return False

    def status(self) -> dict:
        if not self._radio_control_supported():
            return {"success": False, "message": "Bluetooth radio control is not supported on this Windows setup."}
        try:
            r = subprocess.run(
                ["powershell", "-Command",
                 "$r = Get-BluetoothRadio; if ($r) { Write-Output \"$($r.Name) enabled=$($r.Enabled)\" } else { Write-Output 'No Bluetooth radio found' }"],
                capture_output=True, text=True, timeout=10,
            )
            return {"success": True, "message": r.stdout.strip()}
        except Exception as e:
            return {"success": False, "message": f"Bluetooth status error: {str(e)}"}

    def on(self) -> dict:
        if not self._radio_control_supported():
            return {"success": False, "message": "Bluetooth radio control is not supported on this Windows setup."}
        try:
            subprocess.run(
                ["powershell", "-Command", "Get-BluetoothRadio | Set-BluetoothRadio -Enabled $true"],
                capture_output=True, timeout=30,
            )
            return {"success": True, "message": "Bluetooth turned on"}
        except Exception as e:
            return {"success": False, "message": f"Failed to turn on Bluetooth: {str(e)}"}

    def off(self) -> dict:
        if not self._radio_control_supported():
            return {"success": False, "message": "Bluetooth radio control is not supported on this Windows setup."}
        try:
            subprocess.run(
                ["powershell", "-Command", "Get-BluetoothRadio | Set-BluetoothRadio -Enabled $false"],
                capture_output=True, timeout=30,
            )
            return {"success": True, "message": "Bluetooth turned off"}
        except Exception as e:
            return {"success": False, "message": f"Failed to turn off Bluetooth: {str(e)}"}

    def scan(self) -> dict:
        try:
            r = subprocess.run(
                ["powershell", "-Command",
                 "Get-PnpDevice -Class Bluetooth | Where-Object Status -eq 'OK' | Select-Object FriendlyName"],
                capture_output=True, text=True, timeout=15,
            )
            devices = [
                l.strip() for l in r.stdout.split('\n')
                if l.strip() and 'FriendlyName' not in l and '---' not in l
            ]
            if devices:
                return {"success": True, "message": f"Devices: {', '.join(devices)}", "devices": devices}
            return {"success": True, "message": "No Bluetooth devices found", "devices": []}
        except Exception as e:
            return {"success": False, "message": f"Bluetooth scan error: {str(e)}"}

    def connect(self, device: str) -> dict:
        return {
            "success": False,
            "message": f"Bluetooth connect for '{device}' is not supported in this release.",
        }

    def disconnect(self, device: str) -> dict:
        return {
            "success": False,
            "message": f"Bluetooth disconnect for '{device}' is not supported in this release.",
        }

    def execute(self, args: dict) -> dict:
        action = args.get("action", "")
        device = args.get("device", "")
        if action == "status":
            return self.status()
        elif action == "on":
            return self.on()
        elif action == "off":
            return self.off()
        elif action == "scan":
            return self.scan()
        elif action == "connect":
            return self.connect(device)
        elif action == "disconnect":
            return self.disconnect(device)
        return {"success": False, "message": f"Unknown Bluetooth action: {action}"}
