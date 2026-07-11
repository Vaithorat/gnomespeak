import asyncio
import sys
import threading
import tkinter as tk
from tkinter import simpledialog, messagebox
from pathlib import Path
from PIL import Image, ImageDraw
import pystray

from server import VoiceTalkServer, prompt_setup


def create_tray_icon(server, loop):
    icon_image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon_image)
    draw.ellipse([8, 8, 56, 56], fill="#2563EB")
    draw.ellipse([20, 20, 44, 44], fill="#FFFFFF")

    def on_show(icon, item):
        icon.visible = False
        root = tk.Tk()
        root.title("VoiceTalk Server")
        root.geometry("400x300")
        tk.Label(root, text="VoiceTalk Server", font=("Arial", 16, "bold")).pack(pady=10)
        tk.Label(root, text=f"Running on ws://{server.config.host}:{server.config.port}",
                 font=("Arial", 10)).pack(pady=5)
        log = tk.Text(root, height=12, state="disabled")
        log.pack(padx=10, pady=10, fill="both", expand=True)

        original_print = print
        def gui_print(*args, **kwargs):
            original_print(*args, **kwargs)
            log.config(state="normal")
            log.insert("end", " ".join(str(a) for a in args) + "\n")
            log.see("end")
            log.config(state="disabled")
        import builtins
        builtins.print = gui_print

        def on_close():
            builtins.print = original_print
            root.destroy()
            icon.visible = True

        root.protocol("WM_DELETE_WINDOW", on_close)
        root.mainloop()

    def on_quit(icon, item):
        icon.stop()
        loop.call_soon_threadsafe(server.shutdown_event.set)
        sys.exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Show Console", on_show),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon("VoiceTalkServer", icon_image, "VoiceTalk Server", menu)
    icon.run()


def get_password_gui():
    root = tk.Tk()
    root.withdraw()
    pw = simpledialog.askstring(
        "VoiceTalk Server",
        "Enter master password:",
        show="*",
        parent=root,
    )
    root.destroy()
    return pw


def main():
    server = VoiceTalkServer()
    server.setup("voicetalk")
    prompt_setup(server)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    tray_thread = threading.Thread(target=create_tray_icon, args=(server, loop), daemon=True)
    tray_thread.start()

    server.run()


if __name__ == "__main__":
    main()
