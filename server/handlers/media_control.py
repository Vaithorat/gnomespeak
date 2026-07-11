import pyautogui
import time


pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = False


class MediaControl:
    def execute(self, action: str) -> dict:
        action = action.strip().lower().replace("-", "_").replace(" ", "_")

        if action == "play_pause":
            pyautogui.press("space")
            return {"success": True, "message": "Toggled play/pause (Space)"}

        elif action == "next_track":
            pyautogui.press("nexttrack")
            return {"success": True, "message": "Skipped to next track"}

        elif action == "prev_track":
            pyautogui.press("prevtrack")
            return {"success": True, "message": "Went to previous track"}

        elif action == "volume_up":
            pyautogui.press("volumeup")
            return {"success": True, "message": "Volume increased"}

        elif action == "volume_down":
            pyautogui.press("volumedown")
            return {"success": True, "message": "Volume decreased"}

        elif action == "mute":
            pyautogui.press("volumemute")
            return {"success": True, "message": "Toggled mute"}

        elif action == "fullscreen":
            pyautogui.press("f11")
            return {"success": True, "message": "Toggled fullscreen (F11)"}

        elif action == "refresh":
            pyautogui.press("f5")
            return {"success": True, "message": "Refreshed page (F5)"}

        elif action == "escape":
            pyautogui.press("escape")
            return {"success": True, "message": "Pressed Escape"}

        elif action == "enter":
            pyautogui.press("enter")
            return {"success": True, "message": "Pressed Enter"}

        elif action == "tab":
            pyautogui.press("tab")
            return {"success": True, "message": "Pressed Tab"}

        elif action == "forward":
            pyautogui.press("right")
            return {"success": True, "message": "Skipped forward (→)"}

        elif action == "backward":
            pyautogui.press("left")
            return {"success": True, "message": "Skipped backward (←)"}

        else:
            return {
                "success": False,
                "message": f"Unknown action: '{action}'. Available: play_pause, next_track, prev_track, volume_up, volume_down, mute, fullscreen, refresh, forward, backward, escape, enter, tab",
            }

    def dump_tools(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "media_control",
                    "description": "Control media playback and browser via keyboard. Use play_pause to start/resume a paused video (e.g. YouTube). Use fullscreen for fullscreen mode. IMPORTANT: After opening a YouTube video, if it's paused, call media_control(action='play_pause') to start playing.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "play_pause",
                                    "next_track",
                                    "prev_track",
                                    "volume_up",
                                    "volume_down",
                                    "mute",
                                    "fullscreen",
                                    "refresh",
                                    "forward",
                                    "backward",
                                    "escape",
                                    "enter",
                                    "tab",
                                ],
                                "description": "Keyboard action. play_pause = Space (starts/pauses video), forward = Right arrow (skip 5s), backward = Left arrow (rewind 5s)",
                            }
                        },
                        "required": ["action"],
                    },
                },
            }
        ]
