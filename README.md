# FaceIQ — Local Face Recognition Dashboard

FaceIQ is a local-first learning project with a FastAPI backend, React/Vite frontend, SQLite storage, webcam recognition, profile enrollment, repeat-visit tracking, notes, voice greetings, and a live dashboard.

## Important limitations
- Face recognition is probabilistic. The similarity score is not a guarantee of identity; use a conservative threshold and manually confirm enrollment.
- The expression indicator is a rough visual heuristic based on mouth landmarks, not a reliable reading of someone's actual mood or inner state.
- Enroll only people who have explicitly consented. This demo stores face embeddings and profile details locally. Do not use it for access control, employment, policing, or other high-stakes decisions.
- This project does not upload webcam frames to a cloud service. Frames are processed by the local backend.
- The OpenCV model files are downloaded by `backend/download_models.py` from the OpenCV Zoo repository.

## Requirements
- Python 3.10–3.12 recommended
- Node.js 20+
- Webcam
- Internet for initial model download and npm/pip installation

## Run it

### 1) Backend
Windows PowerShell:
```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python download_models.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

macOS/Linux:
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python download_models.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 2) Frontend (new terminal)
```bash
cd frontend
npm install
npm run dev
```
Open the local URL printed by Vite, usually http://localhost:5173.

## First use
1. Allow camera access.
2. Ask a person for consent before enrollment.
3. In **People**, click **Enroll person**, enter their name and confirm consent.
4. Capture 3–5 different angles/expressions in good lighting, then save.
5. Return to **Live**. The system will show a stored name when a face matches a saved profile; otherwise it displays **Unknown visitor**.
6. Use **People** to edit notes or delete a profile and its stored embedding.

## Troubleshooting
- If the camera is unavailable, close apps already using it and check browser permissions.
- If model downloads fail, rerun `python download_models.py`; verify internet access.
- OpenCV SFace/YuNet support varies by platform. Use the Python version recommended above.
- The app is intended for localhost use. Do not expose the API to a public network without authentication, TLS, rate limits, and a privacy/security review.
