# FaceIQ — Windows Face Auto-Lock (Owner)

A safe, supported way to use FaceIQ's existing face recognition for Windows:
**lock the PC when the Owner walks away.** It deliberately does **not** unlock
Windows or replace your sign-in.

---

## 1. Feasibility assessment (why this design)

| Option evaluated | Verdict |
|---|---|
| **Windows Hello Face provider** | ❌ Not possible. A custom app can't register as a Hello Face provider; Hello Face needs IR-camera hardware + a kernel Windows Biometric Framework driver. An RGB webcam + user-space app cannot inject into it. |
| **Custom Credential Provider (native C++ COM in LogonUI)** | ⚠️ Supported, but cannot be *passwordless* safely. To log you in it must hand LSA a real credential; doing that from a face match means storing your Windows password and releasing it on a (photo-spoofable) match. It also can't easily reach the webcam on the secure desktop / session 0. Realistically only a *second factor* (face **and** you still type your PIN/password). |
| **Separate local app (this project)** | ✅ Safe **for locking only**. `LockWorkStation()` bypasses nothing. Auto-*unlock* is not achievable without bypassing the lock screen or storing a secret, so it is not implemented. |

**Hardware/model feasibility:** Your existing OpenCV **YuNet** (detection) + **SFace**
(embedding) pipeline and ordinary RGB webcam are sufficient for a convenience
walk-away lock. They do **not** provide liveness/anti-spoof assurance.

---

## 2. Architecture

```
  ┌─────────────────────────── your logged-in Windows session ───────────────────────────┐
  │                                                                                        │
  │   Browser (React UI)             FastAPI backend                 face_lock.py          │
  │   ─ enroll / recognize   ──►     ─ /api/people, /recognize       (companion process)   │
  │   ─ tick "Owner"         ──►     ─ /api/owner/* (PIN-gated)       ─ reads owners+config │
  │   ─ set PIN / arm        ──►              │                         from the SAME DB    │
  │                                           ▼                       ─ opens webcam (cv2)  │
  │                                   faceiq.sqlite3  ◄───────────────  ─ if Owner absent   │
  │                                   people.is_owner                    > grace seconds →  │
  │                                   app_settings (pin hash, armed)     LockWorkStation()  │
  │                                                                                        │
  └────────────────────────────────────────────────────────────────────────────────────────┘
                                   (never touches LSASS / lock screen / Windows credentials)
```

Recognition and authentication are **separate**: a face match only ever triggers
a **lock**. It is never treated as a Windows authentication result.

**Companion behaviours:**
- Owner absent past the grace period → **lock**.
- A **stranger** lingering while the Owner is away → lock sooner (`STRANGER_GRACE_SECONDS`, default 5s).
- Owner **returns** → wake the display + chime (convenience cue; **does not unlock** — if the PC is locked this just lights the normal sign-in screen). The spoken "welcome back" greeting also plays in the FaceIQ Live view.

---

## 3. Files changed / added

**Modified**
- `backend/app/db.py` — added `people.is_owner`; new `app_settings` table (PIN hash + auto-lock config).
- `backend/app/main.py` — `is_owner` in `public_person`; PIN hashing (PBKDF2) + settings helpers; endpoints `GET /api/owner/status`, `POST /api/owner/pin`, `POST /api/owner/verify`, `POST /api/people/{id}/owner`, `POST /api/owner/auto-lock`.
- `frontend/src/main.jsx` — Owner toggle in the profile editor, Owner badge, and a **Face auto-lock (Owner)** settings card (PIN setup, grace, arm/disarm).
- `frontend/src/style.css` — owner/auto-lock styles.

**Added**
- `backend/face_lock.py` — the auto-lock companion (lock-only).
- `WINDOWS_AUTOLOCK.md` — this document.

---

## 4. Setup & usage

1. Start the existing app (backend + frontend) as usual.
2. In the UI: **People → Edit** a profile → tick **Owner**. The first time, you'll
   create an **Owner PIN** (a FaceIQ app PIN — *not* your Windows password).
3. **Settings → Face auto-lock**: set the grace period, then **Arm auto-lock**.
4. Run the companion in your session:
   ```powershell
   cd backend
   .venv\Scripts\python.exe face_lock.py --dry-run   # TEST FIRST: logs, never locks
   .venv\Scripts\python.exe face_lock.py             # live
   ```
   Stop it any time with **Ctrl+C**.
5. (Optional) To start it automatically at logon, add a **Task Scheduler** task
   ("At log on", run the command above). Do this only after you're happy with it.

---

## 5. Security limitations & threat model

- **Not spoof-proof.** A printed photo or phone video of the Owner can satisfy an
  RGB match. This is a *convenience* control, not a security boundary. (Windows
  Hello Face resists this with IR hardware — this project does not.)
- **Lock-only.** Cannot and does not unlock Windows. No Windows password, hash,
  token, or reusable credential is stored anywhere.
- **Owner PIN** is hashed with PBKDF2-HMAC-SHA256 (200k iterations, per-install
  salt) in the local SQLite DB. It gates FaceIQ owner actions only.
- **Local only.** Embeddings, snapshots, and settings stay on this device. The
  API binds to `127.0.0.1`.
- **Failure modes are safe:** if the companion crashes, the camera is busy, or
  recognition fails, the worst case is the PC locks (or doesn't) — you always
  sign in normally.
- **Residual risks:** someone who can run code in your session could change the
  DB/settings; the DB is not encrypted at rest (use OS disk encryption). The
  companion is a convenience, assumed to run on a machine you control.

---

## 6. Testing

- `python face_lock.py --dry-run` → with Owner armed and present, logs nothing;
  cover the camera / leave view for `grace` seconds → logs **"WOULD LOCK"**.
- Flip to live only once dry-run behaves. Verify it locks after you leave and
  that returning + signing in works normally.
- Edge checks: no Owner ticked → companion idles; disarm in Settings → companion
  releases the camera and stops evaluating.

## 7. Troubleshooting

- *"vision models not ready"* → run `python download_models.py` in `backend`.
- *Won't open camera* → close other camera apps; try `--camera 1`.
- *Locks too eagerly* → raise the grace period in Settings.
- *Never locks* → confirm it's **Armed**, an **Owner** is ticked, and that Owner
  is actually enrolled with face samples.

---

## 8. Rollback (always preserves your normal Windows sign-in)

This feature never changes Windows auth, so your Windows PIN/password always
works. To remove it:

1. **Stop the companion** (Ctrl+C) and delete any Task Scheduler task you created.
2. In **Settings**, **Disarm** auto-lock (or just don't run `face_lock.py`).
3. Optional full removal: delete `backend/face_lock.py`. The `is_owner` column
   and `app_settings` rows are harmless if left; to clear them:
   ```sql
   UPDATE people SET is_owner = 0;
   DELETE FROM app_settings
     WHERE key IN ('owner_pin_hash','owner_pin_salt','auto_lock_armed','auto_lock_grace');
   ```
There is no way for this feature to lock you out of Windows: it only ever issues
a standard lock, which your normal sign-in reverses.
