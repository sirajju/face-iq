"""Ping the FaceIQ face agent over its named pipe and verify the signed reply.

Use this to validate the agent + IPC + HMAC + camera-safety path WITHOUT touching
the Windows lock screen. Run face_agent.py first (in another terminal), then:

    .venv\\Scripts\\python.exe test_agent.py

Expected:
    OK    -> an Owner is in view right now
    DENY  -> camera works but no Owner recognized
    NOCAM -> camera disconnected / not streaming (fail-safe; provider falls back)
"""
import hashlib
import hmac
import os
import time
from pathlib import Path

import win32file
import win32pipe
import pywintypes

PIPE_NAME = r"\\.\pipe\faceiq_verify"
KEY_PATH = Path(r"C:\ProgramData\FaceIQ\ipc.key")


def main():
    if not KEY_PATH.exists():
        print(f"No key at {KEY_PATH}. Start face_agent.py first (it creates the key).")
        return 1
    key = KEY_PATH.read_bytes().strip()
    nonce = os.urandom(16).hex()

    try:
        win32pipe.WaitNamedPipe(PIPE_NAME, 8000)
    except pywintypes.error as exc:
        print(f"Pipe not available ({exc}). Is face_agent.py running?")
        return 1

    h = win32file.CreateFile(
        PIPE_NAME,
        win32file.GENERIC_READ | win32file.GENERIC_WRITE,
        0, None, win32file.OPEN_EXISTING, 0, None,
    )
    win32file.WriteFile(h, f"VERIFY {nonce}\n".encode())
    _, data = win32file.ReadFile(h, 256)
    win32file.CloseHandle(h)

    resp = data.decode(errors="ignore").strip()
    print("raw response:", resp)
    try:
        status, rnonce, ts, mac = resp.split()
    except ValueError:
        print("Malformed response.")
        return 1

    expect = hmac.new(key, f"{status} {rnonce} {ts}".encode(), hashlib.sha256).hexdigest()
    hmac_ok = hmac.compare_digest(expect, mac)
    nonce_ok = rnonce == nonce
    fresh = abs(time.time() - int(ts)) <= 10

    print(f"status       : {status}")
    print(f"hmac valid   : {hmac_ok}")
    print(f"nonce match  : {nonce_ok}  (replay protection)")
    print(f"timestamp ok : {fresh}  (freshness)")
    if hmac_ok and nonce_ok and fresh:
        print("RESULT: trustworthy signed reply [OK]")
        return 0
    print("RESULT: reply failed verification [REJECTED] (provider would refuse it)")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
