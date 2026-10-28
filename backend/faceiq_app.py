"""FaceIQ desktop launcher.

Runs the FastAPI backend (which also serves the built web UI) in-process, opens
the app in a chromeless Edge/Chrome window, and lives in the system tray so it
keeps running in the background and can be reopened or quit. This is the entry
point packaged into FaceIQ.exe.
"""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser


# A windowed exe has no console, so sys.stdout/stderr are None. Libraries (uvicorn)
# that call sys.stdout.isatty() then crash. Give them a safe no-op stream.
class _NullStream:
    def write(self, *a, **k):
        pass

    def flush(self):
        pass

    def isatty(self):
        return False


if sys.stdout is None:
    sys.stdout = _NullStream()
if sys.stderr is None:
    sys.stderr = _NullStream()

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"

_server = None  # uvicorn.Server, so the tray can stop it


def _log(msg):
    try:
        from app.paths import DATA_DIR
        path = DATA_DIR / "faceiq_app.log"
    except Exception:
        import tempfile
        path = os.path.join(tempfile.gettempdir(), "faceiq_app.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def run_server():
    global _server
    try:
        import uvicorn
        from app.main import app
        _server = uvicorn.Server(
            uvicorn.Config(app, host=HOST, port=PORT, log_level="warning", log_config=None)
        )
        _log("server starting")
        _server.run()
    except Exception:
        import traceback
        _log("run_server CRASHED:\n" + traceback.format_exc())


def wait_ready(timeout=40):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=1):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def open_ui():
    # Prefer a chromeless Edge/Chrome app window; fall back to the default browser.
    for exe in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={URL}"])
                return
            except Exception:
                pass
    webbrowser.open(URL)


def build_tray():
    import pystray
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (64, 64), "#0b1017")
    d = ImageDraw.Draw(img)
    d.ellipse((12, 12, 52, 52), outline="#5ed8a8", width=5)
    d.ellipse((26, 26, 38, 38), fill="#5ed8a8")

    def on_open(icon, item):
        open_ui()

    def on_quit(icon, item):
        if _server is not None:
            _server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open FaceIQ", on_open, default=True),
        pystray.MenuItem("Quit", on_quit),
    )
    return pystray.Icon("FaceIQ", img, "FaceIQ", menu)


def main():
    try:
        threading.Thread(target=run_server, daemon=True).start()
        if wait_ready():
            open_ui()
        # Tray must run on the main thread; blocks until Quit.
        build_tray().run()
    except Exception:
        import traceback
        _log("main CRASHED:\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
