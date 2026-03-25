#include "AgentNamedPipe.h"

#include <thread>
#include <string>

#include "dpapihelpers.h"
#include <threads.h>

// Definition of LogonCommand structure
// @op - operation code (2 bytes)
// @padding_1 - padding (2 bytes)
// @padding_2 - padding (4 bytes)
// @data - data buffer (256 bytes)
struct UserData
{
	WCHAR username[64];
	WCHAR password[64];
	WCHAR domain[64];
};

struct LogonCommand {
	uint8_t op;
	uint8_t reserved;
	uint16_t length;
	uint8_t data[384];
};
;
static const DWORD CONNECT_RETRY_MS = 200;
static const int CONNECT_RETRIES = 25; // ~5s total

static PCWSTR REG_PATH = L"SOFTWARE\\SampleCredProvider\\AgentPending";
static PCWSTR REG_VALUE_PIPENAME = L"PipeName";
static PCWSTR REG_VALUE_SECRET = L"Secret";

enum AgentStatus {
	AGENT_STATUS_OK = 0,
	AGENT_STATUS_ERROR = 1,
	AGENT_STATUS_INVALID_COMMAND = 2,
	AGENT_STATUS_PROCESSING = 3
};

SECURITY_ATTRIBUTES* GetPipeSecurityAttributes() {
	static SECURITY_ATTRIBUTES sa;
	static SECURITY_DESCRIPTOR sd;
	InitializeSecurityDescriptor(&sd, SECURITY_DESCRIPTOR_REVISION);
	// Ustawiamy pusty DACL (Everyone ma dost�p) - do test�w. 
	// Docelowo warto tu doda� tylko SID grupy SYSTEM.
	SetSecurityDescriptorDacl(&sd, TRUE, NULL, FALSE);
	sa.nLength = sizeof(SECURITY_ATTRIBUTES);
	sa.lpSecurityDescriptor = &sd;
	sa.bInheritHandle = FALSE;
	return &sa;
}

static void DebugLogWin32Error(const char* prefix, DWORD errorCode) {
	char buffer[256];
	StringCchPrintfA(buffer, ARRAYSIZE(buffer), "%s (error=%lu)", prefix, errorCode);
	DebugLog(buffer);
}

AgentNamedPipe::~AgentNamedPipe() {
	_stopRequested = true;

	if (_hPipe != INVALID_HANDLE_VALUE) {
		DisconnectNamedPipe(_hPipe);
		CloseHandle(_hPipe);
		_hPipe = INVALID_HANDLE_VALUE;
	}

	if (_listenerThread.joinable()) {
		_listenerThread.join();
	}

	if (_pEvents)
	{
		_pEvents->Release();
		_pEvents = nullptr;
	}

	if (_pipeName) {
		CoTaskMemFree(_pipeName);
		_pipeName = nullptr;
	}

	if (_cpUsageScenario) {
		_cpUsageScenario = nullptr;
	}

	if (_pCProvider) {
		_pCProvider->Release();
		_pCProvider = nullptr;
	}

	DllRelease();
}

HRESULT AgentNamedPipe::Initialize(ICredentialProviderEvents* pcpe, UINT_PTR upAdviceContext) {
	HRESULT hr = S_OK;

	if (pcpe) {

		_pEvents = pcpe;
		_upAdviseContext = upAdviceContext;
		_pEvents->AddRef();

	}

	if (*_cpUsageScenario != CPUS_LOGON) {
		DebugLog("AgentNamedPipe: Invalid usage scenario");
		return E_INVALIDARG;
	}
	// Try to find the agent data from registry, it should be provided by client druign login attempt or reconnect
	hr = this->ListenForCommand();
	return hr;
}

HRESULT AgentNamedPipe::_readFromRegistry(_In_ PCWSTR keyName, _In_ BOOL isEncrypted, _Out_ PWSTR* outValu) {
	DebugLog("AgentNamedPipe: Opened registry key successfully");
	HKEY hKey = nullptr;

	LSTATUS status = RegOpenKeyExW(HKEY_LOCAL_MACHINE, REG_PATH, 0, KEY_READ | KEY_WOW64_64KEY, &hKey);

	if (status == ERROR_SUCCESS) {
		DebugLog("AgentNamedPipe: Opened registry key successfully");
		DWORD size = 0;
		DWORD type = 0;

		status = RegQueryValueExW(hKey, keyName, nullptr, &type, nullptr, &size);

		if (status == ERROR_SUCCESS)
		{
			DebugLog("AgentNamedPipe: Queried registry value successfully");

			if (type != REG_SZ && type != REG_EXPAND_SZ)
			{
				RegCloseKey(hKey);
				return E_INVALIDARG;
			}

			PWSTR temp = static_cast<PWSTR>(CoTaskMemAlloc(size));

			if (!temp) {
				RegCloseKey(hKey);
				DebugLog("AgentNamedPipe: CoTaskMemAlloc failed");
				return E_OUTOFMEMORY;
			}

			status = RegQueryValueExW(hKey, keyName, nullptr, nullptr, reinterpret_cast<LPBYTE>(temp), &size);

			if (status == ERROR_SUCCESS && isEncrypted)
			{
				DWORD outSize = 0;
				if (CryptUnprotectData(
					reinterpret_cast<DATA_BLOB*>(outValu),
					nullptr,
					nullptr,
					nullptr,
					nullptr,
					0,
					reinterpret_cast<DATA_BLOB*>(&outSize)))
				{
					// Successfully decrypted
					
					status = ERROR_SUCCESS;
				}
				else
				{
					status = GetLastError();
				}
			}
			else if (status == ERROR_SUCCESS)
			{
				*outValu = temp;
			}
			else
			{
				CoTaskMemFree(temp);
			}

		}

		RegCloseKey(hKey);
	}

	return HRESULT_FROM_WIN32(status);
}

HRESULT AgentNamedPipe::ListenForCommand() {
	if (_cpUsageScenario == nullptr) {
		return E_INVALIDARG;
	}

	if (_listenerThread.joinable()) {
		DebugLog("AgentNamedPipe: Listener already running");
		return S_OK;
	}

	HRESULT hr = S_OK;

	DebugLog("AgentNamedPipe: Reading pipe name from registry");
	hr = this->_readFromRegistry(REG_VALUE_PIPENAME, FALSE, &_pipeName);

	if (FAILED(hr)) {
		DebugLog("AgentNamedPipe: Failed to read pipe name from registry");
		return hr;
	}
	DebugLog("AgentNamedPipe: Read pipe name from registry");



	DebugLog("AgentNamedPipe: Starting command listener thread");
	_listenerThread = std::thread([this]() {
		DllAddRef();
		DebugLog("AgentNamedPipe: Listening for commands on pipe ws");

		while (!_stopRequested && *_cpUsageScenario != CPUS_UNLOCK_WORKSTATION)
		{
			DebugLog("AgentNamedPipe: Creating named pipe");

			HANDLE hPipe = CreateNamedPipe(
				_pipeName,          // pipe name
				PIPE_ACCESS_DUPLEX, // read/write access
				PIPE_TYPE_MESSAGE | // message type pipe
				PIPE_READMODE_MESSAGE | // message-read mode
				PIPE_WAIT,          // blocking mode
				1,                  // max. instances
				1024,                // output buffer size
				1024,                // input buffer size
				0,                  // client time-out
				GetPipeSecurityAttributes());

			
			if (hPipe == INVALID_HANDLE_VALUE)
			{
				DebugLogWin32Error("AgentNamedPipe: Failed to create named pipe", GetLastError());
				Sleep(250);
				continue;
			}
			this->_hPipe = hPipe;
			DebugLog("AgentNamedPipe: Waiting for client to connect to pipe");
			BOOL connected = ConnectNamedPipe(hPipe, nullptr);
			DWORD connectError = connected ? ERROR_SUCCESS : GetLastError();
			if (connected || connectError == ERROR_PIPE_CONNECTED) {
				DebugLog("AgentNamedPipe: Client connected to pipe");
				// Successfully connected
				LogonCommand command;
				DWORD bytesRead = 0;
				
				if (ReadFile(hPipe, &command, sizeof(command), &bytesRead, nullptr) && bytesRead == sizeof(command)) {
					// Process command
					switch (command.op) {
					case 0x00: // Example command
						// Handle command
						
						UserData* userData = reinterpret_cast<UserData*>(command.data);

						if (userData) {
							// Process user data
							DebugLog("AgentNamedPipe: Received user data from pipe");
							if (_pCProvider) {
								_pCProvider->Release();
								_pCProvider = nullptr;
							}
							_pCProvider = new (std::nothrow) CSampleCredential();
							if (!_pCProvider) {
								DebugLog("AgentNamedPipe: Failed to allocate CSampleCredential");
								break;
							}

							DebugLog(userData->username);
							DebugLog(userData->password);
							DebugLog(userData->domain);


							_pCProvider->InitializeData(
								userData->username,
								userData->password,
								userData->domain
							);

							SecureZeroMemory(&command, sizeof(command));

							if (_pEvents)
								_pEvents->CredentialsChanged(_upAdviseContext);

						}
						else {
							DebugLog("AgentNamedPipe: Invalid user data received");
						}
						break;
					}
				}
				else {
					DebugLogWin32Error("AgentNamedPipe: ReadFile failed", GetLastError());
				}
			} else {
				DebugLogWin32Error("AgentNamedPipe: ConnectNamedPipe failed", connectError);
			}

			FlushFileBuffers(hPipe);
			DisconnectNamedPipe(hPipe);
			CloseHandle(hPipe);
			this->_hPipe = INVALID_HANDLE_VALUE;
			DebugLog("AgentNamedPipe: Client disconnected from pipe");
		}
		DllRelease();
	});

	return hr;
}

CSampleCredential* AgentNamedPipe::HasData() { return this->_pCProvider; }

CSampleCredential* AgentNamedPipe::TakeCredential() {
	CSampleCredential* credential = _pCProvider;
	_pCProvider = nullptr;
	return credential;
}

HRESULT AgentNamedPipe::_writeToPipe(const LogonCommand& command) {
	if (_hPipe == INVALID_HANDLE_VALUE) {
		return E_FAIL;
	}
}

HRESULT AgentNamedPipe::_readFromPipe(LogonCommand& command) {
}
