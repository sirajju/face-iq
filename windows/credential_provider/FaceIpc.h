// FaceIpc.h — authenticated local IPC to the FaceIQ face agent.
//
// The provider asks a local agent (backend/face_agent.py) "is the Owner in view
// right now?". The channel is a named pipe with HMAC-SHA256 message auth, a
// fresh nonce per request (replay protection), a timestamp (freshness), and a
// hard timeout. The shared key lives in a local file readable only by SYSTEM +
// Administrators. A face result NEVER authenticates on its own — it only gates a
// tile whose password the user still types.
#pragma once

#include <windows.h>

enum FACE_RESULT
{
    FACE_OK = 0,       // Owner verified in view
    FACE_DENY = 1,     // No owner / not recognized
    FACE_NOCAMERA = 2, // Camera disconnected or not streaming -> cannot verify
    FACE_ERROR = 3,    // Agent unreachable / protocol / auth failure
};

// Pipe + key locations (keep in sync with backend/face_agent.py).
#define FACEIQ_PIPE_NAME  L"\\\\.\\pipe\\faceiq_verify"
#define FACEIQ_KEY_PATH   L"C:\\ProgramData\\FaceIQ\\ipc.key"
#define FACEIQ_IPC_TIMEOUT_MS 4000
#define FACEIQ_IPC_MAX_SKEW_S 10

// Query the agent. Returns one of FACE_RESULT. Never throws; failures map to
// FACE_ERROR / FACE_NOCAMERA so the caller fails safe (face factor not granted).
FACE_RESULT FaceIpcVerify();
