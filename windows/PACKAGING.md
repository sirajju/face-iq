# FaceIQ as a Windows app

FaceIQ runs as a single tray application (`FaceIQ.exe`) that serves its own UI and
API locally and opens a chromeless window. No `npm run dev` / `uvicorn` needed.

## One-time prerequisites
- Node.js + npm (for the frontend build)
- The backend venv with build deps: `pyinstaller`, `pystray`, `pillow`
  (`backend\.venv\Scripts\python.exe -m pip install pyinstaller pystray pillow`)

## Build
```powershell
powershell -ExecutionPolicy Bypass -File windows\build-faceiq.ps1
```
Produces `backend\dist\FaceIQ\FaceIQ.exe` (bundles Python, OpenCV, the ML models,
and the built web UI).

## Install + autostart
```powershell
powershell -ExecutionPolicy Bypass -File windows\install-faceiq.ps1
```
Copies the app to `%LOCALAPPDATA%\Programs\FaceIQ`, adds a **Startup** shortcut so
it launches at every logon, and starts it. Per-user; no admin needed.

## Using it
- A tray icon (bottom-right) appears. **Double-click** it to open the window;
  **right-click → Quit** to stop.
- First launch: the window asks for **camera permission** — allow it.
- Data (SQLite DB, uploaded media) lives in `%LOCALAPPDATA%\FaceIQ` and survives
  rebuilds/reinstalls. Logs: `%LOCALAPPDATA%\FaceIQ\faceiq_app.log`.

## Update after code changes
Re-run `build-faceiq.ps1` then `install-faceiq.ps1`.

## Uninstall
```powershell
powershell -ExecutionPolicy Bypass -File windows\uninstall-faceiq.ps1
```
Removes the autostart shortcut and the installed app. Your data folder
`%LOCALAPPDATA%\FaceIQ` is kept — delete it manually to remove everything.
