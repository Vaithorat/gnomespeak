import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Queue
import customtkinter as ctk
import websockets
from PIL import Image, ImageDraw, ImageFont

from config import Config
from auth import Auth
from intent_parser import IntentParser
from command_executor import CommandExecutor

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

LOGO_ICON = None


def _gen_tray_icon(size=64):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4, 4, size - 4, size - 4), radius=12, fill="#DC2626")
    draw.ellipse((18, 12, 46, 40), fill="white")
    draw.polygon([(34, 26), (34, 50), (52, 38)], fill="white")
    return img


LOGO_ICON = _gen_tray_icon()


def get_lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def copy_to_clipboard(text: str):
    try:
        subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True).communicate(input=text.encode("utf-16-le") + b"\0\x00")
    except Exception:
        pass


class LogHandler:
    def __init__(self, queue: Queue):
        self.queue = queue

    def write(self, text):
        if text.strip():
            self.queue.put(text.strip())

    def flush(self):
        pass


class ServerThread(threading.Thread):
    def __init__(self, config_path: str, master_password: str, log_queue: Queue, status_callback, clients_callback, client_connected_callback=None, activity_callback=None, disconnect_callback=None):
        super().__init__(daemon=True)
        self.config_path = config_path
        self.master_password = master_password
        self.log_queue = log_queue
        self.status_callback = status_callback
        self.clients_callback = clients_callback
        self.client_connected_callback = client_connected_callback
        self.activity_callback = activity_callback
        self.disconnect_callback = disconnect_callback
        self._stop_event = threading.Event()
        self.server_instance = None
        self._loop = None

    def stop(self):
        self._stop_event.set()
        if self._loop and self.server_instance:
            self._loop.call_soon_threadsafe(self.server_instance.shutdown_event.set)

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.server_instance = VoiceTalkServerWithGUI(
            self.config_path, self.log_queue, self.status_callback, self.clients_callback, self.client_connected_callback, self.activity_callback, self.disconnect_callback
        )
        sys.stdout = LogHandler(self.log_queue)
        sys.stderr = LogHandler(self.log_queue)
        try:
            self.server_instance.setup(self.master_password)
            self.status_callback("running")
            self._loop.run_until_complete(self.server_instance.run_async())
        except ValueError as e:
            self.log_queue.put(f"ERROR: {e}")
            self.status_callback("error")
        except Exception as e:
            self.log_queue.put(f"ERROR: {e}")
            self.status_callback("error")
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__


class VoiceTalkServerWithGUI:
    def __init__(self, config_path: str, log_queue: Queue, status_callback, clients_callback, client_connected_callback=None, activity_callback=None, disconnect_callback=None):
        self.config = Config(config_path)
        self.auth = Auth()
        self.intent_parser = None
        self.executor = None
        self._ws = None
        self._pending_questions = {}
        self._log_queue = log_queue
        self._status_callback = status_callback
        self._clients_callback = clients_callback
        self._client_connected_callback = client_connected_callback
        self._activity_callback = activity_callback
        self._disconnect_callback = disconnect_callback
        self._client_count = 0
        self.shutdown_event = asyncio.Event()

    def setup(self, master_password: str):
        self.config.unlock(master_password)
        self.intent_parser = IntentParser(self.config)
        self.executor = CommandExecutor(self.config)
        self._log_queue.put("Configuration loaded and unlocked")

    async def _send_question(self, message: str, options=None):
        q_id = f"q_{int(time.time() * 1000)}_{id(self._ws)}"
        future = asyncio.get_event_loop().create_future()
        self._pending_questions[q_id] = future
        payload = {"type": "question", "id": q_id, "message": message, "options": options or []}
        await self._ws.send(json.dumps(payload))
        try:
            answer = await asyncio.wait_for(future, timeout=60)
            return {"success": True, "text": answer}
        except asyncio.TimeoutError:
            self._pending_questions.pop(q_id, None)
            return {"success": False, "message": "No answer received within 60s"}

    async def handle_client(self, websocket):
        self._client_count += 1
        self._clients_callback(self._client_count)
        peer = websocket.remote_address
        self._log_queue.put(f"Client connected: {peer}")
        if self._client_connected_callback:
            self._client_connected_callback(str(peer[0]) if peer else "unknown")
        self._ws = websocket
        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    await self._send_result(websocket, False, "Invalid JSON")
                    continue
                msg_type = data.get("type")
                if msg_type == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                    continue
                if msg_type == "answer":
                    await self._handle_answer(data)
                    continue
                if msg_type != "command":
                    await self._send_result(websocket, False, "Unknown message type")
                    continue
                api_key = data.get("api_key", "")
                provider = data.get("provider", "")
                text = data.get("text", "").strip()
                if not text:
                    await self._send_result(websocket, False, "Empty command")
                    continue
                self._log_queue.put(f"-> {text}")
                if self._activity_callback:
                    self._activity_callback(text)
                ask_callback = lambda q, opts: self._send_question(q, opts)
                result = await self.intent_parser.parse(text, executor=self.executor, ask_callback=ask_callback, api_key=api_key, provider=provider)
                icon = "✓" if result.get("success") else "✗"
                msg = result.get("message", "")
                self._log_queue.put(f"<- {icon} {msg}")
                result["type"] = "result"
                await websocket.send(json.dumps(result))
        except websockets.exceptions.ConnectionClosed:
            self._log_queue.put(f"Client disconnected: {peer}")
        finally:
            self._client_count = max(0, self._client_count - 1)
            self._clients_callback(self._client_count)
            if self._disconnect_callback:
                self._disconnect_callback(str(peer[0]) if peer else "unknown")

    async def _handle_answer(self, data: dict):
        q_id = data.get("id", "")
        text = data.get("text", "")
        future = self._pending_questions.pop(q_id, None)
        if future and not future.done():
            future.set_result(text)

    async def _send_result(self, websocket, success: bool, message: str):
        await websocket.send(json.dumps({"type": "result", "success": success, "message": message}))

    def _free_port(self, host: str, port: int):
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, startupinfo=startupinfo)
            for line in result.stdout.splitlines():
                if "LISTENING" in line and f"{host}:{port}" in line:
                    parts = line.strip().split()
                    pid = parts[-1]
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, startupinfo=startupinfo)
                    self._log_queue.put(f"Killed stale process on port {port} (PID {pid})")
                    return True
        except Exception as e:
            self._log_queue.put(f"Port cleanup check failed: {e}")
        return False

    async def run_async(self):
        self._free_port(self.config.host, self.config.port)
        async with websockets.serve(
            self.handle_client,
            self.config.host,
            self.config.port,
            ping_interval=30,
            ping_timeout=10,
        ):
            addr = f"{self.config.host}:{self.config.port}"
            self._log_queue.put(f"Server listening on ws://{addr}")
            await self.shutdown_event.wait()


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, config: Config):
        super().__init__(parent)
        self.config = config
        self.result = None
        self.title("Settings")
        self.geometry("420x380")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=24, pady=24)

        ctk.CTkLabel(frame, text="Server Settings", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 16))

        ctk.CTkLabel(frame, text="Host", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.host_entry = ctk.CTkEntry(frame, height=36, corner_radius=8)
        self.host_entry.insert(0, config.data.get("host", "0.0.0.0"))
        self.host_entry.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(frame, text="Port", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.port_entry = ctk.CTkEntry(frame, height=36, corner_radius=8)
        self.port_entry.insert(0, str(config.data.get("port", 8765)))
        self.port_entry.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(frame, text="SMTP Server (optional)", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.smtp_entry = ctk.CTkEntry(frame, height=36, corner_radius=8)
        existing_smtp = config.get_secret("smtp_server") or ""
        self.smtp_entry.insert(0, existing_smtp)
        self.smtp_entry.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(frame, text="SMTP Username", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.smtp_user = ctk.CTkEntry(frame, height=36, corner_radius=8)
        existing_user = config.get_secret("smtp_username") or ""
        self.smtp_user.insert(0, existing_user)
        self.smtp_user.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(frame, text="SMTP Password", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.smtp_pw = ctk.CTkEntry(frame, show="*", height=36, corner_radius=8)
        existing_smtp_pw = config.get_secret("smtp_password") or ""
        self.smtp_pw.insert(0, existing_smtp_pw)
        self.smtp_pw.pack(fill="x", pady=(0, 16))

        btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
        btn_frame.pack(fill="x")
        ctk.CTkButton(btn_frame, text="Save", command=self._save, height=36, corner_radius=8, fg_color="#2563EB", hover_color="#1D4ED8").pack(side="left", padx=(0, 10))
        ctk.CTkButton(btn_frame, text="Cancel", command=self.destroy, height=36, corner_radius=8, fg_color="#374151", hover_color="#4B5563").pack(side="left")

    def _save(self):
        try:
            self.config.data["host"] = self.host_entry.get().strip()
            port_str = self.port_entry.get().strip()
            self.config.data["port"] = int(port_str)
        except ValueError:
            return
        smtp = self.smtp_entry.get().strip()
        if smtp:
            self.config.set_secret("smtp_server", smtp)
            self.config.set_secret("smtp_username", self.smtp_user.get().strip())
            self.config.set_secret("smtp_password", self.smtp_pw.get().strip())
        self.config.save()
        self.destroy()


class PasswordDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.password = None
        self.title("VoiceTalk - Master Password")
        self.geometry("360x200")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(self, text="Enter Master Password", font=("Segoe UI", 16, "bold")).pack(pady=(30, 10))
        self.entry = ctk.CTkEntry(self, show="*", width=250)
        self.entry.pack(pady=10)
        self.entry.bind("<Return>", lambda e: self._ok())
        ctk.CTkButton(self, text="Unlock", command=self._ok).pack(pady=5)
        ctk.CTkButton(self, text="Quit", command=lambda: setattr(self, "password", None) or self.destroy(), fg_color="gray").pack()

    def _ok(self):
        self.password = self.entry.get().strip()
        if self.password:
            self.destroy()


class VoiceTalkGUI:
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("VoiceTalk Server")
        self.root.geometry("720x520")
        self.root.minsize(560, 400)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.config = Config()
        self.server_thread = None
        self._log_queue = Queue()
        self._notif_after_id = None

        self._icon = _gen_tray_icon(32)
        if self._icon:
            from ctypes import windll
            try:
                windll.shell32.SetCurrentProcessExplicitAppUserModelID("voicetalk.server")
            except Exception:
                pass

        self._build_ui()
        self._poll_log()
        self._show_password()

    def _build_ui(self):
        # Top bar
        top = ctk.CTkFrame(self.root, height=60, corner_radius=0, fg_color="#0F172A")
        top.pack(fill="x", padx=0, pady=0)
        top.pack_propagate(False)

        ctk.CTkLabel(top, text="VoiceTalk", font=("Segoe UI", 20, "bold"), text_color="#FFFFFF").pack(side="left", padx=(16, 5), pady=10)

        self.status_btn = ctk.CTkButton(top, text="Starting...", width=140, height=32, corner_radius=8, fg_color="#F59E0B", hover=False, state="disabled", text_color="#FFFFFF", font=("Segoe UI", 11, "bold"))
        self.status_btn.pack(side="right", padx=16, pady=10)

        # Info bar
        info = ctk.CTkFrame(self.root, height=40, corner_radius=0, fg_color="#1E293B")
        info.pack(fill="x", padx=0, pady=0)
        info.pack_propagate(False)

        ctk.CTkLabel(info, text="Clients:", font=("Segoe UI", 12), text_color="#94A3B8").pack(side="left", padx=(16, 4))
        self.clients_label = ctk.CTkLabel(info, text="0", font=("Segoe UI", 12, "bold"), text_color="#FFFFFF")
        self.clients_label.pack(side="left")

        # Connection card
        conn_card = ctk.CTkFrame(self.root, fg_color="#1E293B", height=80, corner_radius=0)
        conn_card.pack(fill="x", padx=0, pady=0)
        conn_card.pack_propagate(False)

        ctk.CTkLabel(conn_card, text="Phone Connection", font=("Segoe UI", 12, "bold"), text_color="#60A5FA").pack(anchor="w", padx=(16, 0), pady=(10, 0))

        url_frame = ctk.CTkFrame(conn_card, fg_color="transparent")
        url_frame.pack(fill="x", padx=16, pady=(4, 10))

        self.conn_url_entry = ctk.CTkEntry(url_frame, font=("Consolas", 15, "bold"), height=36, corner_radius=8, text_color="#F8FAFC", fg_color="#334155", border_color="#475569")
        self.conn_url_entry.insert(0, "ws://---.---.---.---:----")
        self.conn_url_entry.configure(state="readonly")
        self.conn_url_entry.pack(side="left", fill="x", expand=True)

        self.copy_btn = ctk.CTkButton(url_frame, text="Copy", width=70, height=32, corner_radius=8, font=("Segoe UI", 11, "bold"), fg_color="#2563EB", hover_color="#1D4ED8", command=self._copy_url)
        self.copy_btn.pack(side="right", padx=(10, 0))

        # Control buttons
        ctrl = ctk.CTkFrame(self.root, height=52, corner_radius=0, fg_color="#0F172A")
        ctrl.pack(fill="x", padx=0, pady=0)
        ctrl.pack_propagate(False)

        self.start_btn = ctk.CTkButton(ctrl, text="Start", width=100, height=36, corner_radius=8, fg_color="#2563EB", hover_color="#1D4ED8", font=("Segoe UI", 12, "bold"))
        self.start_btn.pack(side="left", padx=(16, 6), pady=8)
        self.stop_btn = ctk.CTkButton(ctrl, text="Stop", width=100, height=36, corner_radius=8, fg_color="#DC2626", hover_color="#B91C1C", font=("Segoe UI", 12, "bold"), state="disabled")
        self.stop_btn.pack(side="left", padx=6, pady=8)
        self.settings_btn = ctk.CTkButton(ctrl, text="Settings", width=100, height=36, corner_radius=8, fg_color="#374151", hover_color="#4B5563", font=("Segoe UI", 12, "bold"))
        self.settings_btn.pack(side="right", padx=16, pady=8)

        # Log area
        log_frame = ctk.CTkFrame(self.root, fg_color="#1E293B", corner_radius=0)
        log_frame.pack(fill="both", expand=True, padx=0, pady=0)

        log_header = ctk.CTkFrame(log_frame, fg_color="transparent", height=36)
        log_header.pack(fill="x", padx=16, pady=(10, 0))
        log_header.pack_propagate(False)

        ctk.CTkLabel(log_header, text="Command Log", font=("Segoe UI", 12, "bold"), text_color="#94A3B8").pack(anchor="w")

        self.log_text = ctk.CTkTextbox(log_frame, font=("Consolas", 11), state="disabled", wrap="word", fg_color="#0F172A", text_color="#E2E8F0", corner_radius=8)
        self.log_text.pack(fill="both", expand=True, padx=16, pady=(4, 12))

        # Notification bar (hidden by default)
        self.notif_frame = ctk.CTkFrame(self.root, height=36, fg_color="#2563EB", corner_radius=0)
        self.notif_label = ctk.CTkLabel(self.notif_frame, text="", font=("Segoe UI", 11, "bold"), text_color="#FFFFFF")
        self.notif_label.pack(side="left", padx=16)
        self.notif_frame.pack_forget()

        # Status bar
        self.tray_label = ctk.CTkLabel(self.root, text="Minimizes to system tray on close", font=("Segoe UI", 10), text_color="#64748B")
        self.tray_label.pack(side="bottom", pady=(0, 6))
        self.notif_frame.pack(fill="x", padx=0, pady=0, before=self.tray_label)

    def _status(self, state: str):
        colors = {"running": "#2563EB", "stopped": "#374151", "error": "#DC2626", "starting": "#F59E0B"}
        labels = {"running": "Running", "stopped": "Stopped", "error": "Error", "starting": "Starting..."}
        c = colors.get(state, "#374151")
        self.status_btn.configure(fg_color=c, text=labels.get(state, "Unknown"))
        if state == "running":
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal")
            self.settings_btn.configure(state="disabled")
            lan = get_lan_ip()
            port = self.config.port
            addr = f"ws://{lan}:{port}"
            self.conn_url_entry.configure(state="normal")
            self.conn_url_entry.delete(0, "end")
            self.conn_url_entry.insert(0, addr)
            self.conn_url_entry.configure(state="readonly")
            self._show_notification(f"Server running on {addr}", "#2563EB")
        else:
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled")
            self.settings_btn.configure(state="normal")
            self._connected_peer = None
            self._hide_persistent_notification()
            self.conn_url_entry.configure(state="normal")
            self.conn_url_entry.delete(0, "end")
            self.conn_url_entry.insert(0, "ws://---.---.---.---:----")
            self.conn_url_entry.configure(state="readonly")

    def _clients(self, count: int):
        self.clients_label.configure(text=str(count))

    def _copy_url(self):
        url = self._connect_url
        try:
            subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True).communicate(input=url.encode("utf-16-le") + b"\0\x00")
            self._show_notification("URL copied!", "#2563EB")
        except Exception:
            self._show_notification("Failed to copy", "#DC2626")

    @property
    def _connect_url(self):
        lan_ip = get_lan_ip()
        port = self.config.port
        return f"ws://{lan_ip}:{port}"

    def _show_notification(self, message: str, color: str = "#2563EB"):
        if self._notif_after_id:
            self.root.after_cancel(self._notif_after_id)
        self.notif_frame.configure(fg_color=color)
        self.notif_label.configure(text=message)
        self.notif_frame.pack(fill="x", padx=0, pady=0, before=self.tray_label)
        self._notif_after_id = self.root.after(5000, self._hide_notification)

    def _hide_notification(self):
        self._notif_after_id = None
        self.notif_frame.pack_forget()

    def _show_persistent_notification(self, message: str, color: str = "#2563EB"):
        if self._notif_after_id:
            self.root.after_cancel(self._notif_after_id)
            self._notif_after_id = None
        self.notif_frame.configure(fg_color=color)
        self.notif_label.configure(text=message)
        self.notif_frame.pack(fill="x", padx=0, pady=0, before=self.tray_label)

    def _hide_persistent_notification(self):
        if self._notif_after_id:
            self.root.after_cancel(self._notif_after_id)
            self._notif_after_id = None
        self.notif_frame.pack_forget()

    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        t = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{t}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_log(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get_nowait()
            self._log(msg)
        self.root.after(100, self._poll_log)

    def _show_password(self):
        try:
            self.config.auto_unlock()
        except ValueError:
            self._log("ERROR: Failed to unlock config")
            return
        self._master_pw = "voicetalk"
        self._log("Configuration unlocked")
        self._start_server()

    def _start_server(self):
        if self.server_thread and self.server_thread.is_alive():
            return
        pw = getattr(self, "_master_pw", None) or ""
        self._status("starting")
        self.server_thread = ServerThread(
            "config.json", pw, self._log_queue,
            lambda s: self.root.after(0, lambda: self._status(s)),
            lambda c: self.root.after(0, lambda: self._clients(c)),
            lambda peer: self.root.after(0, lambda: self._on_client_connected(peer)),
            lambda text: self.root.after(0, lambda: self._on_activity(text)),
            lambda peer: self.root.after(0, lambda: self._on_client_disconnected(peer)),
        )
        self.server_thread.start()

    def _on_client_connected(self, peer: str):
        self._connected_peer = peer
        self._show_persistent_notification(f"Client connected: {peer}", "#2563EB")

    def _on_client_disconnected(self, peer: str):
        self._connected_peer = None
        self._hide_persistent_notification()
        self._show_notification(f"Client disconnected: {peer}", "#DC2626")

    def _on_activity(self, text: str):
        if not self._connected_peer:
            return
        if self._notif_after_id:
            self.root.after_cancel(self._notif_after_id)
        self.notif_frame.configure(fg_color="#F59E0B")
        display = text[:50] + ("..." if len(text) > 50 else "")
        self.notif_label.configure(text=f"Receiving: {display}")
        self.notif_frame.pack(fill="x", padx=0, pady=0, before=self.tray_label)
        self._notif_after_id = self.root.after(2000, self._restore_connected_notification)

    def _restore_connected_notification(self):
        self._notif_after_id = None
        if self._connected_peer:
            self.notif_frame.configure(fg_color="#2563EB")
            self.notif_label.configure(text=f"Client connected: {self._connected_peer}")

    def _stop_server(self):
        self._connected_peer = None
        self._hide_persistent_notification()
        if self.server_thread:
            self.server_thread.stop()
            self.server_thread = None
        self._status("stopped")
        self._log("Server stopped")

    def _open_settings(self):
        if self.server_thread and self.server_thread.is_alive():
            self._log("Stop the server to change settings")
            return
        dlg = SettingsDialog(self.root, self.config)
        self.root.wait_window(dlg)

    def _on_close(self):
        minimized = False
        try:
            import pystray
            from pystray import MenuItem as item
            self.root.withdraw()
            menu = (
                item("Show", lambda: self.root.deiconify()),
                item("Quit", self._quit_app),
            )
            icon = pystray.Icon("VoiceTalk", LOGO_ICON, "VoiceTalk Server", menu)
            threading.Thread(target=icon.run, daemon=True).start()
            self._tray_icon = icon
            minimized = True
        except ImportError:
            pass
        if not minimized:
            self._quit_app()

    def _quit_app(self):
        self._stop_server()
        try:
            if hasattr(self, "_tray_icon"):
                self._tray_icon.stop()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = VoiceTalkGUI()
    app.run()
