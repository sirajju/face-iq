// FaceIpc.cpp — see FaceIpc.h.
#include "FaceIpc.h"
#include <bcrypt.h>
#include <strsafe.h>
#include <stdio.h>
#include <time.h>
#include <string>

#pragma comment(lib, "bcrypt.lib")

#ifndef NT_SUCCESS
#define NT_SUCCESS(s) (((NTSTATUS)(s)) >= 0)
#endif

static bool LoadKey(std::string& keyOut)
{
    HANDLE h = CreateFileW(FACEIQ_KEY_PATH, GENERIC_READ, FILE_SHARE_READ, nullptr,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    char buf[512]; DWORD read = 0;
    bool ok = ReadFile(h, buf, sizeof(buf), &read, nullptr) && read > 0;
    CloseHandle(h);
    if (!ok) return false;
    // Trim trailing whitespace/newlines.
    while (read && (buf[read - 1] == '\n' || buf[read - 1] == '\r' ||
                    buf[read - 1] == ' ' || buf[read - 1] == '\t'))
        read--;
    keyOut.assign(buf, read);
    return !keyOut.empty();
}

static bool HmacSha256Hex(const std::string& key, const std::string& data, std::string& hexOut)
{
    BCRYPT_ALG_HANDLE hAlg = nullptr; BCRYPT_HASH_HANDLE hHash = nullptr;
    bool ok = false; unsigned char mac[32] = {};
    if (!NT_SUCCESS(BCryptOpenAlgorithmProvider(&hAlg, BCRYPT_SHA256_ALGORITHM, nullptr,
                                                BCRYPT_ALG_HANDLE_HMAC_FLAG)))
        return false;
    if (NT_SUCCESS(BCryptCreateHash(hAlg, &hHash, nullptr, 0,
                                    (PUCHAR)key.data(), (ULONG)key.size(), 0)) &&
        NT_SUCCESS(BCryptHashData(hHash, (PUCHAR)data.data(), (ULONG)data.size(), 0)) &&
        NT_SUCCESS(BCryptFinishHash(hHash, mac, sizeof(mac), 0)))
    {
        char hex[65];
        for (int i = 0; i < 32; i++) StringCchPrintfA(hex + i * 2, 3, "%02x", mac[i]);
        hexOut.assign(hex, 64);
        ok = true;
    }
    if (hHash) BCryptDestroyHash(hHash);
    if (hAlg) BCryptCloseAlgorithmProvider(hAlg, 0);
    return ok;
}

static bool ConstantTimeEqual(const std::string& a, const std::string& b)
{
    if (a.size() != b.size()) return false;
    unsigned char diff = 0;
    for (size_t i = 0; i < a.size(); i++) diff |= (unsigned char)(a[i] ^ b[i]);
    return diff == 0;
}

static bool MakeNonceHex(std::string& nonceOut)
{
    unsigned char rnd[16] = {};
    if (!NT_SUCCESS(BCryptGenRandom(nullptr, rnd, sizeof(rnd),
                                    BCRYPT_USE_SYSTEM_PREFERRED_RNG)))
        return false;
    char hex[33];
    for (int i = 0; i < 16; i++) StringCchPrintfA(hex + i * 2, 3, "%02x", rnd[i]);
    nonceOut.assign(hex, 32);
    return true;
}

FACE_RESULT FaceIpcVerify()
{
    std::string key;
    if (!LoadKey(key)) return FACE_ERROR;

    std::string nonce;
    if (!MakeNonceHex(nonce)) return FACE_ERROR;

    // Connect to the pipe (wait briefly if busy).
    HANDLE hPipe = INVALID_HANDLE_VALUE;
    for (int attempt = 0; attempt < 2; attempt++)
    {
        hPipe = CreateFileW(FACEIQ_PIPE_NAME, GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                            OPEN_EXISTING, 0, nullptr);
        if (hPipe != INVALID_HANDLE_VALUE) break;
        if (GetLastError() != ERROR_PIPE_BUSY) return FACE_ERROR;
        if (!WaitNamedPipeW(FACEIQ_PIPE_NAME, FACEIQ_IPC_TIMEOUT_MS)) return FACE_ERROR;
    }
    if (hPipe == INVALID_HANDLE_VALUE) return FACE_ERROR;

    DWORD mode = PIPE_READMODE_BYTE;
    SetNamedPipeHandleState(hPipe, &mode, nullptr, nullptr);

    FACE_RESULT result = FACE_ERROR;
    std::string req = "VERIFY " + nonce + "\n";
    DWORD written = 0;
    if (WriteFile(hPipe, req.data(), (DWORD)req.size(), &written, nullptr))
    {
        char buf[256] = {}; DWORD read = 0;
        if (ReadFile(hPipe, buf, sizeof(buf) - 1, &read, nullptr) && read)
        {
            // Response: "<STATUS> <nonce> <unix_ts> <hmac_hex>"
            std::string resp(buf, read);
            char status[16] = {}, rnonce[64] = {}, hmacHex[80] = {};
            long long ts = 0;
            if (sscanf_s(resp.c_str(), "%15s %63s %lld %79s",
                         status, (unsigned)sizeof(status), rnonce, (unsigned)sizeof(rnonce),
                         &ts, hmacHex, (unsigned)sizeof(hmacHex)) == 4)
            {
                // Recompute HMAC over "<status> <nonce> <ts>".
                char signedPart[160];
                StringCchPrintfA(signedPart, sizeof(signedPart), "%s %s %lld", status, rnonce, ts);
                std::string expect;
                long long nowTs = (long long)time(nullptr);
                bool fresh = (nowTs - ts) >= -FACEIQ_IPC_MAX_SKEW_S &&
                             (nowTs - ts) <= FACEIQ_IPC_MAX_SKEW_S;
                bool nonceOk = (nonce == rnonce);
                if (HmacSha256Hex(key, signedPart, expect) &&
                    ConstantTimeEqual(expect, hmacHex) && fresh && nonceOk)
                {
                    if (_stricmp(status, "OK") == 0) result = FACE_OK;
                    else if (_stricmp(status, "NOCAM") == 0) result = FACE_NOCAMERA;
                    else result = FACE_DENY;
                }
                // else: auth/replay/freshness failure -> FACE_ERROR (fail safe)
            }
        }
    }
    CloseHandle(hPipe);
    return result;
}
