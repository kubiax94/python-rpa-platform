#ifndef WIN32_NO_STATUS
#include <ntstatus.h>
#define WIN32_NO_STATUS
#endif
#include <unknwn.h>
#include "CSampleCredential.h"

#include "guid.h"

CSampleCredential::CSampleCredential() :
    _cRef(1),
    _hasData(false),
    _fIsLocalUser(false),
    _username(nullptr),
    _password(nullptr),
    _domain(nullptr),
    _pEvents(nullptr),
    _upAdviseContext(0),
    _pCredProvCredentialEvents(nullptr),
    _pszUserSid(nullptr),
    _pszQualifiedUserName(nullptr),
    _dwComboIndex(0),
    _fChecked(FALSE),
    _fShowControls(false)
	{



    ZeroMemory(_rgCredProvFieldDescriptors, sizeof(_rgCredProvFieldDescriptors));
    ZeroMemory(_rgFieldStatePairs, sizeof(_rgFieldStatePairs));
    ZeroMemory(_rgFieldStrings, sizeof(_rgFieldStrings));
}

CSampleCredential::~CSampleCredential() {
    if (_password)
    {
        // bezpiecznie wyczyœæ string (pe³na d³ugoœæ), potem zwolnij
        size_t len = wcslen(_password);
        SecureZeroMemory(_password, (len + 1) * sizeof(WCHAR));
        CoTaskMemFree(_password);
        _password = nullptr;
    }
    if (_username) { CoTaskMemFree(_username); _username = nullptr; }
    if (_domain) { CoTaskMemFree(_domain);   _domain = nullptr; }
}

// IUnknown

HRESULT CSampleCredential::InitializeData(PWSTR username, PWSTR password, PWSTR domain) {
    HRESULT hr = S_OK;
    if (username) {
        size_t cb = (wcslen(username) + 1) * sizeof(WCHAR);
        _username = (PWSTR)CoTaskMemAlloc(cb);
        if (!_username) return E_OUTOFMEMORY;
        memcpy(_username, username, cb);
		DebugLog("Username copied");
    }
    if (password) {
        // zostawiam ProtectIfNecessaryAndCopyPassword — oczekuje, ¿e zwraca CoTaskMemAlloc'owany bufor
        hr = ProtectIfNecessaryAndCopyPassword(password, _cpus, &_password);
    }
    if (domain) {
        size_t cb = (wcslen(domain) + 1) * sizeof(WCHAR);
        _domain = (PWSTR)CoTaskMemAlloc(cb);
        if (!_domain) return E_OUTOFMEMORY;
        memcpy(_domain, domain, cb);
		DebugLog("Domain copied");
    }
    DebugLog("Cred initialized");

	_hasData = true;
	return hr;
}

// KLUCZOWY MOMENT - PAKOWANIE DANYCH DO SYSTEMU
HRESULT CSampleCredential::GetSerialization(
    CREDENTIAL_PROVIDER_GET_SERIALIZATION_RESPONSE* pcpgsr,
    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcs,
    PWSTR* ppwszOptionalStatusText, CREDENTIAL_PROVIDER_STATUS_ICON* pcpsiOptionalStatusIcon)
{
	HRESULT hr = E_UNEXPECTED;
	DebugLog("GetSerialization called");
    *pcpgsr = CPGSR_NO_CREDENTIAL_NOT_FINISHED;

    // 1. Sprawdzamy rozmiar bufora
    *ppwszOptionalStatusText = nullptr;
    *pcpsiOptionalStatusIcon = CPSI_NONE;


    KERB_INTERACTIVE_UNLOCK_LOGON kiul;

	hr = KerbInteractiveUnlockLogonInit(_domain, _username, _password, CPUS_LOGON, &kiul);
    if (SUCCEEDED(hr))
    {
		DebugLog("KerbInteractiveUnlockLogonInit succeeded");
		hr = KerbInteractiveUnlockLogonPack(kiul, &pcpcs->rgbSerialization, &pcpcs->cbSerialization);
        if (SUCCEEDED(hr))
        {
			DebugLog("KerbInteractiveUnlockLogonPack succeeded");
			ULONG ulAuthPackage;
			hr = RetrieveNegotiateAuthPackage(&ulAuthPackage);
            if (SUCCEEDED(hr))
            {
                pcpcs->ulAuthenticationPackage = ulAuthPackage;
                pcpcs->clsidCredentialProvider = CLSID_CSample; // TU WPISZ SWÓJ GUID!
                *pcpgsr = CPGSR_RETURN_CREDENTIAL_FINISHED;
				DebugLog("GetSerialization succeeded");
                hr = S_OK;
			}
        }
    }

    return hr;
}

HRESULT CSampleCredential::SetSelected(BOOL* pbAutoLogon) {
    *pbAutoLogon = FALSE; // Mówimy: "Bierz ten kafelek natychmiast"
    return S_OK;
}
HRESULT CSampleCredential::CommandLinkClicked(DWORD dwFieldID) {
    return S_OK;
}

HRESULT CSampleCredential::GetCheckboxValue(DWORD dwFieldID, BOOL* pbChecked, PWSTR* ppwszLabel) {
    return E_NOTIMPL;
}

HRESULT CSampleCredential::GetComboBoxValueCount(DWORD dwFieldID, DWORD* pcItems, DWORD* pdwSelectedItem) {
    return E_NOTIMPL;
}

HRESULT CSampleCredential::GetComboBoxValueAt(DWORD dwFieldID, DWORD dwItem, PWSTR* ppwszItem) {
    return E_NOTIMPL;
}

HRESULT CSampleCredential::SetStringValue(DWORD dwFieldID, PCWSTR pwz) {
    return S_OK;
}

HRESULT CSampleCredential::SetCheckboxValue(DWORD dwFieldID, BOOL bChecked) {
    return S_OK;
}

HRESULT CSampleCredential::SetComboBoxSelectedValue(DWORD dwFieldID, DWORD dwSelectedItem) {
    return S_OK;
}

// Wymagane przez ICredentialProviderCredential2
HRESULT CSampleCredential::GetUserSid(PWSTR* ppszSid) {
    *ppszSid = nullptr;
    return E_NOTIMPL;
}

// Wymagane przez ICredentialProviderCredentialWithFieldOptions
HRESULT CSampleCredential::GetFieldOptions(DWORD dwFieldID, CREDENTIAL_PROVIDER_CREDENTIAL_FIELD_OPTIONS* pcpcfo) {
    *pcpcfo = CPCFO_NONE;
    return S_OK;
}

HRESULT CSampleCredential::Initialize(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
	CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR const* rgcpfd, FIELD_STATE_PAIR const* rgfsp,
	ICredentialProviderUser* pcpUser) {
    _cpus = cpus;

    return S_OK;

}

// Puste implementacje wymagane przez interfejs
HRESULT CSampleCredential::Advise(ICredentialProviderCredentialEvents*) { return S_OK; }
HRESULT CSampleCredential::UnAdvise() { return S_OK; }
HRESULT CSampleCredential::SetDeselected() { return S_OK; }
HRESULT CSampleCredential::GetFieldState(DWORD, CREDENTIAL_PROVIDER_FIELD_STATE* p, CREDENTIAL_PROVIDER_FIELD_INTERACTIVE_STATE* i) {
    *p = CPFS_HIDDEN; *i = CPFIS_NONE; return S_OK;
}
HRESULT CSampleCredential::GetStringValue(DWORD, PWSTR* pp) { *pp = NULL; return S_OK; }
HRESULT CSampleCredential::GetBitmapValue(DWORD, HBITMAP* ph) { *ph = NULL; return S_OK; }
HRESULT CSampleCredential::GetSubmitButtonValue(DWORD, DWORD*) { return S_OK; }
HRESULT CSampleCredential::ReportResult(NTSTATUS, NTSTATUS, PWSTR*, CREDENTIAL_PROVIDER_STATUS_ICON*) { return S_OK; }