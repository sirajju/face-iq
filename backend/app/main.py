from datetime import datetime, timezone
from pathlib import Path
import json
import uuid
import hashlib
import hmac
import secrets
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from .db import connect, init_db
from .vision import Vision

# Uploaded per-person greeting clips live on disk, referenced by filename in DB.
GREETING_DIR = Path(__file__).resolve().parents[1] / "media" / "greetings"
GREETING_DIR.mkdir(parents=True, exist_ok=True)
# Snapshots of unknown visitors awaiting "who was this?" identification.
UNKNOWN_DIR = Path(__file__).resolve().parents[1] / "media" / "unknowns"
UNKNOWN_DIR.mkdir(parents=True, exist_ok=True)
UNKNOWN_DEDUP_SIMILARITY = 0.55  # skip a new snapshot if a similar one is already pending
# Allowed upload types -> file extension used on disk.
AUDIO_EXTS = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav",
              "audio/x-wav": ".wav", "audio/webm": ".webm", "audio/ogg": ".ogg",
              "audio/mp4": ".m4a", "audio/aac": ".aac"}

app = FastAPI(title="FaceIQ API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
)
vision = None
# OpenCV SFace cosine similarity. 0.363 is OpenCV's default but is tuned for
# clean frontal crops and accepts too many look-alikes; 0.42 is stricter to
# avoid matching different people. False matches -> raise it; missed real
# matches -> lower it. Tune with consented test samples.
MATCH_THRESHOLD = 0.42
# Side/profile faces are identified too, but their embeddings are noisier, so
# they must clear a higher similarity bar to avoid false matches.
SIDE_MATCH_THRESHOLD = 0.50
# Minimum detection confidence to even attempt identification. Frontal faces
# must be clearly detected; side faces are allowed a bit lower. Turned-fully-
# away faces are still tracked (boxed/logged) but never identified.
IDENTIFY_MIN_DETECTION = 0.90
SIDE_MIN_DETECTION = 0.80

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def public_person(row):
    return {
        "id": row["id"], "name": row["name"], "notes": row["notes"],
        "interests": row["interests"], "consent": bool(row["consent"]),
        "greeting": row["greeting"] if "greeting" in row.keys() else "",
        "has_greeting_audio": bool(row["greeting_audio"]) if "greeting_audio" in row.keys() else False,
        "is_owner": bool(row["is_owner"]) if "is_owner" in row.keys() else False,
        "created_at": row["created_at"], "first_seen": row["first_seen"],
        "last_seen": row["last_seen"], "visit_count": row["visit_count"]
    }

def embedding_from_blob(blob):
    return np.frombuffer(blob, dtype=np.float32)

def cosine(a, b):
    if a.size != b.size:
        return -1.0
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12))

# --- Owner PIN & app settings --------------------------------------------
# The Owner PIN is a FaceIQ-only app secret used to gate owner actions and the
# auto-lock companion. It is hashed (PBKDF2) and is NEVER a Windows credential.
PIN_ITERATIONS = 200_000

def get_setting(con, key, default=None):
    row = con.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_setting(con, key, value):
    con.execute(
        "INSERT INTO app_settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )

def hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, PIN_ITERATIONS).hex()

def owner_pin_is_set(con):
    return get_setting(con, "owner_pin_hash") is not None

def verify_owner_pin(con, pin):
    stored = get_setting(con, "owner_pin_hash")
    salt_hex = get_setting(con, "owner_pin_salt")
    if not stored or not salt_hex:
        return False
    return hmac.compare_digest(hash_pin(pin, bytes.fromhex(salt_hex)), stored)

def person_from_embeddings(con, name, embeddings, notes):
    """Create a consenting person from one or more embeddings; returns the row."""
    mean = np.mean(np.stack(embeddings), axis=0).astype(np.float32)
    mean /= (np.linalg.norm(mean) + 1e-12)
    ts = now()
    cur = con.execute(
        "INSERT INTO people(name, notes, interests, consent, created_at, first_seen, last_seen, visit_count, embedding) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (name.strip(), notes, "", 1, ts, ts, ts, 1, mean.tobytes())
    )
    pid = cur.lastrowid
    con.execute("INSERT INTO events(person_id,display_name,seen_at,expression,confidence,facing) VALUES(?,?,?,?,?,?)",
                (pid, name.strip(), ts, "Neutral / unclear", 1.0, "Looking at camera"))
    return con.execute("SELECT * FROM people WHERE id=?", (pid,)).fetchone()

def match_embedding(embedding, threshold=MATCH_THRESHOLD):
    best, best_score = None, -1.0
    with connect() as con:
        rows = con.execute("SELECT * FROM people WHERE consent=1").fetchall()
    for row in rows:
        saved = embedding_from_blob(row["embedding"])
        if saved.size != embedding.size:
            continue
        score = float(np.dot(embedding, saved) / ((np.linalg.norm(embedding)*np.linalg.norm(saved))+1e-12))
        if score > best_score:
            best, best_score = row, score
    if best is not None and best_score >= threshold:
        return best, best_score
    return None, max(0.0, best_score)

@app.on_event("startup")
def startup():
    global vision
    init_db()
    try:
        vision = Vision()
    except Exception as exc:
        # App still starts so the frontend can explain setup errors.
        print(f"VISION INITIALIZATION ERROR: {exc}")

@app.get("/api/health")
def health():
    return {"ok": True, "vision_ready": vision is not None,
            "message": None if vision else "Vision models not ready. Run backend/download_models.py and restart."}

@app.get("/api/people")
def people():
    with connect() as con:
        rows = con.execute("SELECT * FROM people ORDER BY last_seen DESC, name COLLATE NOCASE").fetchall()
    return [public_person(r) for r in rows]

class EnrollBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=2000)
    interests: str = Field(default="", max_length=500)
    consent: bool
    embeddings: list[list[float]]

@app.post("/api/people")
def enroll(body: EnrollBody):
    if not body.consent:
        raise HTTPException(400, "Consent must be confirmed before enrollment.")
    if len(body.embeddings) < 3:
        raise HTTPException(400, "Capture at least 3 face samples.")
    vectors = [np.asarray(v, dtype=np.float32) for v in body.embeddings]
    if any(v.ndim != 1 or not np.isfinite(v).all() for v in vectors):
        raise HTTPException(400, "Invalid face embedding.")
    if len({v.size for v in vectors}) != 1:
        raise HTTPException(400, "Face samples do not match.")
    mean = np.mean(np.stack(vectors), axis=0).astype(np.float32)
    mean /= (np.linalg.norm(mean) + 1e-12)
    with connect() as con:
        cur = con.execute(
            "INSERT INTO people(name, notes, interests, consent, created_at, embedding) VALUES(?,?,?,?,?,?)",
            (body.name.strip(), body.notes, body.interests, 1, now(), mean.tobytes())
        )
        person_id = cur.lastrowid
        row = con.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return public_person(row)

class QuickEnrollBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # One or more embeddings for the same unknown face, taken straight from the
    # /recognize response. Fewer samples than full enrollment, so slightly less
    # reliable — good enough to name someone on the spot and recognize them later.
    embeddings: list[list[float]] = Field(min_length=1)

def _validate_vectors(embeddings):
    vectors = [np.asarray(v, dtype=np.float32) for v in embeddings]
    if any(v.ndim != 1 or v.size == 0 or not np.isfinite(v).all() for v in vectors):
        raise HTTPException(400, "Invalid face embedding.")
    if len({v.size for v in vectors}) != 1:
        raise HTTPException(400, "Face samples do not match.")
    return vectors

@app.post("/api/people/quick")
def quick_enroll(body: QuickEnrollBody):
    vectors = _validate_vectors(body.embeddings)
    with connect() as con:
        row = person_from_embeddings(con, body.name, vectors, "Named from live view.")
    return public_person(row)

@app.delete("/api/people/{person_id}")
def delete_person(person_id: int):
    with connect() as con:
        row = con.execute("SELECT greeting_audio FROM people WHERE id=?", (person_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Person not found.")
        _remove_greeting_file(row["greeting_audio"])
        con.execute("DELETE FROM people WHERE id=?", (person_id,))
    return {"ok": True}

class UpdateBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    notes: str = Field(default="", max_length=2000)
    interests: str = Field(default="", max_length=500)
    greeting: str = Field(default="", max_length=200)

@app.patch("/api/people/{person_id}")
def update_person(person_id: int, body: UpdateBody):
    with connect() as con:
        cur = con.execute("UPDATE people SET name=?, notes=?, interests=?, greeting=? WHERE id=?",
                          (body.name.strip(), body.notes, body.interests, body.greeting.strip(), person_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Person not found.")
        row = con.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return public_person(row)

def _remove_greeting_file(stored):
    if stored:
        try:
            (GREETING_DIR / stored).unlink(missing_ok=True)
        except Exception:
            pass

@app.post("/api/people/{person_id}/greeting-audio")
async def upload_greeting_audio(person_id: int, clip: UploadFile = File(...)):
    ext = AUDIO_EXTS.get((clip.content_type or "").lower())
    if not ext:
        raise HTTPException(400, "Unsupported audio type. Use mp3, wav, ogg, webm, m4a or aac.")
    raw = await clip.read()
    if not raw:
        raise HTTPException(400, "Empty audio file.")
    if len(raw) > 5_000_000:
        raise HTTPException(413, "Audio too large (max 5 MB).")
    with connect() as con:
        row = con.execute("SELECT greeting_audio FROM people WHERE id=?", (person_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Person not found.")
        _remove_greeting_file(row["greeting_audio"])  # replace any previous clip
        filename = f"person_{person_id}{ext}"
        (GREETING_DIR / filename).write_bytes(raw)
        con.execute("UPDATE people SET greeting_audio=? WHERE id=?", (filename, person_id))
        updated = con.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return public_person(updated)

@app.get("/api/people/{person_id}/greeting-audio")
def get_greeting_audio(person_id: int):
    with connect() as con:
        row = con.execute("SELECT greeting_audio FROM people WHERE id=?", (person_id,)).fetchone()
    if not row or not row["greeting_audio"]:
        raise HTTPException(404, "No greeting audio.")
    path = GREETING_DIR / row["greeting_audio"]
    if not path.exists():
        raise HTTPException(404, "No greeting audio.")
    return FileResponse(str(path))

@app.delete("/api/people/{person_id}/greeting-audio")
def delete_greeting_audio(person_id: int):
    with connect() as con:
        row = con.execute("SELECT greeting_audio FROM people WHERE id=?", (person_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Person not found.")
        _remove_greeting_file(row["greeting_audio"])
        con.execute("UPDATE people SET greeting_audio='' WHERE id=?", (person_id,))
        updated = con.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return public_person(updated)

def _remove_unknown_file(stored):
    if stored:
        try:
            (UNKNOWN_DIR / stored).unlink(missing_ok=True)
        except Exception:
            pass

def public_capture(row):
    return {"id": row["id"], "captured_at": row["captured_at"],
            "image_url": f"/api/unknown-captures/{row['id']}/image"}

@app.post("/api/unknown-captures")
async def add_unknown_capture(frame: UploadFile = File(...)):
    # Called by the frontend ONLY after an unknown face has persisted past the
    # grace window (so warm-up frames of known people are never captured here).
    if vision is None:
        raise HTTPException(503, "Vision models are not ready.")
    raw = await frame.read()
    if len(raw) > 8_000_000:
        raise HTTPException(413, "Frame too large.")
    try:
        _, faces = vision.analyze(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not faces:
        raise HTTPException(400, "No face found in snapshot.")
    # Largest (closest) face is the subject of the snapshot.
    face = max(faces, key=lambda f: f["box"]["width"] * f["box"]["height"])
    emb = np.asarray(face["embedding"], dtype=np.float32)
    # If this face is actually a known person, don't file it as unknown.
    person, _ = match_embedding(emb)
    if person is not None:
        return {"saved": False, "reason": "known"}
    with connect() as con:
        pending = con.execute("SELECT id, embedding FROM unknown_captures WHERE resolved=0").fetchall()
        for r in pending:
            if cosine(emb, embedding_from_blob(r["embedding"])) >= UNKNOWN_DEDUP_SIMILARITY:
                return {"saved": False, "reason": "duplicate", "capture_id": r["id"]}
        fname = f"{uuid.uuid4().hex}.jpg"
        (UNKNOWN_DIR / fname).write_bytes(raw)
        cur = con.execute(
            "INSERT INTO unknown_captures(captured_at, image, embedding, resolved) VALUES(?,?,?,0)",
            (now(), fname, emb.tobytes())
        )
        capture_id = cur.lastrowid
    return {"saved": True, "capture_id": capture_id}

@app.get("/api/unknown-captures")
def list_unknown_captures():
    with connect() as con:
        rows = con.execute("SELECT * FROM unknown_captures WHERE resolved=0 ORDER BY id DESC").fetchall()
    return [public_capture(r) for r in rows]

@app.get("/api/unknown-captures/{capture_id}/image")
def unknown_capture_image(capture_id: int):
    with connect() as con:
        row = con.execute("SELECT image FROM unknown_captures WHERE id=?", (capture_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Capture not found.")
    path = UNKNOWN_DIR / row["image"]
    if not path.exists():
        raise HTTPException(404, "Capture image missing.")
    return FileResponse(str(path))

class IdentifyCaptureBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)

@app.post("/api/unknown-captures/{capture_id}/identify")
def identify_unknown_capture(capture_id: int, body: IdentifyCaptureBody):
    with connect() as con:
        row = con.execute("SELECT * FROM unknown_captures WHERE id=? AND resolved=0", (capture_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Capture not found or already resolved.")
        emb = embedding_from_blob(row["embedding"])
        person = person_from_embeddings(con, body.name, [emb], "Identified from an unknown snapshot.")
        con.execute("UPDATE unknown_captures SET resolved=1, person_id=? WHERE id=?", (person["id"], capture_id))
    _remove_unknown_file(row["image"])  # keep only the embedding once named
    return public_person(person)

@app.delete("/api/unknown-captures/{capture_id}")
def dismiss_unknown_capture(capture_id: int):
    with connect() as con:
        row = con.execute("SELECT image FROM unknown_captures WHERE id=?", (capture_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Capture not found.")
        _remove_unknown_file(row["image"])
        con.execute("DELETE FROM unknown_captures WHERE id=?", (capture_id,))
    return {"ok": True}

class SetPinBody(BaseModel):
    pin: str = Field(min_length=4, max_length=32)
    current_pin: str | None = None

class VerifyPinBody(BaseModel):
    pin: str = Field(min_length=1, max_length=32)

class OwnerFlagBody(BaseModel):
    is_owner: bool
    pin: str = Field(min_length=1, max_length=32)

class AutoLockBody(BaseModel):
    armed: bool
    grace_seconds: int = Field(default=20, ge=5, le=600)
    pin: str = Field(min_length=1, max_length=32)

@app.get("/api/owner/status")
def owner_status():
    with connect() as con:
        pin_set = owner_pin_is_set(con)
        owners = con.execute("SELECT id, name FROM people WHERE is_owner=1").fetchall()
        armed = get_setting(con, "auto_lock_armed", "0") == "1"
        grace = int(get_setting(con, "auto_lock_grace", "20") or 20)
    return {"pin_set": pin_set, "owners": [dict(o) for o in owners],
            "auto_lock_armed": armed, "auto_lock_grace": grace}

@app.post("/api/owner/pin")
def set_owner_pin(body: SetPinBody):
    with connect() as con:
        if owner_pin_is_set(con):
            # Changing an existing PIN requires the current one.
            if not body.current_pin or not verify_owner_pin(con, body.current_pin):
                raise HTTPException(403, "Current Owner PIN is incorrect.")
        salt = secrets.token_bytes(16)
        set_setting(con, "owner_pin_salt", salt.hex())
        set_setting(con, "owner_pin_hash", hash_pin(body.pin, salt))
    return {"ok": True, "pin_set": True}

@app.post("/api/owner/verify")
def verify_pin(body: VerifyPinBody):
    with connect() as con:
        if not verify_owner_pin(con, body.pin):
            raise HTTPException(403, "Incorrect Owner PIN.")
    return {"ok": True}

@app.post("/api/people/{person_id}/owner")
def set_person_owner(person_id: int, body: OwnerFlagBody):
    with connect() as con:
        if not owner_pin_is_set(con):
            raise HTTPException(400, "Set an Owner PIN before assigning owners.")
        if not verify_owner_pin(con, body.pin):
            raise HTTPException(403, "Incorrect Owner PIN.")
        row = con.execute("SELECT id FROM people WHERE id=?", (person_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Person not found.")
        con.execute("UPDATE people SET is_owner=? WHERE id=?",
                    (1 if body.is_owner else 0, person_id))
        updated = con.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return public_person(updated)

@app.post("/api/owner/auto-lock")
def set_auto_lock(body: AutoLockBody):
    with connect() as con:
        if not verify_owner_pin(con, body.pin):
            raise HTTPException(403, "Incorrect Owner PIN.")
        set_setting(con, "auto_lock_armed", "1" if body.armed else "0")
        set_setting(con, "auto_lock_grace", str(body.grace_seconds))
    return {"ok": True, "auto_lock_armed": body.armed, "auto_lock_grace": body.grace_seconds}

@app.get("/api/events")
def events(limit: int = 100):
    limit = max(1, min(limit, 500))
    with connect() as con:
        rows = con.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/stats")
def stats():
    with connect() as con:
        people_count = con.execute("SELECT COUNT(*) FROM people").fetchone()[0]
        known_visits = con.execute("SELECT COALESCE(SUM(visit_count),0) FROM people").fetchone()[0]
        events_count = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        unknown_count = con.execute("SELECT COUNT(*) FROM events WHERE person_id IS NULL").fetchone()[0]
        pending_unknowns = con.execute("SELECT COUNT(*) FROM unknown_captures WHERE resolved=0").fetchone()[0]
    return {"people": people_count, "known_visits": known_visits,
            "events": events_count, "unknown_events": unknown_count,
            "pending_unknowns": pending_unknowns}

@app.post("/api/enrollment-sample")
async def enrollment_sample(frame: UploadFile = File(...)):
    if vision is None:
        raise HTTPException(503, "Vision models are not ready. Run python download_models.py and restart the API.")
    raw = await frame.read()
    if len(raw) > 8_000_000:
        raise HTTPException(413, "Frame too large.")
    try:
        _, faces = vision.analyze(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not faces:
        return {"faces": []}
    # Enrollment endpoint is local-only by default; keep it bound to localhost in development.
    return {"faces": [{"embedding": faces[0]["embedding"], "box": faces[0]["box"]}]}

@app.post("/api/recognize")
async def recognize(frame: UploadFile = File(...)):
    if vision is None:
        raise HTTPException(503, "Vision models are not ready. Run python download_models.py and restart the API.")
    raw = await frame.read()
    if len(raw) > 8_000_000:
        raise HTTPException(413, "Frame too large.")
    try:
        _, faces = vision.analyze(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    output = []
    for face in faces:
        embedding = np.asarray(face["embedding"], dtype=np.float32)
        # Gate identification on face quality. Frontal and side faces are both
        # identified (side faces need a stricter similarity bar); only a fully
        # turned-away or low-confidence crop is tracked without being matched,
        # so we don't label a stranger as a saved person. Either way the face
        # is still detected, boxed and logged.
        facing, det = face["facing"], face["detection_score"]
        if facing == "Looking at camera" and det >= IDENTIFY_MIN_DETECTION:
            person, score = match_embedding(embedding)
            clear_enough = True
        elif facing == "Turned to the side" and det >= SIDE_MIN_DETECTION:
            person, score = match_embedding(embedding, SIDE_MATCH_THRESHOLD)
            clear_enough = True
        else:
            person, score = None, 0.0
            clear_enough = False
        display = "Unknown visitor"
        person_id = None
        greeting = None
        has_audio = False
        if person is not None:
            person_id = person["id"]
            display = person["name"]
            greeting = (person["greeting"] if "greeting" in person.keys() else "") or None
            has_audio = bool(person["greeting_audio"]) if "greeting_audio" in person.keys() else False
            timestamp = now()
            with connect() as con:
                # Debounce repeat events: one event per person per 30 seconds.
                previous = con.execute(
                    "SELECT seen_at FROM events WHERE person_id=? ORDER BY id DESC LIMIT 1",
                    (person_id,)
                ).fetchone()
                should_log = True
                if previous:
                    try:
                        delta = (datetime.fromisoformat(timestamp) - datetime.fromisoformat(previous["seen_at"])).total_seconds()
                        should_log = delta >= 30
                    except Exception:
                        pass
                if should_log:
                    con.execute("UPDATE people SET first_seen=COALESCE(first_seen,?), last_seen=?, visit_count=visit_count+1 WHERE id=?",
                                (timestamp, timestamp, person_id))
                    con.execute("INSERT INTO events(person_id,display_name,seen_at,expression,confidence,facing) VALUES(?,?,?,?,?,?)",
                                (person_id, display, timestamp, face["expression"], score, face["facing"]))
        else:
            # Unknown events are rate-limited globally to avoid flooding the event log.
            timestamp = now()
            with connect() as con:
                latest = con.execute("SELECT seen_at FROM events WHERE person_id IS NULL ORDER BY id DESC LIMIT 1").fetchone()
                log_unknown = True
                if latest:
                    try:
                        log_unknown = (datetime.fromisoformat(timestamp)-datetime.fromisoformat(latest["seen_at"])).total_seconds() >= 30
                    except Exception:
                        pass
                if log_unknown:
                    con.execute("INSERT INTO events(person_id,display_name,seen_at,expression,confidence,facing) VALUES(NULL,?,?,?,?,?)",
                                (display, timestamp, face["expression"], score, face["facing"]))
        output.append({
            "name": display, "known": person is not None, "person_id": person_id,
            "similarity": round(score, 3), "box": face["box"],
            "expression": face["expression"], "expression_note": face["expression_note"],
            "facing": face["facing"], "detection_score": face["detection_score"],
            # Whether this face was clear enough to attempt identification.
            "recognizable": clear_enough,
            # Custom spoken greeting for a recognized person (None -> default).
            "greeting": greeting,
            # True if an uploaded audio clip should play instead of TTS.
            "has_greeting_audio": has_audio,
            # Enrollment needs a frontal, high-quality face for a good embedding.
            "enroll_ready": (face["facing"] == "Looking at camera"
                             and face["detection_score"] >= IDENTIFY_MIN_DETECTION),
            # Embedding is returned so an unknown face can be named & saved from
            # the live view without re-capturing dedicated enrollment samples.
            "embedding": face["embedding"] if person is None else None,
        })
    return {"faces": output, "processed_at": now()}
