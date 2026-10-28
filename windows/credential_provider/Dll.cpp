// Dll.cpp — COM DLL plumbing: class factory, exports, refcounts, self-register.
#include "common.h"
#include "CFaceProvider.h"
#include <new>
#include <strsafe.h>
#include <olectl.h>

HINSTANCE g_hInst = nullptr;
static long g_cDllRef = 0;

void DllAddRef()  { InterlockedIncrement(&g_cDllRef); }
void DllRelease() { InterlockedDecrement(&g_cDllRef); }

class CClassFactory : public IClassFactory
{
public:
    IFACEMETHODIMP_(ULONG) AddRef() { return ++_cRef; }
    IFACEMETHODIMP_(ULONG) Release() { long c = --_cRef; if (!c) delete this; return c; }
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv)
    {
        if (riid == IID_IUnknown || riid == IID_IClassFactory)
        { *ppv = static_cast<IClassFactory*>(this); AddRef(); return S_OK; }
        *ppv = nullptr; return E_NOINTERFACE;
    }
    IFACEMETHODIMP CreateInstance(IUnknown* pUnkOuter, REFIID riid, void** ppv)
    {
        if (pUnkOuter) return CLASS_E_NOAGGREGATION;
        return CFaceProvider_CreateInstance(riid, ppv);
    }
    IFACEMETHODIMP LockServer(BOOL bLock) { if (bLock) DllAddRef(); else DllRelease(); return S_OK; }
    CClassFactory() { DllAddRef(); }
private:
    ~CClassFactory() { DllRelease(); }
    long _cRef = 1;
};

STDAPI DllGetClassObject(REFCLSID rclsid, REFIID riid, void** ppv)
{
    if (rclsid != CLSID_FaceIQProvider) return CLASS_E_CLASSNOTAVAILABLE;
    CClassFactory* pcf = new (std::nothrow) CClassFactory();
    if (!pcf) return E_OUTOFMEMORY;
    HRESULT hr = pcf->QueryInterface(riid, ppv);
    pcf->Release();
    return hr;
}

STDAPI DllCanUnloadNow() { return (g_cDllRef == 0) ? S_OK : S_FALSE; }

BOOL WINAPI DllMain(HINSTANCE hInstance, DWORD dwReason, LPVOID)
{
    if (dwReason == DLL_PROCESS_ATTACH)
    {
        g_hInst = hInstance;
        DisableThreadLibraryCalls(hInstance);
    }
    return TRUE;
}

// ---- self registration (requires admin; or use register.reg) ---------------
static HRESULT SetKeyStringValue(HKEY root, PCWSTR subkey, PCWSTR name, PCWSTR value)
{
    HKEY hKey;
    LONG lr = RegCreateKeyExW(root, subkey, 0, nullptr, 0, KEY_WRITE, nullptr, &hKey, nullptr);
    if (lr != ERROR_SUCCESS) return HRESULT_FROM_WIN32(lr);
    lr = RegSetValueExW(hKey, name, 0, REG_SZ, (const BYTE*)value,
                        (DWORD)((lstrlenW(value) + 1) * sizeof(WCHAR)));
    RegCloseKey(hKey);
    return HRESULT_FROM_WIN32(lr);
}

STDAPI DllRegisterServer()
{
    WCHAR szModule[MAX_PATH];
    if (!GetModuleFileNameW(g_hInst, szModule, ARRAYSIZE(szModule)))
        return HRESULT_FROM_WIN32(GetLastError());

    WCHAR szGuid[64];
    StringFromGUID2(CLSID_FaceIQProvider, szGuid, ARRAYSIZE(szGuid));

    WCHAR szClsidKey[160];
    StringCchPrintfW(szClsidKey, ARRAYSIZE(szClsidKey), L"CLSID\\%s", szGuid);
    WCHAR szInproc[200];
    StringCchPrintfW(szInproc, ARRAYSIZE(szInproc), L"CLSID\\%s\\InprocServer32", szGuid);
    WCHAR szCpKey[200];
    StringCchPrintfW(szCpKey, ARRAYSIZE(szCpKey),
        L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Authentication\\Credential Providers\\%s", szGuid);

    HRESULT hr = SetKeyStringValue(HKEY_CLASSES_ROOT, szClsidKey, nullptr, L"FaceIQ Credential Provider");
    if (SUCCEEDED(hr)) hr = SetKeyStringValue(HKEY_CLASSES_ROOT, szInproc, nullptr, szModule);
    if (SUCCEEDED(hr)) hr = SetKeyStringValue(HKEY_CLASSES_ROOT, szInproc, L"ThreadingModel", L"Apartment");
    if (SUCCEEDED(hr)) hr = SetKeyStringValue(HKEY_LOCAL_MACHINE, szCpKey, nullptr, L"FaceIQ Credential Provider");
    return hr;
}

STDAPI DllUnregisterServer()
{
    WCHAR szGuid[64];
    StringFromGUID2(CLSID_FaceIQProvider, szGuid, ARRAYSIZE(szGuid));
    WCHAR szClsidKey[160], szCpKey[200];
    StringCchPrintfW(szClsidKey, ARRAYSIZE(szClsidKey), L"CLSID\\%s", szGuid);
    StringCchPrintfW(szCpKey, ARRAYSIZE(szCpKey),
        L"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Authentication\\Credential Providers\\%s", szGuid);
    RegDeleteTreeW(HKEY_CLASSES_ROOT, szClsidKey);
    RegDeleteTreeW(HKEY_LOCAL_MACHINE, szCpKey);
    return S_OK;
}
