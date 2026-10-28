// CFaceCredential.h — one lock-screen tile. Face is a SECOND FACTOR: the user
// still types their Windows password/PIN, which is what authenticates.
#pragma once

#include <windows.h>
#include <credentialprovider.h>
#include "common.h"

class CFaceCredential : public ICredentialProviderCredential2
{
public:
    // IUnknown
    IFACEMETHODIMP_(ULONG) AddRef() { return ++_cRef; }
    IFACEMETHODIMP_(ULONG) Release();
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv);

    // ICredentialProviderCredential
    IFACEMETHODIMP Advise(ICredentialProviderCredentialEvents* pcpce);
    IFACEMETHODIMP UnAdvise();
    IFACEMETHODIMP SetSelected(BOOL* pbAutoLogon);
    IFACEMETHODIMP SetDeselected();
    IFACEMETHODIMP GetFieldState(DWORD dwFieldID,
        CREDENTIAL_PROVIDER_FIELD_STATE* pcpfs,
        CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* pcpfis);
    IFACEMETHODIMP GetStringValue(DWORD dwFieldID, PWSTR* ppwsz);
    IFACEMETHODIMP GetBitmapValue(DWORD dwFieldID, HBITMAP* phbmp);
    IFACEMETHODIMP GetCheckboxValue(DWORD, BOOL*, PWSTR*) { return E_NOTIMPL; }
    IFACEMETHODIMP GetComboBoxValueCount(DWORD, DWORD*, DWORD*) { return E_NOTIMPL; }
    IFACEMETHODIMP GetComboBoxValueAt(DWORD, DWORD, PWSTR*) { return E_NOTIMPL; }
    IFACEMETHODIMP GetSubmitButtonValue(DWORD dwFieldID, DWORD* pdwAdjacentTo);
    IFACEMETHODIMP SetStringValue(DWORD dwFieldID, PCWSTR pwz);
    IFACEMETHODIMP SetCheckboxValue(DWORD, BOOL) { return E_NOTIMPL; }
    IFACEMETHODIMP SetComboBoxSelectedValue(DWORD, DWORD) { return E_NOTIMPL; }
    IFACEMETHODIMP CommandLinkClicked(DWORD) { return E_NOTIMPL; }
    IFACEMETHODIMP GetSerialization(CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* pcpgsr,
        CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs,
        PWSTR* ppwszOptionalStatusText,
        CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon);
    IFACEMETHODIMP ReportResult(NTSTATUS ntsStatus, NTSTATUS ntsSubstatus,
        PWSTR* ppwszOptionalStatusText,
        CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon);

    // ICredentialProviderCredential2
    IFACEMETHODIMP GetUserSid(PWSTR* ppszSid);

    HRESULT Initialize(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
                       const CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR* rgcpfd,
                       const CREDENTIAL_PROVIDER_FIELD_STATE_PAIR* rgfsp,
                       ICredentialProviderUser* pcpUser);
    CFaceCredential();

private:
    ~CFaceCredential();
    long _cRef = 1;
    CREDENTIAL_PROVIDER_USAGE_SCENARIO _cpus = CPUS_INVALID;
    CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR _rgFieldDescriptors[FFI_NUM_FIELDS] = {};
    CREDENTIAL_PROVIDER_FIELD_STATE_PAIR _rgFieldStatePairs[FFI_NUM_FIELDS] = {};
    PWSTR _rgFieldStrings[FFI_NUM_FIELDS] = {};
    PWSTR _pszUserSid = nullptr;
    PWSTR _pszQualifiedUserName = nullptr;
    ICredentialProviderCredentialEvents* _pcpce = nullptr;

    void SetStatus(PCWSTR text);
};
