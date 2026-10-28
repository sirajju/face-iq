"""Filesystem locations that work both from source and from a packaged exe.

- Read-only resources (ML models, built web UI) ship inside the app. When frozen
  by PyInstaller they live under sys._MEIPASS; from source, under backend/.
- Writable data (SQLite DB, uploaded media) goes to %LOCALAPPDATA%\\FaceIQ so the
  app works even when installed to a read-only location like Program Files.
"""
import os
import sys
from pathlib import Path


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]  # backend/


def data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FaceIQ"
    (base / "media" / "greetings").mkdir(parents=True, exist_ok=True)
    (base / "media" / "unknowns").mkdir(parents=True, exist_ok=True)
    return base


RESOURCE_DIR = resource_dir()
MODELS_DIR = RESOURCE_DIR / "models"
WEB_DIR = RESOURCE_DIR / "web"            # built frontend (copied in at package time)

DATA_DIR = data_dir()
DB_PATH = DATA_DIR / "faceiq.sqlite3"
GREETING_DIR = DATA_DIR / "media" / "greetings"
UNKNOWN_DIR = DATA_DIR / "media" / "unknowns"
