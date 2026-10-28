// helpers.h — credential serialization helpers.
//
// These mirror Microsoft's public SampleCredentialProvider (MIT). They pack the
// username/domain/password the USER TYPES into the standard
// KERB_INTERACTIVE_UNLOCK_LOGON that LogonUI hands to LSA — exactly what the
// built-in password tile does. No secret is stored; the password lives only in
// the LogonUI buffer for the duration of the sign-in. Diff against the official
// sample for your Windows SDK version if anything fails to build.
#pragma once

#include <windows.h>
#include <credentialprovider.h>

HRESULT FieldDescriptorCopy(const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR& rcpfd,
                            CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* pcpfd);

HRESULT KerbInteractiveUnlockLogonInit(PWSTR pwzDomain, PWSTR pwzUsername, PWSTR pwzPassword,
                                       CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
                                       struct _KERB_INTERACTIVE_UNLOCK_LOGON* pkiul);

HRESULT KerbInteractiveUnlockLogonPack(const struct _KERB_INTERACTIVE_UNLOCK_LOGON& rkiulIn,
                                       BYTE** prgb, DWORD* pcb);

HRESULT ProtectIfNecessaryAndCopyPassword(PCWSTR pwzPassword,
                                          CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
                                          PWSTR* ppwzProtectedPassword);

// Split a "DOMAIN\\user" or "user" string into domain + username.
HRESULT SplitDomainAndUsername(PCWSTR pszQualifiedUserName, PWSTR* ppszDomain, PWSTR* ppszUsername);

// Look up the Negotiate authentication package for the serialized credential.
HRESULT RetrieveNegotiateAuthPackage(ULONG* pulAuthPackage);
