#pragma once
#include <atomic>
#include <thread>
#include <intsafe.h>
#include "helpers.h"
#include "CSampleCredential.h"

struct LogonCommand;

class AgentNamedPipe {


	public:
	AgentNamedPipe(CREDENTIAL_PROVIDER_USAGE_SCENARIO* cp_usage_scenario)
		: _cpUsageScenario(cp_usage_scenario),
		  _pipeName(nullptr),
		  _fWreadOnce(false) {
	}

	HRESULT									Initialize(ICredentialProviderEvents* pcpe, UINT_PTR upAdviceContext);
	HRESULT									ListenForCommand();
	CSampleCredential*						HasData(); // return credential if available, else nullptr, password is encrypted
	CSampleCredential*					TakeCredential();
	~AgentNamedPipe();

private:
	CREDENTIAL_PROVIDER_USAGE_SCENARIO*		_cpUsageScenario;
	PWSTR									_pipeName;
	bool									_fWreadOnce = false;
	UINT_PTR								_upAdviseContext;

	ICredentialProviderEvents*				_pEvents = nullptr;
	CSampleCredential*						_pCProvider = nullptr;
	HANDLE									_hPipe = INVALID_HANDLE_VALUE;
	std::atomic<bool>						_stopRequested = false;
	std::thread								_listenerThread;
	HRESULT									_writeToPipe(const LogonCommand& command);
	HRESULT									_readFromPipe(LogonCommand& command);
	HRESULT									_readFromRegistry(_In_ PCWSTR keyName, _In_ BOOL isEncrypted, _Out_ PWSTR* outValu);

};
