// CFaceCredential.cpp — see CFaceCredential.h.
#include "CFaceCredential.h"
#include "helpers.h"
#include "FaceIpc.h"
#include <ntsecapi.h>
#include <propkey.h>
#include <strsafe.h>

CFaceCredential::CFaceCredential() { DllAddRef(); }

CFaceCredential::~CFaceCredential()
{
    if (_rgFieldStrings[FFI_PASSWORD])
    {
        // Wipe the typed password from memory before freeing.
        size_t len = lstrlenW(_rgFieldStrings[FFI_PASSWORD]);
        SecureZeroMemory(_rgFieldStrings[FFI_PASSWORD], len * sizeof(WCHAR));
    }
    for (int i = 0; i < FFI_NUM_FIELDS; i++)
        CoTaskMemFree(_rgFieldStrings[i]);
    for (int i = 0; i < FFI_NUM_FIELDS; i++)
        CoTaskMemFree(_rgFieldDescriptors[i].pszLabel);
    CoTaskMemFree(_pszUserSid);
    CoTaskMemFree(_pszQualifiedUserName);
    DllRelease();
}

IFACEMETHODIMP_(ULONG) CFaceCredential::Release()
{
    long cRef = --_cRef;
    if (!cRef) delete this;
    return cRef;
}

IFACEMETHODIMP CFaceCredential::QueryInterface(REFIID riid, void** ppv)
{
    if (riid == IID_IUnknown ||
        riid == IID_ICredentialProviderCredential ||
        riid == IID_ICredentialProviderCredential2)
    {
        *ppv = static_cast<ICredentialProviderCredential2*>(this);
        AddRef();
        return S_OK;
    }
    *ppv = nullptr;
    return E_NOINTERFACE;
}

HRESULT CFaceCredential::Initialize(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
                                    const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* rgcpfd,
                                    const FIELD_STATE_PAIR* rgfsp,
                                    ICredentialProviderUser* pcpUser)
{
    _cpus = cpus;
    HRESULT hr = S_OK;
    for (int i = 0; i < FFI_NUM_FIELDS && SUCCEEDED(hr); i++)
    {
        _rgFieldStatePairs[i] = rgfsp[i];
        hr = FieldDescriptorCopy(rgcpfd[i], &_rgFieldDescriptors[i]);
    }
    if (SUCCEEDED(hr)) hr = SHStrDupW(L"", &_rgFieldStrings[FFI_LABEL]);
    if (SUCCEEDED(hr)) hr = SHStrDupW(L"Face check: not run", &_rgFieldStrings[FFI_STATUS]);
    if (SUCCEEDED(hr)) hr = SHStrDupW(L"", &_rgFieldStrings[FFI_PASSWORD]);
    if (SUCCEEDED(hr)) hr = SHStrDupW(L"Verify face + sign in", &_rgFieldStrings[FFI_SUBMIT]);
    if (SUCCEEDED(hr)) hr = SHStrDupW(L"FaceIQ (second factor)", &_rgFieldStrings[FFI_TILEIMAGE]);

    if (SUCCEEDED(hr) && pcpUser)
    {
        pcpUser->GetStringValue(PKEY_Identity_QualifiedUserName, &_pszQualifiedUserName);
        pcpUser->GetSid(&_pszUserSid);
    }
    return hr;
}

void CFaceCredential::SetStatus(PCWSTR text)
{
    CoTaskMemFree(_rgFieldStrings[FFI_STATUS]);
    SHStrDupW(text, &_rgFieldStrings[FFI_STATUS]);
    if (_pcpce)
        _pcpce->SetFieldString(this, FFI_STATUS, _rgFieldStrings[FFI_STATUS]);
}

IFACEMETHODIMP CFaceCredential::Advise(ICredentialProviderCredentialEvents* pcpce)
{
    if (_pcpce) _pcpce->Release();
    _pcpce = pcpce;
    if (_pcpce) _pcpce->AddRef();
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::UnAdvise()
{
    if (_pcpce) { _pcpce->Release(); _pcpce = nullptr; }
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::SetSelected(BOOL* pbAutoLogon)
{
    // IMPORTANT: never auto-logon. The user must type their password.
    *pbAutoLogon = FALSE;
    SetStatus(L"Face check runs when you click Verify.");
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::SetDeselected()
{
    if (_rgFieldStrings[FFI_PASSWORD])
    {
        size_t len = lstrlenW(_rgFieldStrings[FFI_PASSWORD]);
        SecureZeroMemory(_rgFieldStrings[FFI_PASSWORD], len * sizeof(WCHAR));
        CoTaskMemFree(_rgFieldStrings[FFI_PASSWORD]);
        SHStrDupW(L"", &_rgFieldStrings[FFI_PASSWORD]);
        if (_pcpce)
            _pcpce->SetFieldString(this, FFI_PASSWORD, _rgFieldStrings[FFI_PASSWORD]);
    }
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::GetFieldState(DWORD dwFieldID,
    CREDENTIAL_PROVIDER_FIELD_STATE* pcpfs,
    CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* pcpfis)
{
    if (dwFieldID >= FFI_NUM_FIELDS) return E_INVALIDARG;
    *pcpfs = _rgFieldStatePairs[dwFieldID].cpfs;
    *pcpfis = _rgFieldStatePairs[dwFieldID].cpfis;
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::GetStringValue(DWORD dwFieldID, PWSTR* ppwsz)
{
    if (dwFieldID >= FFI_NUM_FIELDS) return E_INVALIDARG;
    return SHStrDupW(_rgFieldStrings[dwFieldID] ? _rgFieldStrings[dwFieldID] : L"", ppwsz);
}

IFACEMETHODIMP CFaceCredential::GetBitmapValue(DWORD dwFieldID, HBITMAP* phbmp)
{
    if (dwFieldID != FFI_TILEIMAGE) return E_INVALIDARG;
    *phbmp = nullptr; // Use the default tile image; ship your own .bmp if desired.
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::GetSubmitButtonValue(DWORD dwFieldID, DWORD* pdwAdjacentTo)
{
    if (dwFieldID != FFI_SUBMIT) return E_INVALIDARG;
    *pdwAdjacentTo = FFI_PASSWORD;
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::SetStringValue(DWORD dwFieldID, PCWSTR pwz)
{
    if (dwFieldID != FFI_PASSWORD) return E_INVALIDARG;
    CoTaskMemFree(_rgFieldStrings[FFI_PASSWORD]);
    return SHStrDupW(pwz, &_rgFieldStrings[FFI_PASSWORD]);
}

IFACEMETHODIMP CFaceCredential::GetSerialization(
    CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* pcpgsr,
    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs,
    PWSTR* ppwszOptionalStatusText,
    CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon)
{
    *pcpgsr = CPGSR_NO_CREDENTIAL_NOT_FINISHED;
    if (ppwszOptionalStatusText) *ppwszOptionalStatusText = nullptr;
    if (pcpsiOptionalStatusIcon) *pcpsiOptionalStatusIcon = CPSI_NONE;

    // SECOND FACTOR GATE: ask the agent whether the Owner is in view.
    FACE_RESULT fr = FaceIpcVerify();
    if (fr != FACE_OK)
    {
        PCWSTR msg = (fr == FACE_NOCAMERA)
            ? L"Camera unavailable — can't verify your face. Use your normal sign-in tile."
            : (fr == FACE_DENY)
                ? L"Face not recognized. Use your normal sign-in tile."
                : L"Face agent unreachable. Use your normal sign-in tile.";
        SetStatus(msg);
        if (ppwszOptionalStatusText) SHStrDupW(msg, ppwszOptionalStatusText);
        if (pcpsiOptionalStatusIcon) *pcpsiOptionalStatusIcon = CPSI_ERROR;
        // Stay on the tile; the user can switch to the standard provider.
        return S_OK;
    }

    // Face passed. The PASSWORD the user typed is the real authenticator.
    if (!_rgFieldStrings[FFI_PASSWORD] || !*_rgFieldStrings[FFI_PASSWORD])
    {
        SetStatus(L"Face OK. Now type your Windows password/PIN and submit.");
        return S_OK;
    }

    PWSTR pwzProtected = nullptr;
    HRESULT hr = ProtectIfNecessaryAndCopyPassword(_rgFieldStrings[FFI_PASSWORD], _cpus, &pwzProtected);
    if (FAILED(hr)) return hr;

    PWSTR pszDomain = nullptr; PWSTR pszUser = nullptr;
    if (_pszQualifiedUserName)
        SplitDomainAndUsername(_pszQualifiedUserName, &pszDomain, &pszUser);

    WCHAR wszComputer[MAX_COMPUTERNAME_LENGTH + 1] = {};
    DWORD cch = ARRAYSIZE(wszComputer);
    GetComputerNameW(wszComputer, &cch);

    KERB_INTERACTIVE_UNLOCK_LOGON kiul;
    hr = KerbInteractiveUnlockLogonInit(
        pszDomain ? pszDomain : wszComputer,
        pszUser ? pszUser : (_pszQualifiedUserName ? _pszQualifiedUserName : L""),
        pwzProtected, _cpus, &kiul);

    if (SUCCEEDED(hr))
    {
        hr = KerbInteractiveUnlockLogonPack(kiul, &pcpcs->rgbSerialization, &pcpcs->cbSerialization);
        if (SUCCEEDED(hr))
        {
            ULONG ulAuthPackage = 0;
            hr = RetrieveNegotiateAuthPackage(&ulAuthPackage);
            if (SUCCEEDED(hr))
            {
                pcpcs->ulAuthenticationPackage = ulAuthPackage;
                pcpcs->clsidCredentialProvider = CLSID_FaceIQProvider;
                *pcpgsr = CPGSR_RETURN_CREDENTIAL_FINISHED;
            }
        }
    }

    // Wipe the protected copy.
    if (pwzProtected)
    {
        SecureZeroMemory(pwzProtected, lstrlenW(pwzProtected) * sizeof(WCHAR));
        CoTaskMemFree(pwzProtected);
    }
    CoTaskMemFree(pszDomain);
    CoTaskMemFree(pszUser);
    return hr;
}

IFACEMETHODIMP CFaceCredential::ReportResult(NTSTATUS, NTSTATUS,
    PWSTR* ppwszOptionalStatusText, CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon)
{
    if (ppwszOptionalStatusText) *ppwszOptionalStatusText = nullptr;
    if (pcpsiOptionalStatusIcon) *pcpsiOptionalStatusIcon = CPSI_NONE;
    return S_OK;
}

IFACEMETHODIMP CFaceCredential::GetUserSid(PWSTR* ppszSid)
{
    if (!_pszUserSid) { *ppszSid = nullptr; return S_FALSE; }
    return SHStrDupW(_pszUserSid, ppszSid);
}
