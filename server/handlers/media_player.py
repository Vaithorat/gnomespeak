import os
import subprocess
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor


class MediaPlayer:
    def __init__(self):
        self._com_executor = None
        try:
            import pythoncom
            self._com_executor = ThreadPoolExecutor(max_workers=1)
            self._com_executor.submit(self._init_com).result()
        except ImportError:
            pass

    @staticmethod
    def _init_com():
        import pythoncom
        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)

    def play_local(self, query: str) -> dict:
        dirs = [
            Path(os.environ.get("USERPROFILE", "")) / "Music",
            Path(os.environ.get("USERPROFILE", "")) / "Downloads",
        ]
        query_lower = query.lower()
        matches = []
        for d in dirs:
            if not d.exists():
                continue
            for f in d.rglob("*"):
                if f.is_file() and query_lower in f.stem.lower():
                    matches.append(f)
        if not matches:
            return {"success": False, "message": f"No local files found matching '{query}'"}
        target = matches[0]
        try:
            os.startfile(str(target))
            return {"success": True, "message": f"Playing '{target.stem}' from local files"}
        except Exception as e:
            return {"success": False, "message": f"Failed to play local file: {str(e)}"}

    def volume_up(self) -> dict:
        try:
            subprocess.run(
                ["powershell", "-Command", "$o = new-object -com wscript.shell; $o.SendKeys([char]175)"],
                capture_output=True, timeout=5,
            )
            return {"success": True, "message": "Volume increased"}
        except Exception as e:
            return {"success": False, "message": f"Volume up failed: {str(e)}"}

    def volume_down(self) -> dict:
        try:
            subprocess.run(
                ["powershell", "-Command", "$o = new-object -com wscript.shell; $o.SendKeys([char]174)"],
                capture_output=True, timeout=5,
            )
            return {"success": True, "message": "Volume decreased"}
        except Exception as e:
            return {"success": False, "message": f"Volume down failed: {str(e)}"}

    def volume_mute(self) -> dict:
        try:
            subprocess.run(
                ["powershell", "-Command", "$o = new-object -com wscript.shell; $o.SendKeys([char]173)"],
                capture_output=True, timeout=5,
            )
            return {"success": True, "message": "Volume toggled mute"}
        except Exception as e:
            return {"success": False, "message": f"Mute failed: {str(e)}"}

    def set_volume(self, level: int) -> dict:
        level = max(0, min(100, level))
        if self._com_executor is None:
            return self._set_volume_com(level)
        try:
            future = self._com_executor.submit(self._set_volume_com, level)
            return future.result()
        except Exception as e:
            return {"success": False, "message": f"Volume control error: {str(e)}"}

    @staticmethod
    def _get_endpoint_volume():
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        endpoint_volume = getattr(devices, "EndpointVolume", None)
        if endpoint_volume is not None:
            return endpoint_volume

        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))

    @staticmethod
    def _set_volume_com(level: int) -> dict:
        try:
            volume = MediaPlayer._get_endpoint_volume()
            scalar = level / 100.0
            volume.SetMasterVolumeLevelScalar(scalar, None)
            return {"success": True, "message": f"Volume set to {level}%"}
        except ImportError:
            return {"success": False, "message": "pycaw not installed. Run: pip install pycaw comtypes"}
        except Exception as e:
            return {"success": False, "message": f"Volume control error: {str(e)}"}
