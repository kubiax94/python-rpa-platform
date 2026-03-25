#include <initguid.h>
#include "CSampleProvider.h"

#include <shlwapi.h>

#include "CSampleCredential.h"
#include "Dll.h"
#include "guid.h"

// Konstruktor
CSampleProvider::CSampleProvider() : _cRef(1), _pEvents(nullptr), _upAdviseContext(0), _bReadyToLogon(false), _pCredential(nullptr), _pPipeClient(nullptr), _fRecreateEnumeratedCredentials(false), _cpus(CPUS_INVALID), _pCredProviderUserArray(nullptr) {
    DllAddRef();
	
}

CSampleProvider::~CSampleProvider() {
    if (_pEvents) _pEvents->Release();
    if (_pPipeClient) {
        delete _pPipeClient;
        _pPipeClient = nullptr;
    }

    DllRelease();
}

// Besaide init this is main method where we setup our provider, and catch it's state, after that Avise is called
HRESULT CSampleProvider::SetUsageScenario(CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus, DWORD dwFlags) {
	HRESULT hr = S_OK;
    
    switch (cpus) {
    case CPUS_LOGON:
        DebugLog("SetUsageScenario: Logon");
		_cpus = cpus;
		if (!_pPipeClient) {
			_pPipeClient = new (std::nothrow) AgentNamedPipe(&_cpus);
			if (!_pPipeClient) {
				return E_OUTOFMEMORY;
			}
        } else {
			DebugLog("SetUsageScenario: Reusing existing pipe client");
        }
        break;
    case CPUS_UNLOCK_WORKSTATION:
        _cpus = cpus;
		DebugLog("SetUsageScenario: CPUS_UNLOCK_WORKSTATION");
		DebugLog("SetUsageScenario: Pipe client initialized");
		hr = S_OK;
        break;

    // TODO: Probably we could also automate password changing here
    case CPUS_CHANGE_PASSWORD:
	case CPUS_CREDUI: // I dont know still what is this scenario for
        _cpus = cpus;
		DebugLog("SetUsageScenario: Not implemented for this scenario");
        hr = S_OK;
        break;
    default:
        hr = E_INVALIDARG;
        break;
    }

    return hr;
}


HRESULT CSampleProvider::Advise(ICredentialProviderEvents* pcpe, UINT_PTR upAdviseContext) {
	DebugLog("Advise called");
	HRESULT hr = S_OK;

    if (_cpus != CPUS_LOGON)
    {
        DebugLog("SetUsageScenario: Advise called in invalid scenario");
        return E_INVALIDARG;
	}

	if (pcpe) {
        _pEvents = pcpe;
        _pEvents->AddRef();
        _upAdviseContext = upAdviseContext;
    }

	hr = _pPipeClient->Initialize(_pEvents, upAdviseContext);

	if (FAILED(hr))
    {
        DebugLog("SetUsageScenario: Pipe client initialization failed");
        return hr;
    }

	return S_OK;
}

HRESULT CSampleProvider::UnAdvise() {
    if (_pEvents) { _pEvents->Release(); _pEvents = nullptr; }
    return S_OK;
}

HRESULT CSampleProvider::GetFieldDescriptorCount(DWORD* pdwCount) {
    *pdwCount = 0; // Minimalizm - zero p�l widocznych dla usera
    return S_OK;
}

HRESULT CSampleProvider::GetFieldDescriptorAt(DWORD, CREDENTIAL_PROVIDER_FIELD_DESCRIPTOR**) { return E_NOTIMPL; }

// WYMUSZENIE LOGOWANIA
HRESULT CSampleProvider::GetCredentialCount(DWORD* pdwCount, DWORD* pdwDefault, BOOL* pbAutoLogonWithDefault) {

	if (_pPipeClient && _pPipeClient->HasData())
	{
        *pdwCount = 1;
        *pdwDefault = 0;
        *pbAutoLogonWithDefault = TRUE;
		DebugLog("GetCredentialCount: Ready to logon");
	}
    else {
        *pdwCount = 0; // Jeste�my niewidoczni!
        *pbAutoLogonWithDefault = FALSE;
    }
    return S_OK;
}
// Implementacja filtra (nawet je�li nic nie robi, musi istnie�)
HRESULT CSampleProvider::Filter(
    CREDENTIAL_PROVIDER_USAGE_SCENARIO cpus,
    DWORD dwFlags,
    GUID* rgclsidProviders,
    BOOL* rgbAllow,
    DWORD dwCount)
{
    // Na razie pozwalamy na wszystko, �eby nie blokowa� debugowania
    return S_OK;
}

// Kolejna metoda, kt�rej szuka linker
HRESULT CSampleProvider::UpdateRemoteCredential(
    const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcsIn,
    CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION* pcpcsOut)
{
    return E_NOTIMPL;
}

HRESULT CSampleProvider::GetCredentialAt(DWORD dwIndex, ICredentialProviderCredential** ppcpc) {
    if (!ppcpc) return E_POINTER;
    *ppcpc = nullptr;

    if (dwIndex != 0) return E_INVALIDARG;

    if (!_pPipeClient) return E_UNEXPECTED;

    CSampleCredential* credential = _pPipeClient->TakeCredential();
    if (!credential) return E_UNEXPECTED;

    HRESULT hrQI = credential->QueryInterface(IID_PPV_ARGS(ppcpc));
    credential->Release();
    return hrQI;
}

HRESULT CSample_CreateInstance(REFIID riid, void** ppv) {
    CSampleProvider* pProvider = new (std::nothrow) CSampleProvider();
    if (pProvider) {
        HRESULT hr = pProvider->QueryInterface(riid, ppv);
        pProvider->Release();
        return hr;
    }
    return E_OUTOFMEMORY;
}

HRESULT CSampleProvider::SetSerialization(const CREDENTIAL_PROVIDER_CREDENTIAL_SERIALIZATION*) {
	DebugLog("SetSerialization called - not implemented");
	return E_NOTIMPL;
}