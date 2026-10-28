// helpers.cpp — see helpers.h. Mirrors Microsoft's SampleCredentialProvider.
#include "helpers.h"
#include <intsafe.h>
#include <ntsecapi.h>   // KERB_INTERACTIVE_UNLOCK_LOGON, KERB_INTERACTIVE_LOGON
#include <wincred.h>    // CredProtect
#include <strsafe.h>
#include <string.h>

#pragma comment(lib, "Secur32.lib")
#pragma comment(lib, "Credui.lib")

HRESULT FieldDescriptorCopy(const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR& rcpfd,
                            CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* pcpfd)
{
    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR cpfd = rcpfd;
    HRESULT hr = SHStrDupW(rcpfd.pszLabel, &cpfd.pszLabel);
    if (SUCCEEDED(hr))
        *pcpfd = cpfd;
    return hr;
}

static void UnicodeStringInitWithString(PWSTR pwz, UNICODE_STRING* pus)
{
    if (pwz)
    {
        size_t lenInChars = lstrlenW(pwz);
        pus->Length = static_cast<USHORT>(lenInChars * sizeof(WCHAR));
        pus->MaximumLength = static_cast<USHORT>((lenInChars + 1) * sizeof(WCHAR));
        pus->Buffer = pwz;
    }
    else
    {
        pus->Length = 0; pus->MaximumLength = 0; pus->Buffer = nullptr;
    }
}

HRESULT KerbInteractiveUnlockLogonInit(PWSTR pwzDomain, PWSTR pwzUsername, PWSTR pwzPassword,
                                       CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
                                       KERB_INTERACTIVE_UNLOCK_LOGON* pkiul)
{
    KERB_INTERACTIVE_UNLOCK_LOGON kiul = {};
    KERB_INTERACTIVE_LOGON* pkil = &kiul.Logon;

    UnicodeStringInitWithString(pwzDomain, &pkil->LogonDomainName);
    UnicodeStringInitWithString(pwzUsername, &pkil->UserName);
    UnicodeStringInitWithString(pwzPassword, &pkil->Password);

    pkil->MessageType = (cpus == CPUS_UNLOCK_WORKSTATION)
        ? KerbWorkstationUnlockLogon : KerbInteractiveLogon;

    *pkiul = kiul;
    return S_OK;
}

static void AppendAndAdvance(const UNICODE_STRING& src, BYTE* base, BYTE** cursor, UNICODE_STRING* dst)
{
    LONG_PTR offset = *cursor - base;
    dst->Length = src.Length;
    dst->MaximumLength = src.Length;
    if (src.Length)
    {
        CopyMemory(*cursor, src.Buffer, src.Length);
        dst->Buffer = reinterpret_cast<PWSTR>(offset);
        *cursor += src.Length;
    }
    else
    {
        dst->Buffer = nullptr;
    }
}

HRESULT KerbInteractiveUnlockLogonPack(const KERB_INTERACTIVE_UNLOCK_LOGON& rkiulIn,
                                       BYTE** prgb, DWORD* pcb)
{
    const KERB_INTERACTIVE_LOGON& rkilIn = rkiulIn.Logon;

    DWORD cb = sizeof(rkiulIn)
        + rkilIn.LogonDomainName.Length
        + rkilIn.UserName.Length
        + rkilIn.Password.Length;

    KERB_INTERACTIVE_UNLOCK_LOGON* pkiulOut =
        static_cast<KERB_INTERACTIVE_UNLOCK_LOGON*>(CoTaskMemAlloc(cb));
    if (!pkiulOut) return E_OUTOFMEMORY;

    ZeroMemory(&pkiulOut->LogonId, sizeof(pkiulOut->LogonId));
    pkiulOut->Logon.MessageType = rkilIn.MessageType;

    BYTE* base = reinterpret_cast<BYTE*>(pkiulOut);
    BYTE* cursor = base + sizeof(*pkiulOut);

    AppendAndAdvance(rkilIn.LogonDomainName, base, &cursor, &pkiulOut->Logon.LogonDomainName);
    AppendAndAdvance(rkilIn.UserName, base, &cursor, &pkiulOut->Logon.UserName);
    AppendAndAdvance(rkilIn.Password, base, &cursor, &pkiulOut->Logon.Password);

    *prgb = reinterpret_cast<BYTE*>(pkiulOut);
    *pcb = cb;
    return S_OK;
}

HRESULT ProtectIfNecessaryAndCopyPassword(PCWSTR pwzPassword,
                                          CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
                                          PWSTR* ppwzProtectedPassword)
{
    *ppwzProtectedPassword = nullptr;
    if (!pwzPassword || !*pwzPassword)
        return SHStrDupW(L"", ppwzProtectedPassword);

    // Only CredProtect for the remote-credential scenarios the sample lists; for
    // local logon/unlock we pass the password straight through to LSA.
    bool bCredAlreadyEncrypted = false;
    CRED_PROTECTION_TYPE protectionType;
    if (CredIsProtectedW(const_cast<PWSTR>(pwzPassword), &protectionType) &&
        protectionType != CredUnprotected)
    {
        bCredAlreadyEncrypted = true;
    }

    if (CPUS_CREDUI == cpus && !bCredAlreadyEncrypted)
    {
        DWORD cch = 0;
        CredProtectW(FALSE, const_cast<PWSTR>(pwzPassword),
                     lstrlenW(pwzPassword) + 1, nullptr, &cch, nullptr);
        if (cch)
        {
            PWSTR pwz = static_cast<PWSTR>(CoTaskMemAlloc(cch * sizeof(WCHAR)));
            if (!pwz) return E_OUTOFMEMORY;
            if (CredProtectW(FALSE, const_cast<PWSTR>(pwzPassword),
                             lstrlenW(pwzPassword) + 1, pwz, &cch, nullptr))
            {
                *ppwzProtectedPassword = pwz;
                return S_OK;
            }
            CoTaskMemFree(pwz);
        }
    }
    return SHStrDupW(pwzPassword, ppwzProtectedPassword);
}

HRESULT SplitDomainAndUsername(PCWSTR pszQualifiedUserName, PWSTR* ppszDomain, PWSTR* ppszUsername)
{
    *ppszDomain = nullptr; *ppszUsername = nullptr;
    const WCHAR* pch = wcschr(pszQualifiedUserName, L'\\');
    if (pch)
    {
        size_t domLen = pch - pszQualifiedUserName;
        PWSTR dom = static_cast<PWSTR>(CoTaskMemAlloc((domLen + 1) * sizeof(WCHAR)));
        if (!dom) return E_OUTOFMEMORY;
        StringCchCopyNW(dom, domLen + 1, pszQualifiedUserName, domLen);
        PWSTR user = nullptr;
        HRESULT hr = SHStrDupW(pch + 1, &user);
        if (FAILED(hr)) { CoTaskMemFree(dom); return hr; }
        *ppszDomain = dom; *ppszUsername = user;
        return S_OK;
    }
    // No domain: use the local machine name as domain.
    *ppszDomain = nullptr;
    return SHStrDupW(pszQualifiedUserName, ppszUsername);
}

HRESULT RetrieveNegotiateAuthPackage(ULONG* pulAuthPackage)
{
    HANDLE hLsa = nullptr;
    NTSTATUS status = LsaConnectUntrusted(&hLsa);
    if (status < 0) return HRESULT_FROM_NT(status);

    HRESULT hr;
    ULONG ulAuthPackage = 0;
    LSA_STRING name;
    char szNegotiate[] = "Negotiate";
    name.Buffer = szNegotiate;
    name.Length = (USHORT)strlen(szNegotiate);
    name.MaximumLength = (USHORT)(strlen(szNegotiate) + 1);

    status = LsaLookupAuthenticationPackage(hLsa, &name, &ulAuthPackage);
    if (status >= 0) { *pulAuthPackage = ulAuthPackage; hr = S_OK; }
    else hr = HRESULT_FROM_NT(status);

    LsaDeregisterLogonProcess(hLsa);
    return hr;
}
