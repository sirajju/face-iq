"""FaceIQ auto-lock companion.

Runs in YOUR logged-in Windows session and locks the workstation when the
Owner's face has been absent for a grace period. It reuses the existing FaceIQ
recognition pipeline (app/vision.py) and the same SQLite database.

SECURITY MODEL (read this):
  * This tool ONLY locks the PC (user32.LockWorkStation). It can never unlock
    it, never bypasses the Windows lock screen, and stores no Windows
    credentials. Unlocking always uses your normal Windows PIN/password.
  * It locks sooner when a stranger lingers while the Owner is away, and when
    the Owner returns it wakes the display and chimes (a convenience cue only -
    waking the screen just shows the normal sign-in; it does NOT unlock).
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
POLL_SECONDS = 2.0           # how often to sample the camera
STARTUP_GRACE_SECONDS = 10   # never lock during this warm-up after launch
POST_LOCK_COOLDOWN = 30      # after locking, pause before evaluating again
STRANGER_GRACE_SECONDS = 5   # lock faster when a non-owner is present and owner is away


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


def open_camera(index):
    """Open the webcam, trying backends in order. Returns a cap or None."""
    for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
        cap = cv2.VideoCapture(index, backend)
        if cap.isOpened():
            return cap
        cap.release()
    return None


def scan(vision, frame, owners):
    """Return (owner_seen, stranger_seen) for the faces in this frame."""
    ok, buf = cv2.imencode(".jpg", frame)
    if not ok:
        return (False, False)
    try:
        _, faces = vision.analyze(buf.tobytes())
    except Exception:
        return (False, False)
    owner_seen = stranger_seen = False
    for face in faces:
        emb = np.asarray(face["embedding"], dtype=np.float32)
        if any(cosine(emb, o) >= OWNER_MATCH_THRESHOLD for o in owners):
            owner_seen = True
        else:
            stranger_seen = True
    return owner_seen, stranger_seen


def lock_workstation(dry_run, reason):
    if dry_run:
        log(f"WOULD LOCK (dry-run) - {reason}.")
        return
    log(f"Locking workstation ({reason}).")
    ctypes.windll.user32.LockWorkStation()


def on_owner_return(dry_run):
    """Owner is back in view: wake the display and chime. Never unlocks Windows.
    If the PC is locked this only lights up the normal sign-in screen."""
    log("Welcome back, Owner." + (" (dry-run)" if dry_run else ""))
    try:
        # ES_CONTINUOUS | ES_DISPLAY_REQUIRED: nudge the display awake, then
        # clear the request so we don't prevent normal sleep afterwards.
        ES_CONTINUOUS = 0x80000000
        ES_DISPLAY_REQUIRED = 0x00000002
        k32 = ctypes.windll.kernel32
        k32.SetThreadExecutionState(ES_CONTINUOUS | ES_DISPLAY_REQUIRED)
        k32.SetThreadExecutionState(ES_CONTINUOUS)
    except Exception:
        pass
    try:
        import winsound
        winsound.Beep(880, 150)
        winsound.Beep(1320, 180)
    except Exception:
        pass


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
    owner_was_present = True  # avoid a spurious "welcome back" on first sight
    read_fail = 0
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
                owner_was_present = True
                continue

            if cap is None:
                cap = open_camera(args.camera)
                if cap is None:
                    log(f"Camera {args.camera} is in use or unavailable - it's "
                        "likely held by another app (the FaceIQ Live view, Zoom, "
                        "Teams, the Camera app). Close that so auto-lock can see "
                        "the webcam. Retrying…")
                    time.sleep(POLL_SECONDS)
                    continue
                last_seen_owner = time.time()  # fresh warm-up when (re)opening
                owner_was_present = True
                read_fail = 0

            ok, frame = cap.read()
            if not ok or frame is None:
                # Opened but no frames: camera busy (another app holds it), the PC
                # is locked, or the device was unplugged. We cannot identify anyone,
                # so DO NOT lock — and reset the absence timer so we don't lock the
                # instant frames come back.
                read_fail += 1
                last_seen_owner = time.time()
                if read_fail == 3 or read_fail % 15 == 0:
                    log("Camera returns no frames - can't identify, so NOT locking. "
                        "It's likely in use by another app (FaceIQ Live view, Zoom, "
                        "Teams, Camera), the PC is locked, or the webcam was unplugged.")
                if read_fail % 15 == 0:
                    cap.release()
                    cap = None
                time.sleep(POLL_SECONDS)
                continue
            read_fail = 0

            owner_seen, stranger_seen = scan(vision, frame, owners)
            now = time.time()
            if owner_seen:
                if not owner_was_present:
                    on_owner_return(args.dry_run)  # wake display + chime (no unlock)
                owner_was_present = True
                last_seen_owner = now
            else:
                owner_was_present = False
                # A stranger lingering while the owner is away locks sooner.
                effective_grace = (
                    min(grace, STRANGER_GRACE_SECONDS) if stranger_seen else grace
                )
                if now - last_seen_owner >= effective_grace:
                    reason = (
                        "stranger present, owner away"
                        if stranger_seen
                        else "owner absent"
                    )
                    lock_workstation(args.dry_run, reason)
                    last_seen_owner = now + POST_LOCK_COOLDOWN

            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        log("Stopped by user.")
    finally:
        if cap is not None:
            cap.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
