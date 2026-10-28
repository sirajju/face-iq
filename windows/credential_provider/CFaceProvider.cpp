// CFaceProvider.cpp — see CFaceProvider.h.
#include "CFaceProvider.h"
#include "CFaceCredential.h"
#include <new>

CFaceProvider::CFaceProvider() { DllAddRef(); }

CFaceProvider::~CFaceProvider()
{
    ReleaseEnumeratedCredentials();
    if (_pUserArray) { _pUserArray->Release(); _pUserArray = nullptr; }
    DllRelease();
}

void CFaceProvider::ReleaseEnumeratedCredentials()
{
    if (_pCredential) { _pCredential->Release(); _pCredential = nullptr; }
}

IFACEMETHODIMP_(ULONG) CFaceProvider::Release()
{
    long cRef = --_cRef;
    if (!cRef) delete this;
    return cRef;
}

IFACEMETHODIMP CFaceProvider::QueryInterface(REFIID riid, void** ppv)
{
    if (riid == IID_IUnknown || riid == IID_ICredentialProvider)
        *ppv = static_cast<ICredentialProvider*>(this);
    else if (riid == IID_ICredentialProviderSetUserArray)
        *ppv = static_cast<ICredentialProviderSetUserArray*>(this);
    else { *ppv = nullptr; return E_NOINTERFACE; }
    AddRef();
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::SetUsageScenario(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, DWORD)
{
    // Only offer the face tile where a user actually signs in / unlocks.
    switch (cpus)
    {
    case CPUS_LOGON:
    case CPUS_UNLOCK_WORKSTATION:
        _cpus = cpus;
        return S_OK;
    default:
        return E_NOTIMPL; // not shown for change-password, CredUI, etc.
    }
}

IFACEMETHODIMP CFaceProvider::SetSerialization(const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION*)
{
    return E_NOTIMPL;
}

IFACEMETHODIMP CFaceProvider::Advise(ICredentialProviderEvents*, UINT_PTR) { return S_OK; }
IFACEMETHODIMP CFaceProvider::UnAdvise() { return S_OK; }

IFACEMETHODIMP CFaceProvider::GetFieldDescriptorCount(DWORD* pdwCount)
{
    *pdwCount = FFI_NUM_FIELDS;
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::GetFieldDescriptorAt(DWORD dwIndex,
    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR** ppcpfd)
{
    if (dwIndex >= FFI_NUM_FIELDS || !ppcpfd) return E_INVALIDARG;
    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* pcpfd =
        static_cast<CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR*>(
            CoTaskMemAlloc(sizeof(CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR)));
    if (!pcpfd) return E_OUTOFMEMORY;
    *pcpfd = s_fieldDescriptors[dwIndex];
    SHStrDupW(s_fieldDescriptors[dwIndex].pszLabel, &pcpfd->pszLabel);
    *ppcpfd = pcpfd;
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::SetUserArray(ICredentialProviderUserArray* users)
{
    if (_pUserArray) _pUserArray->Release();
    _pUserArray = users;
    if (_pUserArray) _pUserArray->AddRef();
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::GetCredentialCount(DWORD* pdwCount, DWORD* pdwDefault,
    BOOL* pbAutoLogonWithDefault)
{
    *pdwCount = 1;
    *pdwDefault = CREDENTIAL_PROVIDER_NO_DEFAULT; // never the default tile
    *pbAutoLogonWithDefault = FALSE;              // never auto-logon

    ReleaseEnumeratedCredentials();
    _pCredential = new (std::nothrow) CFaceCredential();
    if (!_pCredential) return E_OUTOFMEMORY;

    ICredentialProviderUser* pUser = nullptr;
    if (_pUserArray)
    {
        DWORD cUsers = 0;
        _pUserArray->GetCount(&cUsers);
        if (cUsers > 0) _pUserArray->GetAt(0, &pUser); // selected/first user
    }

    HRESULT hr = _pCredential->Initialize(_cpus, s_fieldDescriptors, s_fieldStatePairs, pUser);
    if (pUser) pUser->Release();
    if (FAILED(hr)) { ReleaseEnumeratedCredentials(); return hr; }
    return S_OK;
}

IFACEMETHODIMP CFaceProvider::GetCredentialAt(DWORD dwIndex, ICredentialProviderCredential** ppcpc)
{
    if (dwIndex != 0 || !_pCredential || !ppcpc) return E_INVALIDARG;
    return _pCredential->QueryInterface(IID_PPV_ARGS(ppcpc));
}

HRESULT CFaceProvider_CreateInstance(REFIID riid, void** ppv)
{
    CFaceProvider* p = new (std::nothrow) CFaceProvider();
    if (!p) return E_OUTOFMEMORY;
    HRESULT hr = p->QueryInterface(riid, ppv);
    p->Release();
    return hr;
}
