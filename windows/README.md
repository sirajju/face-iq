# FaceIQ Credential Provider (second factor) — scaffold

A native C++ **Credential Provider** that puts a FaceIQ tile on the Windows
sign-in/lock screen. It performs a **local face check** and then **requires you to
type your Windows password/PIN**. Face is a *second factor* — it never signs you
in by itself.

> ⚠️ **Honest scope.** This is **not** passwordless and **not** Windows Hello. An
> RGB webcam has no liveness (a photo can pass the face check), so face is only an
> extra gate, never the authenticator. It stores **no** Windows credentials. It
> registers as an **additional** provider — your normal password/PIN tile is
> always there, so you cannot be locked out.

## Components

| File | Role |
|---|---|
| `credential_provider/*.cpp/.h` | The COM DLL (provider + tile + KERB serialization). |
| `credential_provider/FaceIpc.*` | Authenticated named-pipe client (HMAC, nonce, timeout). |
| `credential_provider/CMakeLists.txt` | Build config. |
| `credential_provider/register.reg` | Manual registration (alt. to regsvr32). |
| `../backend/face_agent.py` | Python pipe server; reuses `Vision`; returns OK/DENY/**NOCAM**. |

Architecture: `LogonUI → FaceIQ provider tile → FaceIpc (named pipe) → face_agent.py → Vision + webcam`.
The provider serializes the **typed** password to LSA exactly like the stock
password tile; the face result only decides whether that serialization is allowed.

## Prerequisites

- **Visual Studio 2022** with "Desktop development with C++" + the **Windows 10/11 SDK**.
- **CMake 3.20+** (bundled with VS).
- Python deps for the agent: `cd backend && .venv\Scripts\python.exe -m pip install pywin32`.
- ⚠️ **Do all first-time testing in a disposable VM or VM snapshot**, or with a
  **second local Administrator account** open and signed in, so a mistake can't
  lock you out. Keep that fallback until you've verified sign-in works.

## Build

```powershell
cd windows\credential_provider
cmake -S . -B build -A x64
cmake --build build --config Release
# -> build\Release\FaceIQCredentialProvider.dll
```

Before shipping, generate your **own** CLSID (uuidgen) and replace it in both
`common.h` (`CLSID_FaceIQProvider`) and `register.reg`.

## Install

1. Start the agent in your user session:
   ```powershell
   cd backend
   .venv\Scripts\python.exe face_agent.py   # creates C:\ProgramData\FaceIQ\ipc.key on first run
   ```
   Restrict the key file's ACL to SYSTEM + Administrators (right-click → Properties → Security).
2. Copy the DLL somewhere stable, e.g. `C:\FaceIQ\FaceIQCredentialProvider.dll`.
3. Register (elevated):
   ```powershell
   regsvr32 C:\FaceIQ\FaceIQCredentialProvider.dll
   ```
   (or edit the DLL path in `register.reg` and import it.)
4. Lock the screen (Win+L). A **FaceIQ (second factor)** tile appears next to your
   normal tile. Selecting it runs the face check, then asks for your password/PIN.

## Testing

- **Agent alone:** with the agent running and you in view, it caches `OK`; leave
  view → `DENY`; unplug/cover the camera → `NOCAM`. (Add a temporary print in
  `handle_client` to watch statuses.)
- **Provider path:** on the lock screen, pick the FaceIQ tile:
  - Face OK + correct password → signs in.
  - Face denied / camera unavailable → tile shows a message; use the normal tile.
- Verify the **standard password/PIN tile still works** at every step.

## Known limitations (important)

- **Secure-desktop camera access is the hard, unsolved-for-RGB part.** The agent
  runs in your user session; whether it can read the webcam while the session is
  *locked* varies by hardware/driver. If it can't, the tile will report `NOCAM`
  and you simply use your password tile. This is exactly why Windows Hello Face
  uses dedicated IR hardware + a kernel biometric driver.
- **No liveness.** A printed photo can pass the face check. Never treat this as
  security; it's convenience + a soft second factor.
- The KERB packing helpers mirror Microsoft's public **SampleCredentialProvider**
  (MIT). If the DLL builds but sign-in fails, diff `helpers.cpp` against that
  sample for your SDK.

## Threat model (summary)

| Threat | Mitigation |
|---|---|
| Replayed/forged face "OK" over IPC | HMAC-SHA256 + per-request nonce + timestamp freshness + constant-time compare. |
| Rogue local process answering the pipe | Pipe ACL (SYSTEM/Admins/Interactive) + shared key file with restricted ACL. |
| Photo/video spoof of the Owner | Documented; face is only a second factor, password still required. |
| Lockout from a broken provider | Registered as *additional* provider; stock tile always present; rollback below. |
| Credential theft | No Windows password/hash/token is ever stored; typed password is wiped after use. |

## Rollback (cannot lock you out)

Your normal sign-in is never removed, so you can always use it. To uninstall:

1. **Unregister** (elevated):
   ```powershell
   regsvr32 /u C:\FaceIQ\FaceIQCredentialProvider.dll
   ```
   or delete these keys (also what `register.reg` created):
   - `HKCR\CLSID\{7F3B9E42-1C6A-4D2E-9B51-6F2A1E9D4C80}`
   - `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\Credential Providers\{7F3B9E42-1C6A-4D2E-9B51-6F2A1E9D4C80}`
2. Stop `face_agent.py`. Delete `C:\ProgramData\FaceIQ\ipc.key` if you want.
3. Reboot. The FaceIQ tile is gone; the standard tiles remain.

**Recovery if a tile ever misbehaves:** boot to Safe Mode (the provider is not
loaded there) or sign in with your second Administrator account, then run the
unregister step above.
