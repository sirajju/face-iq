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
import hashlib
import hmac
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

import win32pipe
import win32file
import pywintypes

from app.db import connect
from app.vision import Vision

PIPE_NAME = r"\\.\pipe\faceiq_verify"
KEY_PATH = Path(r"C:\ProgramData\FaceIQ\ipc.key")
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

    def run(self):
        cap = None
        while not self.stop_flag:
            if cap is None:
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap.release()
                    cap = cv2.VideoCapture(self.camera_index, cv2.CAP_MSMF)
                if not cap.isOpened():
                    time.sleep(1.0)
                    cap = None
                    continue
            ok, frame = cap.read()
            if not ok or frame is None:
                # Camera down / no frames -> leave last_frame_at stale (NOCAM).
                time.sleep(0.5)
                cap.release()
                cap = None
                continue
            now = time.time()
            with self.lock:
                self.last_frame_at = now
            owners = load_owner_embeddings()
            if owners:
                ok2, buf = cv2.imencode(".jpg", frame)
                if ok2:
                    try:
                        _, faces = self.vision.analyze(buf.tobytes())
                        for face in faces:
                            emb = np.asarray(face["embedding"], dtype=np.float32)
                            if any(cosine(emb, o) >= OWNER_MATCH_THRESHOLD for o in owners):
                                with self.lock:
                                    self.last_owner_at = now
                                break
                    except Exception:
                        pass
            time.sleep(0.4)
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


def handle_client(pipe, key, worker):
    try:
        _, data = win32file.ReadFile(pipe, 256)
        text = data.decode(errors="ignore").strip()
        parts = text.split()
        if len(parts) != 2 or parts[0] != "VERIFY":
            return
        nonce = parts[1][:64]
        status = worker.status()
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


def main():
    log("FaceIQ face agent starting. It only REPORTS a face result; it never signs you in.")
    key = load_key()
    try:
        vision = Vision()
    except Exception as exc:
        log(f"ERROR: vision models not ready ({exc}).")
        return 1
    worker = CameraWorker(vision)
    worker.start()
    log("Serving named pipe. Ctrl+C to stop.")
    try:
        while True:
            pipe = make_pipe()
            try:
                win32pipe.ConnectNamedPipe(pipe, None)
                handle_client(pipe, key, worker)
            finally:
                win32file.CloseHandle(pipe)
    except KeyboardInterrupt:
        log("Stopped by user.")
    finally:
        worker.stop_flag = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
