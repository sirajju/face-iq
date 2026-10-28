import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "faceiq.sqlite3"

def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            interests TEXT NOT NULL DEFAULT '',
            consent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            first_seen TEXT,
            last_seen TEXT,
            visit_count INTEGER NOT NULL DEFAULT 0,
            embedding BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            person_id INTEGER,
            display_name TEXT NOT NULL,
            seen_at TEXT NOT NULL,
            expression TEXT NOT NULL DEFAULT 'Unknown',
            confidence REAL,
            FOREIGN KEY(person_id) REFERENCES people(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS unknown_captures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            image TEXT NOT NULL,
            embedding BLOB NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            person_id INTEGER
        );
        -- Local app settings: Owner PIN hash and auto-lock config. Never stores
        -- Windows credentials; the Owner PIN is a FaceIQ-only app secret.
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        ''')
        _migrate(con)

def _migrate(con):
    # Add columns introduced after the first release, ignoring "already exists".
    event_cols = {r["name"] for r in con.execute("PRAGMA table_info(events)")}
    if "facing" not in event_cols:
        con.execute("ALTER TABLE events ADD COLUMN facing TEXT NOT NULL DEFAULT 'Unknown'")
    people_cols = {r["name"] for r in con.execute("PRAGMA table_info(people)")}
    if "greeting" not in people_cols:
        # Optional custom spoken greeting; empty falls back to "Welcome back, <name>".
        con.execute("ALTER TABLE people ADD COLUMN greeting TEXT NOT NULL DEFAULT ''")
    if "greeting_audio" not in people_cols:
        # Filename of an uploaded greeting clip (in media/greetings); empty = use TTS.
        con.execute("ALTER TABLE people ADD COLUMN greeting_audio TEXT NOT NULL DEFAULT ''")
    if "is_owner" not in people_cols:
        # Marks a registered person as an Owner for the auto-lock companion.
        con.execute("ALTER TABLE people ADD COLUMN is_owner INTEGER NOT NULL DEFAULT 0")
