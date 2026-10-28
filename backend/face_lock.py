"""FaceIQ auto-lock companion.

Runs in YOUR logged-in Windows session and locks the workstation when the
Owner's face has been absent for a grace period. It reuses the existing FaceIQ
recognition pipeline (app/vision.py) and the same SQLite database.

SECURITY MODEL (read this):
  * This tool ONLY locks the PC (user32.LockWorkStation). It can never unlock
    it, never bypasses the Windows lock screen, and stores no Windows
    credentials. Unlocking always uses your normal Windows PIN/password.
  * An RGB webcam match is NOT a liveness/anti-spoof guarantee. Treat this as a
    convenience "walk-away lock", not a security boundary.
  * Locking is always safe and fully recoverable: if anything misbehaves you
    just sign in again as usual.

USAGE:
  cd backend
  .venv\\Scripts\\python.exe face_lock.py            # live (reads arm/grace from DB)
  .venv\\Scripts\\python.exe face_lock.py --dry-run   # logs "WOULD LOCK", never locks
  .venv\\Scripts\\python.exe face_lock.py --camera 1  # pick a different webcam index

Stop it any time with Ctrl+C.
"""
import argparse
import sys
import time
import ctypes

import cv2
import numpy as np

from app.db import connect
from app.vision import Vision

# Cosine similarity to accept a face as an Owner. Matches the frontal threshold
# used by the API; raise for stricter, lower for more lenient.
OWNER_MATCH_THRESHOLD = 0.42
POLL_SECONDS = 2.0          # how often to sample the camera
STARTUP_GRACE_SECONDS = 10  # never lock during this warm-up after launch
POST_LOCK_COOLDOWN = 30     # after locking, pause before evaluating again


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


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


def read_settings():
    with connect() as con:
        armed = con.execute(
            "SELECT value FROM app_settings WHERE key='auto_lock_armed'"
        ).fetchone()
        grace = con.execute(
            "SELECT value FROM app_settings WHERE key='auto_lock_grace'"
        ).fetchone()
    armed = bool(armed and armed["value"] == "1")
    grace = int(grace["value"]) if grace and grace["value"].isdigit() else 20
    return armed, grace


def cosine(a, b):
    if a.size != b.size:
        return -1.0
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12))


def owner_present(vision, frame, owners):
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return False
    try:
        _, faces = vision.analyze(buf.tobytes())
    except Exception:
        return False
    for face in faces:
        emb = np.asarray(face["embedding"], dtype=np.float32)
        if any(cosine(emb, o) >= OWNER_MATCH_THRESHOLD for o in owners):
            return True
    return False


def lock_workstation(dry_run):
    if dry_run:
        log("WOULD LOCK (dry-run) — owner absent past grace period.")
        return
    log("Locking workstation (owner absent).")
    ctypes.windll.user32.LockWorkStation()


def main():
    ap = argparse.ArgumentParser(description="FaceIQ auto-lock companion (locks only).")
    ap.add_argument("--dry-run", action="store_true", help="log instead of locking")
    ap.add_argument("--camera", type=int, default=0, help="webcam index (default 0)")
    ap.add_argument("--grace", type=int, default=None, help="override grace seconds")
    args = ap.parse_args()

    log("FaceIQ auto-lock companion starting. This tool only LOCKS, never unlocks.")
    log("Press Ctrl+C to stop. Unlocking always uses your normal Windows sign-in.")
    if args.dry_run:
        log("DRY-RUN mode: it will never actually lock.")

    try:
        vision = Vision()
    except Exception as exc:
        log(f"ERROR: vision models not ready ({exc}). Run download_models.py first.")
        return 1

    cap = None
    last_seen_owner = time.time() + STARTUP_GRACE_SECONDS  # warm-up
    try:
        while True:
            armed, db_grace = read_settings()
            grace = args.grace if args.grace is not None else db_grace
            owners = load_owner_embeddings()

            if not armed or not owners:
                if cap is not None:
                    cap.release()
                    cap = None
                if not owners:
                    log("No Owner enrolled - idle. Tick an Owner in FaceIQ.")
                time.sleep(POLL_SECONDS)
                last_seen_owner = time.time()  # don't lock the instant we arm
                continue

            if cap is None:
                cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    log(f"Could not open camera {args.camera}; retrying…")
                    cap = None
                    time.sleep(POLL_SECONDS)
                    continue
                last_seen_owner = time.time()  # fresh warm-up when (re)opening

            ok, frame = cap.read()
            if not ok or frame is None:
                # Camera unavailable (e.g., PC already locked). Do nothing.
                time.sleep(POLL_SECONDS)
                continue

            if owner_present(vision, frame, owners):
                last_seen_owner = time.time()
            elif time.time() - last_seen_owner >= grace:
                lock_workstation(args.dry_run)
                last_seen_owner = time.time() + POST_LOCK_COOLDOWN

            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("Stopped by user.")
    finally:
        if cap is not None:
            cap.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
