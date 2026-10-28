// common.h — shared definitions for the FaceIQ second-factor credential provider.
//
// SECURITY INTENT (read windows/README.md fully):
//   * This provider is a SECOND FACTOR. A positive face check does NOT sign you
//     in by itself; you still type your Windows PIN/password, which is what
//     authenticates to LSA. The provider stores NO secrets.
//   * It registers as an ADDITIONAL provider. Your normal password/PIN tile is
//     untouched, so you can always sign in the usual way. Rollback = delete the
//     registry keys (see README).
//   * RGB-webcam face recognition is NOT spoof-proof and is NOT Windows Hello.
//
// Structure follows Microsoft's public SampleCredentialProvider
// (https://github.com/microsoft/Windows-classic-samples, MIT). Verify the KERB
// packing helpers in helpers.cpp against that sample for your SDK version.
#pragma once

#include <windows.h>
#include <strsafe.h>
#include <shlwapi.h>   // SHStrDupW
#include <credentialprovider.h>

// The SDK has no "field state pair" struct; providers define their own.
struct FIELD_STATE_PAIR
{
    CREDENTIAL_PROVIDER_FIELD_STATE cpfs;
    CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE cpfis;
};

// {7F3B9E42-1C6A-4D2E-9B51-6F2A1E9D4C80}  — unique CLSID for THIS provider.
// Generate your own with guidgen / uuidgen before shipping; do not reuse.
DEFINE_GUID(CLSID_FaceIQProvider,
    0x7f3b9e42, 0x1c6a, 0x4d2e, 0x9b, 0x51, 0x6f, 0x2a, 0x1e, 0x9d, 0x4c, 0x80);

// Fields shown on the tile. Order matters; it maps to the descriptor table.
enum FACE_FIELD_ID
{
    FFI_TILEIMAGE   = 0,  // provider logo / avatar
    FFI_LABEL       = 1,  // "FaceIQ second factor"
    FFI_STATUS      = 2,  // live face-check status text
    FFI_PASSWORD    = 3,  // Windows password/PIN (the real authenticator)
    FFI_SUBMIT      = 4,  // submit button
    FFI_NUM_FIELDS  = 5
};

// Count of CREDENTIAL_PROVIDER_USAGE_SCENARIO values we support.
static const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR s_fieldDescriptors[] =
{
    { FFI_TILEIMAGE, CPFT_TILE_IMAGE,   const_cast<PWSTR>(L"Image") },
    { FFI_LABEL,     CPFT_LARGE_TEXT,   const_cast<PWSTR>(L"FaceIQ second factor") },
    { FFI_STATUS,    CPFT_SMALL_TEXT,   const_cast<PWSTR>(L"Face check: waiting…") },
    { FFI_PASSWORD,  CPFT_PASSWORD_TEXT,const_cast<PWSTR>(L"Windows password or PIN") },
    { FFI_SUBMIT,    CPFT_SUBMIT_BUTTON,const_cast<PWSTR>(L"Verify face + sign in") },
};

// Field state table — what is visible/interactive on the (unselected/selected) tile.
static const FIELD_STATE_PAIR s_fieldStatePairs[] =
{
    { CPFS_DISPLAY_IN_BOTH,            CPFIS_NONE    }, // FFI_TILEIMAGE
    { CPFS_DISPLAY_IN_BOTH,            CPFIS_NONE    }, // FFI_LABEL
    { CPFS_DISPLAY_IN_SELECTED_TILE,  CPFIS_NONE    }, // FFI_STATUS
    { CPFS_DISPLAY_IN_SELECTED_TILE,  CPFIS_FOCUSED }, // FFI_PASSWORD
    { CPFS_DISPLAY_IN_SELECTED_TILE,  CPFIS_NONE    }, // FFI_SUBMIT
};

extern HINSTANCE g_hInst;
void DllAddRef();
void DllRelease();
