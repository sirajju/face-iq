import React, { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  AudioLines,
  Camera,
  Check,
  ChevronRight,
  CircleHelp,
  Clock3,
  Fingerprint,
  LayoutDashboard,
  Mic,
  Plus,
  ScanFace,
  Search,
  Settings2,
  ShieldCheck,
  Trash2,
  Users,
  Video,
  VideoOff,
  X,
} from "lucide-react";
import "./style.css";

const API = "http://127.0.0.1:8000/api";
const fmt = (v) => (v ? new Date(v).toLocaleString() : "Not seen yet");
async function request(path, options = {}) {
  const res = await fetch(API + path, options);
  const data = await res
    .json()
    .catch(() => ({ detail: "Unexpected server response" }));
  if (!res.ok) throw new Error(data.detail || "Request failed");
  return data;
}
function App() {
  const [page, setPage] = useState("Live");
  const [people, setPeople] = useState([]);
  const [events, setEvents] = useState([]);
  const [stats, setStats] = useState({
    people: 0,
    known_visits: 0,
    events: 0,
    unknown_events: 0,
  });
  const [health, setHealth] = useState({
    ok: false,
    vision_ready: false,
    message: "Checking API…",
  });
  const [cameraOn, setCameraOn] = useState(false);
  const [faces, setFaces] = useState([]);
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [modal, setModal] = useState(false);
  const [selected, setSelected] = useState(null);
  const videoRef = useRef(null),
    canvasRef = useRef(null),
    streamRef = useRef(null),
    timerRef = useRef(null),
    busyRef = useRef(false);
  const unknownBufRef = useRef([]);
  const greetedRef = useRef({}); // person_id -> last alert time (ms), debounce
  const audioRef = useRef(null); // lazily-created AudioContext for the chime
  const [form, setForm] = useState({
    name: "",
    notes: "",
    interests: "",
    consent: false,
  });
  const [samples, setSamples] = useState([]);
  const [saving, setSaving] = useState(false);
  const [quickTarget, setQuickTarget] = useState(null);
  const [quickName, setQuickName] = useState("");
  const [quickSaving, setQuickSaving] = useState(false);
  // Recognition alerts — fire ONLY for registered/recognized people. Persisted.
  const [alerts, setAlerts] = useState(() => {
    try {
      return {
        chime: true,
        voice: true,
        desktop: false,
        ...JSON.parse(localStorage.getItem("faceiq_alerts") || "{}"),
      };
    } catch {
      return { chime: true, voice: true, desktop: false };
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem("faceiq_alerts", JSON.stringify(alerts));
    } catch {}
  }, [alerts]);

  const refresh = useCallback(async () => {
    try {
      const [p, e, s, h] = await Promise.all([
        request("/people"),
        request("/events?limit=100"),
        request("/stats"),
        request("/health"),
      ]);
      setPeople(p);
      setEvents(e);
      setStats(s);
      setHealth(h);
    } catch (e) {
      setHealth({ ok: false, vision_ready: false, message: e.message });
    }
  }, []);
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);
  const stopCamera = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
    if (streamRef.current)
      streamRef.current.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOn(false);
    setFaces([]);
  }, []);
  const startCamera = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: "user",
          width: { ideal: 960 },
          height: { ideal: 540 },
        },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraOn(true);
      setNotice("");
      timerRef.current = setInterval(captureFrame, 1200);
    } catch (e) {
      setNotice(
        "Camera unavailable. Allow camera access in your browser and close other camera apps.",
      );
    }
  };
  const captureFrame = async () => {
    if (
      busyRef.current ||
      !videoRef.current ||
      !videoRef.current.videoWidth ||
      !canvasRef.current
    )
      return;
    busyRef.current = true;
    try {
      const v = videoRef.current,
        c = canvasRef.current;
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
      const blob = await new Promise((resolve) =>
        c.toBlob(resolve, "image/jpeg", 0.78),
      );
      if (!blob) return;
      const fd = new FormData();
      fd.append("frame", blob, "frame.jpg");
      const data = await request("/recognize", { method: "POST", body: fd });
      setFaces(data.faces);
      // Keep a short rolling buffer of unknown-face embeddings so naming a
      // person on the spot can use several samples, not just one frame.
      const fresh = data.faces
        .filter((f) => !f.known && Array.isArray(f.embedding))
        .map((f) => f.embedding);
      if (fresh.length)
        unknownBufRef.current = [...unknownBufRef.current, ...fresh].slice(-10);
      if (data.faces.some((f) => !f.known))
        setNotice(
          "Unknown visitor detected — name them below to recognize them next time.",
        );
      else setNotice("");
      // Sound / voice / desktop alerts fire only for recognized, registered people.
      data.faces.forEach((f) => f.known && alertRecognized(f));
      if (data.faces.some((f) => f.known)) refresh();
    } catch (e) {
      setNotice(e.message);
    } finally {
      busyRef.current = false;
    }
  };
  useEffect(() => () => stopCamera(), [stopCamera]);

  const openEnroll = () => {
    setForm({ name: "", notes: "", interests: "", consent: false });
    setSamples([]);
    setModal(true);
  };
  const captureSample = async () => {
    if (!videoRef.current || !videoRef.current.videoWidth) {
      setNotice("Start the camera on the Live page before capturing samples.");
      return;
    }
    try {
      const v = videoRef.current,
        c = canvasRef.current;
      c.width = v.videoWidth;
      c.height = v.videoHeight;
      c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
      const blob = await new Promise((resolve) =>
        c.toBlob(resolve, "image/jpeg", 0.9),
      );
      const fd = new FormData();
      fd.append("frame", blob, "sample.jpg");
      const data = await request("/enrollment-sample", {
        method: "POST",
        body: fd,
      });
      if (!data.faces.length) {
        setNotice(
          "No face detected. Center your face in good lighting and try again.",
        );
        return;
      }
      setSamples((old) => [...old, data.faces[0].embedding].slice(0, 5));
      setNotice("Sample captured.");
    } catch (e) {
      setNotice(e.message);
    }
  };
  const savePerson = async () => {
    if (!form.name.trim() || !form.consent) {
      setNotice("Enter a name and confirm consent.");
      return;
    }
    if (samples.length < 3) {
      setNotice("Capture at least 3 samples.");
      return;
    }
    setSaving(true);
    try {
      await request("/people", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...form, embeddings: samples }),
      });
      setModal(false);
      setNotice("Profile enrolled successfully.");
      refresh();
    } catch (e) {
      setNotice(e.message);
    } finally {
      setSaving(false);
    }
  };
  const openQuick = (face) => {
    setQuickTarget(face);
    setQuickName("");
  };
  const saveQuick = async () => {
    if (!quickTarget) return;
    const name = quickName.trim();
    if (!name) {
      setNotice("Enter a name for this person.");
      return;
    }
    const target = quickTarget.embedding;
    if (!Array.isArray(target)) {
      setNotice(
        "No face sample available — keep the person in view and try again.",
      );
      return;
    }
    // Gather buffered unknown samples that look like the same person (cosine
    // similarity on already-normalised embeddings = dot product).
    const dot = (a, b) => a.reduce((s, v, i) => s + v * b[i], 0);
    const similar = unknownBufRef.current.filter(
      (e) => e.length === target.length && dot(e, target) >= 0.5,
    );
    const embeddings = [target, ...similar].slice(0, 5);
    setQuickSaving(true);
    try {
      await request("/people/quick", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, embeddings }),
      });
      unknownBufRef.current = [];
      setQuickTarget(null);
      setNotice(`Saved "${name}". They'll be recognized next time.`);
      refresh();
    } catch (e) {
      setNotice(e.message);
    } finally {
      setQuickSaving(false);
    }
  };
  const deletePerson = async (p) => {
    if (
      !confirm(
        `Delete ${p.name}'s profile and face embedding? This cannot be undone.`,
      )
    )
      return;
    try {
      await request(`/people/${p.id}`, { method: "DELETE" });
      setSelected(null);
      setNotice("Profile deleted.");
      refresh();
    } catch (e) {
      setNotice(e.message);
    }
  };
  const updateProfile = async () => {
    if (!selected) return;
    try {
      await request(`/people/${selected.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          notes: selected.notes,
          interests: selected.interests,
          greeting: selected.greeting || "",
        }),
      });
      setNotice("Profile updated.");
      refresh();
    } catch (e) {
      setNotice(e.message);
    }
  };
  const speak = (text) => {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      window.speechSynthesis.speak(u);
    }
  };
  // Short two-note chime via Web Audio — no asset files needed.
  const playChime = () => {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      if (!audioRef.current) audioRef.current = new Ctx();
      const ctx = audioRef.current;
      if (ctx.state === "suspended") ctx.resume();
      [
        [880, 0],
        [1320, 0.12],
      ].forEach(([freq, at]) => {
        const osc = ctx.createOscillator(),
          gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        const t = ctx.currentTime + at;
        gain.gain.setValueAtTime(0.0001, t);
        gain.gain.exponentialRampToValueAtTime(0.25, t + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
        osc.connect(gain).connect(ctx.destination);
        osc.start(t);
        osc.stop(t + 0.2);
      });
    } catch {}
  };
  const notify = (title, body) => {
    try {
      if ("Notification" in window && Notification.permission === "granted")
        new Notification(title, { body, silent: true });
    } catch {}
  };
  // Fire alerts for a recognized person, debounced to once per 60s per person.
  const alertRecognized = (face) => {
    if (!face.known || face.person_id == null) return;
    const now = Date.now();
    const last = greetedRef.current[face.person_id] || 0;
    if (now - last < 60000) return;
    greetedRef.current[face.person_id] = now;
    if (alerts.chime) playChime();
    if (alerts.voice) speak(face.greeting || `Welcome back, ${face.name}`);
    if (alerts.desktop)
      notify("FaceIQ — recognized", `${face.name} is in view.`);
  };
  // Map a detection box (raw, un-mirrored frame coords) onto the on-screen
  // video, accounting for object-fit:cover cropping and the scaleX(-1) mirror.
  const boxStyle = (box) => {
    const v = videoRef.current;
    if (!v || !v.videoWidth || !v.clientWidth) return { display: "none" };
    const cw = v.clientWidth,
      ch = v.clientHeight,
      vw = v.videoWidth,
      vh = v.videoHeight;
    const scale = Math.max(cw / vw, ch / vh); // object-fit: cover
    const offX = (cw - vw * scale) / 2,
      offY = (ch - vh * scale) / 2;
    const width = box.width * scale,
      height = box.height * scale;
    const left = cw - (offX + box.x * scale + width); // mirror to match scaleX(-1)
    const top = offY + box.y * scale;
    return {
      left: `${left}px`,
      top: `${top}px`,
      width: `${width}px`,
      height: `${height}px`,
    };
  };
  const filtered = people.filter((p) =>
    (p.name + " " + p.notes + " " + p.interests)
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  const nav = [
    ["Live", Video],
    ["People", Users],
    ["Activity", Activity],
    ["Settings", Settings2],
  ];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <ScanFace size={22} />
          </div>
          <div>
            <b>faceiq</b>
            <span>PERSONAL INTELLIGENCE</span>
          </div>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav>
          {nav.map(([n, Icon]) => (
            <button
              key={n}
              className={`nav-item ${page === n ? "active" : ""}`}
              onClick={() => setPage(n)}
            >
              <Icon size={18} />
              <span>{n}</span>
              {n === "People" && <small>{people.length}</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-card">
            <ShieldCheck size={18} />
            <div>
              <b>Local-first privacy</b>
              <p>Profiles stay on this device.</p>
            </div>
          </div>
          <div className="user-chip">
            <div className="avatar">F</div>
            <div>
              <b>FaceIQ workspace</b>
              <span>Personal instance</span>
            </div>
            <Settings2 size={16} />
          </div>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">PERSONAL RECOGNITION SYSTEM</div>
            <h1>
              {page === "Live"
                ? "Live recognition"
                : page === "People"
                  ? "People & profiles"
                  : page === "Activity"
                    ? "Recognition activity"
                    : "Privacy & settings"}
            </h1>
          </div>
          <div className="top-actions">
            <span
              className={`status-pill ${health.vision_ready ? "good" : "warn"}`}
            >
              <i />
              {health.vision_ready
                ? "Vision system ready"
                : "Vision system offline"}
            </span>
            <button
              className="icon-button"
              title="Refresh data"
              onClick={refresh}
            >
              <Activity size={17} />
            </button>
            <button className="primary" onClick={openEnroll}>
              <Plus size={17} /> Enroll person
            </button>
          </div>
        </header>
        {notice && (
          <div className="notice">
            <AlertTriangle size={16} />
            <span>{notice}</span>
            <button onClick={() => setNotice("")}>
              <X size={15} />
            </button>
          </div>
        )}
        {!health.vision_ready && (
          <div className="setup-banner">
            <AlertTriangle size={19} />
            <div>
              <b>Recognition engine isn't ready yet</b>
              <p>
                {health.message ||
                  "Start the API and download the model files."}
              </p>
            </div>
          </div>
        )}
        {page === "Live" && (
          <div className="content live-grid">
            <section className="panel camera-panel">
              <div className="panel-head">
                <div>
                  <h2>Live camera</h2>
                  <p>On-device face detection & matching</p>
                </div>
                <span className={`live-tag ${cameraOn ? "is-live" : ""}`}>
                  <i />
                  {cameraOn ? "LIVE" : "STANDBY"}
                </span>
              </div>
              <div className="camera-stage">
                <video
                  ref={videoRef}
                  muted
                  playsInline
                  className={cameraOn ? "camera-video active" : "camera-video"}
                />
                <canvas ref={canvasRef} className="hidden-canvas" />
                {!cameraOn && (
                  <div className="camera-placeholder">
                    <div className="camera-icon">
                      <Camera size={29} />
                    </div>
                    <b>Camera is standing by</b>
                    <span>Start your camera to begin local recognition.</span>
                  </div>
                )}
                {cameraOn &&
                  faces.map((f, i) => (
                    <div
                      key={i}
                      className={`face-box ${f.known ? "known" : "unknown"}`}
                      style={boxStyle(f.box)}
                    >
                      <span>
                        {f.name}
                        {f.facing && f.facing !== "Looking at camera"
                          ? ` · ${f.facing}`
                          : ""}
                      </span>
                    </div>
                  ))}
                <div className="camera-overlay">
                  <span>
                    <i /> LOCAL PROCESSING
                  </span>
                  <span>NO CLOUD UPLOAD</span>
                </div>
              </div>
              <div className="camera-footer">
                <div className="camera-meta">
                  <span>
                    <span className={`dot ${cameraOn ? "green" : ""}`} />
                    {cameraOn ? "Camera active" : "Camera stopped"}
                  </span>
                  <span>
                    <Fingerprint size={14} />
                    {faces.length} face{faces.length === 1 ? "" : "s"} detected
                  </span>
                </div>
                <div className="button-row">
                  {cameraOn ? (
                    <button className="secondary" onClick={stopCamera}>
                      <VideoOff size={16} /> Stop camera
                    </button>
                  ) : (
                    <button className="primary" onClick={startCamera}>
                      <Video size={16} /> Start camera
                    </button>
                  )}
                </div>
              </div>
            </section>
            <section className="right-stack">
              <div className="panel detected-panel">
                <div className="panel-head">
                  <div>
                    <h2>In view</h2>
                    <p>Current recognition results</p>
                  </div>
                  <span className="count-badge">{faces.length}</span>
                </div>
                {faces.length === 0 ? (
                  <div className="empty-state">
                    <div className="empty-icon">
                      <ScanFace size={23} />
                    </div>
                    <b>No faces in view</b>
                    <span>Position a face in front of the camera.</span>
                  </div>
                ) : (
                  faces.map((f, i) => (
                    <div className="person-result" key={i}>
                      <div
                        className={`result-avatar ${f.known ? "" : "unknown-avatar"}`}
                      >
                        {f.known ? f.name.slice(0, 1).toUpperCase() : "?"}
                      </div>
                      <div className="result-info">
                        <b>{f.name}</b>
                        <span>
                          {f.known
                            ? "Previously enrolled"
                            : f.recognizable
                              ? "Not in your profiles"
                              : "Face not clear enough to identify"}
                        </span>
                        <div className="result-tags">
                          <span>{f.expression}</span>
                          <span
                            className={
                              f.facing === "Looking at camera"
                                ? "facing-tag facing-on"
                                : "facing-tag facing-off"
                            }
                          >
                            {f.facing}
                          </span>
                          {f.known && (
                            <span>
                              {Math.round(f.similarity * 100)}% similarity
                            </span>
                          )}
                        </div>
                      </div>
                      {f.known ? (
                        <button
                          className="round-button"
                          title="Voice greeting"
                          onClick={() =>
                            speak(f.greeting || `Welcome back, ${f.name}`)
                          }
                        >
                          <AudioLines size={16} />
                        </button>
                      ) : (
                        <button
                          className="secondary small-button"
                          title={
                            f.enroll_ready
                              ? "Name & save this person"
                              : "Ask them to look at the camera before saving"
                          }
                          disabled={
                            !Array.isArray(f.embedding) || !f.enroll_ready
                          }
                          onClick={() => openQuick(f)}
                        >
                          <Plus size={14} /> Name
                        </button>
                      )}
                    </div>
                  ))
                )}
                <p className="muted-note">
                  <CircleHelp size={14} /> Similarity is a model score, not
                  proof of identity. Expression is a rough visual estimate only.
                </p>
              </div>
              <div className="panel quick-stats">
                <div className="panel-head">
                  <div>
                    <h2>Workspace overview</h2>
                    <p>Stored locally in SQLite</p>
                  </div>
                  <LayoutDashboard size={18} className="subtle-icon" />
                </div>
                <div className="mini-stats">
                  <div>
                    <span>Known people</span>
                    <b>{stats.people}</b>
                  </div>
                  <div>
                    <span>Known visits</span>
                    <b>{stats.known_visits}</b>
                  </div>
                  <div>
                    <span>Unknown events</span>
                    <b>{stats.unknown_events}</b>
                  </div>
                </div>
                <button
                  className="text-button"
                  onClick={() => setPage("Activity")}
                >
                  View activity log <ChevronRight size={15} />
                </button>
              </div>
            </section>
            <section className="panel recent-panel">
              <div className="panel-head">
                <div>
                  <h2>Recently recognized</h2>
                  <p>Your latest saved recognition events</p>
                </div>
                <button
                  className="text-button"
                  onClick={() => setPage("Activity")}
                >
                  View all <ChevronRight size={15} />
                </button>
              </div>
              {events.slice(0, 5).length === 0 ? (
                <div className="empty-line">
                  No saved events yet. Start the camera to begin.
                </div>
              ) : (
                <div className="event-list">
                  {events.slice(0, 5).map((e) => (
                    <div className="event-row" key={e.id}>
                      <div
                        className={`event-icon ${e.person_id ? "" : "event-unknown"}`}
                      >
                        {e.person_id ? (
                          <Check size={16} />
                        ) : (
                          <AlertTriangle size={16} />
                        )}
                      </div>
                      <div className="event-main">
                        <b>{e.display_name}</b>
                        <span>
                          {e.expression} ·{" "}
                          {e.person_id
                            ? "Recognized profile"
                            : "Unknown visitor"}
                        </span>
                      </div>
                      <time>{fmt(e.seen_at)}</time>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}
        {page === "People" && (
          <div className="content">
            <div className="toolbar">
              <div className="searchbox">
                <Search size={17} />
                <input
                  placeholder="Search people, notes, interests…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
              <span className="muted">
                {filtered.length} profile{filtered.length === 1 ? "" : "s"}
              </span>
            </div>
            {filtered.length === 0 ? (
              <div className="panel empty-large">
                <Users size={30} />
                <h2>No profiles yet</h2>
                <p>
                  Enroll a consenting person to recognize them when they return.
                </p>
                <button className="primary" onClick={openEnroll}>
                  <Plus size={16} /> Enroll first person
                </button>
              </div>
            ) : (
              <div className="people-grid">
                {filtered.map((p) => (
                  <div className="panel profile-card" key={p.id}>
                    <div className="profile-card-top">
                      <div className="profile-avatar">
                        {p.name.slice(0, 1).toUpperCase()}
                      </div>
                      <span className="consent-tag">
                        <ShieldCheck size={13} /> Consent recorded
                      </span>
                    </div>
                    <h3>{p.name}</h3>
                    <p className="profile-interests">
                      {p.interests || "No interests added"}
                    </p>
                    <div className="profile-stats">
                      <div>
                        <span>Visits</span>
                        <b>{p.visit_count}</b>
                      </div>
                      <div>
                        <span>First seen</span>
                        <b>
                          {p.first_seen
                            ? new Date(p.first_seen).toLocaleDateString()
                            : "—"}
                        </b>
                      </div>
                      <div>
                        <span>Last seen</span>
                        <b>
                          {p.last_seen
                            ? new Date(p.last_seen).toLocaleDateString()
                            : "—"}
                        </b>
                      </div>
                    </div>
                    <p className="profile-notes">
                      {p.notes || "No personal notes yet."}
                    </p>
                    <div className="profile-actions">
                      <button
                        className="secondary"
                        onClick={() => setSelected({ ...p })}
                      >
                        Edit profile
                      </button>
                      <button
                        className="danger-icon"
                        title="Delete profile"
                        onClick={() => deletePerson(p)}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {page === "Activity" && (
          <div className="content">
            <div className="panel activity-panel">
              <div className="panel-head">
                <div>
                  <h2>Recognition history</h2>
                  <p>Recent events logged on this device</p>
                </div>
                <span className="count-badge">{events.length}</span>
              </div>
              {events.length === 0 ? (
                <div className="empty-large">
                  <Clock3 size={30} />
                  <h2>No activity yet</h2>
                  <p>Recognition events will appear here.</p>
                </div>
              ) : (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>PERSON</th>
                        <th>RESULT</th>
                        <th>EXPRESSION ESTIMATE</th>
                        <th>FACING</th>
                        <th>SIMILARITY</th>
                        <th>TIME</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map((e) => (
                        <tr key={e.id}>
                          <td>
                            <b>{e.display_name}</b>
                          </td>
                          <td>
                            <span
                              className={`table-status ${e.person_id ? "known-status" : "unknown-status"}`}
                            >
                              {e.person_id ? "Recognized" : "Unknown"}
                            </span>
                          </td>
                          <td>{e.expression}</td>
                          <td>{e.facing || "—"}</td>
                          <td>
                            {e.confidence == null
                              ? "—"
                              : `${Math.round(e.confidence * 100)}%`}
                          </td>
                          <td>{fmt(e.seen_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
        {page === "Settings" && (
          <div className="content settings-grid">
            <div className="panel settings-card">
              <div className="settings-icon">
                <ShieldCheck />
              </div>
              <h2>Privacy by design</h2>
              <p>
                Frames are sent only to your local FastAPI service at 127.0.0.1.
                Face embeddings, profile notes, and event logs are stored in a
                local SQLite database.
              </p>
              <ul>
                <li>Camera starts only after you click Start camera.</li>
                <li>Stop camera to end the stream and processing.</li>
                <li>Profiles require an explicit consent checkbox.</li>
                <li>
                  Delete a profile to remove its embedding and profile details.
                </li>
              </ul>
            </div>
            <div className="panel settings-card">
              <div className="settings-icon">
                <Fingerprint />
              </div>
              <h2>Recognition settings</h2>
              <p>
                The current matching threshold is configured in{" "}
                <code>backend/app/main.py</code> as{" "}
                <code>MATCH_THRESHOLD = 0.363</code>.
              </p>
              <p>
                Test with consented sample data before changing it. A lower
                threshold may increase false matches; a higher threshold may
                miss genuine matches.
              </p>
              <div className="settings-callout">
                <AlertTriangle size={17} />
                <span>
                  Do not use this prototype as a security gate or for
                  consequential decisions.
                </span>
              </div>
            </div>
            <div className="panel settings-card">
              <div className="settings-icon">
                <Mic />
              </div>
              <h2>Recognition alerts</h2>
              <p>
                Alerts fire only when a <b>registered</b> person is recognized in
                the camera — never for unknown visitors. Debounced to once per
                minute per person.
              </p>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={alerts.chime}
                  onChange={(e) =>
                    setAlerts({ ...alerts, chime: e.target.checked })
                  }
                />
                <span>Play a chime sound</span>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={alerts.voice}
                  onChange={(e) =>
                    setAlerts({ ...alerts, voice: e.target.checked })
                  }
                />
                <span>Speak a greeting (uses each person's custom message)</span>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={alerts.desktop}
                  onChange={async (e) => {
                    const on = e.target.checked;
                    if (on && "Notification" in window) {
                      const perm = await Notification.requestPermission();
                      if (perm !== "granted") {
                        setNotice(
                          "Desktop notifications were blocked in the browser.",
                        );
                        return;
                      }
                    }
                    setAlerts({ ...alerts, desktop: on });
                  }}
                />
                <span>Send a desktop notification</span>
              </label>
              <button
                className="secondary"
                onClick={() => {
                  if (alerts.chime) playChime();
                  speak("Welcome back, friend");
                  if (alerts.desktop)
                    notify("FaceIQ — recognized", "Test notification.");
                }}
              >
                <AudioLines size={16} /> Test alert
              </button>
            </div>
          </div>
        )}
      </main>
      {modal && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-head">
              <div>
                <div className="eyebrow">NEW PROFILE</div>
                <h2>Enroll a person</h2>
                <p>Ask permission before collecting face samples.</p>
              </div>
              <button className="icon-button" onClick={() => setModal(false)}>
                <X size={18} />
              </button>
            </div>
            <label>
              Full name
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Alex Morgan"
              />
            </label>
            <label>
              Interests & preferences
              <input
                value={form.interests}
                onChange={(e) =>
                  setForm({ ...form, interests: e.target.value })
                }
                placeholder="Coffee, photography, prefers short greetings"
              />
            </label>
            <label>
              Personal notes
              <textarea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="Details shared by this person…"
                rows={3}
              />
            </label>
            <div className="sample-box">
              <div>
                <b>Face samples</b>
                <span>Capture 3–5 samples using the active webcam.</span>
              </div>
              <div className="sample-count">{samples.length}/5</div>
              <button
                className="secondary"
                disabled={!cameraOn || samples.length >= 5}
                onClick={captureSample}
              >
                <Camera size={15} /> Capture sample
              </button>
              <p className="small-hint">
                Start the camera on the Live page first. Samples need a clear,
                centered face.
              </p>
            </div>
            <label className="consent-check">
              <input
                type="checkbox"
                checked={form.consent}
                onChange={(e) =>
                  setForm({ ...form, consent: e.target.checked })
                }
              />
              <span>
                I have this person's consent to create and store a
                face-recognition profile on this device.
              </span>
            </label>
            <div className="modal-actions">
              <button className="secondary" onClick={() => setModal(false)}>
                Cancel
              </button>
              <button
                className="primary"
                disabled={saving}
                onClick={savePerson}
              >
                {saving ? "Saving…" : "Save profile"}
              </button>
            </div>
          </div>
        </div>
      )}
      {selected && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-head">
              <div>
                <div className="eyebrow">PROFILE DETAILS</div>
                <h2>{selected.name}</h2>
                <p>Update notes and preferences stored locally.</p>
              </div>
              <button className="icon-button" onClick={() => setSelected(null)}>
                <X size={18} />
              </button>
            </div>
            <label>
              Interests & preferences
              <input
                value={selected.interests}
                onChange={(e) =>
                  setSelected({ ...selected, interests: e.target.value })
                }
              />
            </label>
            <label>
              Custom spoken greeting
              <input
                value={selected.greeting || ""}
                placeholder={`Default: "Welcome back, ${selected.name}"`}
                onChange={(e) =>
                  setSelected({ ...selected, greeting: e.target.value })
                }
              />
            </label>
            <label>
              Personal notes
              <textarea
                rows={5}
                value={selected.notes}
                onChange={(e) =>
                  setSelected({ ...selected, notes: e.target.value })
                }
              />
            </label>
            <div className="profile-detail">
              <span>First seen</span>
              <b>{fmt(selected.first_seen)}</b>
              <span>Last seen</span>
              <b>{fmt(selected.last_seen)}</b>
              <span>Recognized visits</span>
              <b>{selected.visit_count}</b>
            </div>
            <div className="modal-actions">
              <button
                className="danger-button"
                onClick={() => deletePerson(selected)}
              >
                <Trash2 size={15} /> Delete profile
              </button>
              <button className="primary" onClick={updateProfile}>
                Save changes
              </button>
            </div>
          </div>
        </div>
      )}
      {quickTarget && (
        <div className="modal-backdrop">
          <div className="modal quick-modal">
            <div className="modal-head">
              <div>
                <div className="eyebrow">NAME THIS PERSON</div>
                <h2>Save an unknown visitor</h2>
                <p>
                  Give this face a name to recognize them automatically next
                  time.
                </p>
              </div>
              <button
                className="icon-button"
                onClick={() => setQuickTarget(null)}
              >
                <X size={18} />
              </button>
            </div>
            <label>
              Name
              <input
                autoFocus
                value={quickName}
                onChange={(e) => setQuickName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveQuick();
                }}
                placeholder="e.g. Delivery driver, Sam, Neighbour"
              />
            </label>
            <p className="small-hint">
              <CircleHelp size={14} /> Uses the face sample(s) currently in
              view. Only save people who consented to being recognized on this
              device.
            </p>
            <div className="modal-actions">
              <button
                className="secondary"
                onClick={() => setQuickTarget(null)}
              >
                Cancel
              </button>
              <button
                className="primary"
                disabled={quickSaving}
                onClick={saveQuick}
              >
                {quickSaving ? "Saving…" : "Save & recognize"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
