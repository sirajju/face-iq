from datetime import datetime, timezone
from pathlib import Path
import json
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .db import connect, init_db
from .vision import Vision

app = FastAPI(title="FaceIQ API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False, allow_methods=["*"], allow_headers=["*"],
)
vision = None
MATCH_THRESHOLD = 0.363  # OpenCV SFace cosine similarity; tune with consented test samples.

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def public_person(row):
    return {
        "id": row["id"], "name": row["name"], "notes": row["notes"],
        "interests": row["interests"], "consent": bool(row["consent"]),
        "created_at": row["created_at"], "first_seen": row["first_seen"],
        "last_seen": row["last_seen"], "visit_count": row["visit_count"]
    }

def embedding_from_blob(blob):
    return np.frombuffer(blob, dtype=np.float32)

def match_embedding(embedding):
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
    if best is not None and best_score >= MATCH_THRESHOLD:
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

@app.post("/api/people/quick")
def quick_enroll(body: QuickEnrollBody):
    vectors = [np.asarray(v, dtype=np.float32) for v in body.embeddings]
    if any(v.ndim != 1 or v.size == 0 or not np.isfinite(v).all() for v in vectors):
        raise HTTPException(400, "Invalid face embedding.")
    if len({v.size for v in vectors}) != 1:
        raise HTTPException(400, "Face samples do not match.")
    mean = np.mean(np.stack(vectors), axis=0).astype(np.float32)
    mean /= (np.linalg.norm(mean) + 1e-12)
    timestamp = now()
    with connect() as con:
        cur = con.execute(
            "INSERT INTO people(name, notes, interests, consent, created_at, first_seen, last_seen, visit_count, embedding) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (body.name.strip(), "Named from live view.", "", 1, timestamp, timestamp, timestamp, 1, mean.tobytes())
        )
        person_id = cur.lastrowid
        con.execute("INSERT INTO events(person_id,display_name,seen_at,expression,confidence,facing) VALUES(?,?,?,?,?,?)",
                    (person_id, body.name.strip(), timestamp, "Neutral / unclear", 1.0, "Looking at camera"))
        row = con.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return public_person(row)

@app.delete("/api/people/{person_id}")
def delete_person(person_id: int):
    with connect() as con:
        row = con.execute("SELECT id FROM people WHERE id=?", (person_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Person not found.")
        con.execute("DELETE FROM people WHERE id=?", (person_id,))
    return {"ok": True}

class UpdateBody(BaseModel):
    notes: str = Field(default="", max_length=2000)
    interests: str = Field(default="", max_length=500)

@app.patch("/api/people/{person_id}")
def update_person(person_id: int, body: UpdateBody):
    with connect() as con:
        cur = con.execute("UPDATE people SET notes=?, interests=? WHERE id=?",
                          (body.notes, body.interests, person_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Person not found.")
        row = con.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
    return public_person(row)

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
    return {"people": people_count, "known_visits": known_visits,
            "events": events_count, "unknown_events": unknown_count}

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
        person, score = match_embedding(embedding)
        display = "Unknown visitor"
        person_id = None
        if person is not None:
            person_id = person["id"]
            display = person["name"]
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
            # Embedding is returned so an unknown face can be named & saved from
            # the live view without re-capturing dedicated enrollment samples.
            "embedding": face["embedding"] if person is None else None,
        })
    return {"faces": output, "processed_at": now()}
