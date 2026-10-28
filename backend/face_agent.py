"""FaceIQ face agent — local IPC verifier for the credential provider.

Answers one question over an authenticated named pipe: "is an Owner in view RIGHT
NOW?" -> OK / DENY / NOCAM. It reuses the existing recognition pipeline
(app/vision.py) and the same database (Owners = people.is_owner=1).

SECURITY MODEL (read windows/README.md):
  * This NEVER authenticates anyone. It only reports a face result that the C++
    credential provider uses to GATE a tile whose password the user still types.
  * Responses are signed with HMAC-SHA256 over "<status> <nonce> <ts>" using a
    shared key file, with a per-request nonce (replay) and timestamp (freshness).
  * CAMERA SAFETY: if the webcam is disconnected or not delivering frames, the
    agent returns NOCAM (it will not claim OK or DENY), so the provider fails safe
    and the user falls back to normal sign-in. It never causes a lock.

Requires pywin32:  .venv\\Scripts\\python.exe -m pip install pywin32
Run (in your user session):  .venv\\Scripts\\python.exe face_agent.py
Stop with Ctrl+C.
"""
import argparse
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.request
from pathlib import Path

# Quiet OpenCV's VIDEOIO/DSHOW warnings when the camera is busy or absent. Must
# be set BEFORE importing cv2 to take effect.
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
os.environ.setdefault("OPENCV_VIDEOIO_DEBUG", "0")

import cv2
import numpy as np

import win32pipe
import win32file
import pywintypes

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:
    pass

from app.db import connect
from app.vision import Vision

PIPE_NAME = r"\\.\pipe\faceiq_verify"
KEY_PATH = Path(r"C:\ProgramData\FaceIQ\ipc.key")
# Shared mode (default): presence comes from the browser's recognition stream via
# the backend, so ONE camera (the browser's) serves the web app AND the agent.
BACKEND_PRESENCE_URL = "http://127.0.0.1:8000/api/owner/presence"
OWNER_MATCH_THRESHOLD = 0.42
OWNER_FRESH_SECONDS = 3.0   # treat Owner as "present" if seen within this window
FRAME_STALE_SECONDS = 3.0   # no frame within this long -> camera considered down
# Restrict the pipe to SYSTEM (credential provider host), Administrators, and the
# interactive user. GRGW = generic read/write.
PIPE_SDDL = "D:(A;;GRGW;;;SY)(A;;GRGW;;;BA)(A;;GRGW;;;IU)"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_key():
    KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not KEY_PATH.exists():
        KEY_PATH.write_bytes(os.urandom(32).hex().encode())
        log(f"Generated shared IPC key at {KEY_PATH}. Restrict its ACL to SYSTEM/Admins.")
    return KEY_PATH.read_bytes().strip()


def load_owner_embeddings():
    with connect() as con:
        rows = con.execute(
            "SELECT embedding FROM people WHERE is_owner=1 AND consent=1"
        ).fetchall()
    out = []
    for r in rows:
        v = np.frombuffer(r["embedding"], dtype=np.float32)
        if v.size:
            out.append(v)
    return out


def cosine(a, b):
    if a.size != b.size:
        return -1.0
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12))


class CameraWorker(threading.Thread):
    """Continuously samples the webcam so pipe responses are instant and reflect
    live state. Tracks last-frame time (camera health) and last owner sighting."""

    def __init__(self, vision, camera_index=0):
        super().__init__(daemon=True)
        self.vision = vision
        self.camera_index = camera_index
        self.lock = threading.Lock()
        self.last_frame_at = 0.0
        self.last_owner_at = 0.0
        self.stop_flag = False
        self._last_log = 0.0

    def _maybe_log(self, msg):
        now = time.time()
        if now - self._last_log >= 5.0:
            self._last_log = now
            log(msg)

    def run(self):
        cap = None
        backoff = 1.0  # grows while the camera is unavailable, to avoid spamming
        try:
          while not self.stop_flag:
            if cap is None:
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap.release()
                    cap = cv2.VideoCapture(self.camera_index, cv2.CAP_MSMF)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    # Busy/absent camera: back off quietly (status stays NOCAM).
                    self._maybe_log("status=NOCAM camera=DOWN (can't open - another "
                                    "app likely holds the webcam, e.g. the FaceIQ Live "
                                    "view, Zoom, Teams, or the Camera app)")
                    time.sleep(backoff)
                    backoff = min(backoff * 1.5, 5.0)
                    continue
                backoff = 1.0
            ok, frame = cap.read()
            if not ok or frame is None:
                # Camera down / no frames -> leave last_frame_at stale (NOCAM).
                cap.release()
                cap = None
                self._maybe_log("status=NOCAM camera=DOWN (opened but no frames - "
                                "the webcam is in use by another app)")
                time.sleep(backoff)
                backoff = min(backoff * 1.5, 5.0)
                continue
            backoff = 1.0
            now = time.time()
            with self.lock:
                self.last_frame_at = now
            owners = load_owner_embeddings()
            n_faces = 0
            best = -1.0
            if owners:
                ok2, buf = cv2.imencode(".jpg", frame)
                if ok2:
                    try:
                        _, faces = self.vision.analyze(buf.tobytes())
                        n_faces = len(faces)
                        for face in faces:
                            emb = np.asarray(face["embedding"], dtype=np.float32)
                            s = max((cosine(emb, o) for o in owners), default=-1.0)
                            best = max(best, s)
                            if s >= OWNER_MATCH_THRESHOLD:
                                with self.lock:
                                    self.last_owner_at = now
                    except Exception:
                        pass
            self._maybe_log(
                f"status={self.status()} camera=up faces={n_faces} "
                f"owners={len(owners)} best_owner_sim={best:.2f} "
                f"(need >= {OWNER_MATCH_THRESHOLD} to match)"
            )
            time.sleep(0.4)
        finally:
            # Always release the webcam when the worker stops (Ctrl+C included).
            if cap is not None:
                cap.release()

    def status(self):
        now = time.time()
        with self.lock:
            frame_fresh = (now - self.last_frame_at) <= FRAME_STALE_SECONDS
            owner_fresh = (now - self.last_owner_at) <= OWNER_FRESH_SECONDS
        if not frame_fresh:
            return "NOCAM"   # cannot identify -> fail safe
        return "OK" if owner_fresh else "DENY"


def sign(key, status, nonce, ts):
    msg = f"{status} {nonce} {ts}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def backend_status():
    """Shared mode: read owner presence from the backend (fed by the browser).
    Any failure -> NOCAM so the provider fails safe."""
    try:
        with urllib.request.urlopen(BACKEND_PRESENCE_URL, timeout=2) as r:
            return json.loads(r.read().decode()).get("status", "NOCAM")
    except Exception:
        return "NOCAM"


def handle_client(pipe, key, get_status):
    try:
        _, data = win32file.ReadFile(pipe, 256)
        text = data.decode(errors="ignore").strip()
        parts = text.split()
        if len(parts) != 2 or parts[0] != "VERIFY":
            return
        nonce = parts[1][:64]
        status = get_status()
        ts = int(time.time())
        resp = f"{status} {nonce} {ts} {sign(key, status, nonce, ts)}\n"
        win32file.WriteFile(pipe, resp.encode())
    except pywintypes.error:
        pass


def make_pipe():
    sa = pywintypes.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = pywintypes.SECURITY_DESCRIPTOR()
    try:
        import win32security
        sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            PIPE_SDDL, win32security.SDDL_REVISION_1
        )
        sa.SECURITY_DESCRIPTOR = sd
    except Exception:
        pass  # fall back to default pipe security
    return win32pipe.CreateNamedPipe(
        PIPE_NAME,
        win32pipe.PIPE_ACCESS_DUPLEX,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
        win32pipe.PIPE_UNLIMITED_INSTANCES,
        512, 512, 0, sa,
    )


def pipe_server(key, get_status, stop):
    # Runs in a daemon thread. The blocking ConnectNamedPipe can't be interrupted
    # by Ctrl+C, so we keep it OFF the main thread; the process exit tears it down.
    while not stop.is_set():
        try:
            pipe = make_pipe()
        except pywintypes.error:
            time.sleep(0.5)
            continue
        try:
            win32pipe.ConnectNamedPipe(pipe, None)
            handle_client(pipe, key, get_status)
        except pywintypes.error:
            pass
        finally:
            try:
                win32file.CloseHandle(pipe)
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser(description="FaceIQ face agent (pipe verifier).")
    ap.add_argument("--direct", action="store_true",
                    help="open the webcam directly instead of sharing the browser's "
                         "stream via the backend (can't run alongside the Live view)")
    ap.add_argument("--camera", type=int, default=0, help="camera index for --direct")
    args = ap.parse_args()

    log("FaceIQ face agent starting. It only REPORTS a face result; it never signs you in.")
    key = load_key()
    worker = None
    stop = threading.Event()

    if args.direct:
        try:
            vision = Vision()
        except Exception as exc:
            log(f"ERROR: vision models not ready ({exc}).")
            return 1
        worker = CameraWorker(vision, args.camera)
        worker.start()
        get_status = worker.status
        log("Mode: DIRECT (agent owns the webcam; stop the browser Live camera first).")
    else:
        get_status = backend_status
        log("Mode: SHARED (presence from the backend's recognition stream - the ONE "
            "browser camera serves the web app AND this agent).")
        log(f"Reading presence from {BACKEND_PRESENCE_URL}")

    server = threading.Thread(target=pipe_server, args=(key, get_status, stop), daemon=True)
    server.start()
    log("Serving named pipe. Press Ctrl+C to stop.")
    try:
        last_log = 0.0
        while True:
            time.sleep(0.5)
            if time.time() - last_log >= 5.0:
                last_log = time.time()
                log(f"status={get_status()}")
    except KeyboardInterrupt:
        log("Stopping…")
    finally:
        stop.set()
        if worker is not None:
            worker.stop_flag = True
            worker.join(timeout=4)
            log("Camera released.")
        log("Bye.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
