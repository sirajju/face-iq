// CFaceProvider.h — the ICredentialProvider. Registers as an ADDITIONAL provider
// for logon/unlock and offers one FaceIQ second-factor tile per user.
#pragma once

#include <windows.h>
#include <credentialprovider.h>
#include "common.h"

class CFaceCredential;

class CFaceProvider : public ICredentialProvider, public ICredentialProviderSetUserArray
{
public:
    IFACEMETHODIMP_(ULONG) AddRef() { return ++_cRef; }
    IFACEMETHODIMP_(ULONG) Release();
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv);

    // ICredentialProvider
    IFACEMETHODIMP SetUsageScenario(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, DWORD dwFlags);
    IFACEMETHODIMP SetSerialization(const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs);
    IFACEMETHODIMP Advise(ICredentialProviderEvents* pcpe, UINT_PTR upAdviseContext);
    IFACEMETHODIMP UnAdvise();
    IFACEMETHODIMP GetFieldDescriptorCount(DWORD* pdwCount);
    IFACEMETHODIMP GetFieldDescriptorAt(DWORD dwIndex, CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd);
    IFACEMETHODIMP GetCredentialCount(DWORD* pdwCount, DWORD* pdwDefault, BOOL* pbAutoLogonWithDefault);
    IFACEMETHODIMP GetCredentialAt(DWORD dwIndex, ICredentialProviderCredential** ppcpc);

    // ICredentialProviderSetUserArray
    IFACEMETHODIMP SetUserArray(ICredentialProviderUserArray* users);

    CFaceProvider();

private:
    ~CFaceProvider();
    void ReleaseEnumeratedCredentials();

    long _cRef = 1;
    CREDENTIAL_PROVIDER_USAGE_SCENARIO _cpus = CPUS_INVALID;
    CFaceCredential* _pCredential = nullptr;
    ICredentialProviderUserArray* _pUserArray = nullptr;
};

HRESULT CFaceProvider_CreateInstance(REFIID riid, void** ppv);
