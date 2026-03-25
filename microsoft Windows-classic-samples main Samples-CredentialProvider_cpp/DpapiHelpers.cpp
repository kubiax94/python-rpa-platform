#include "DpapiHelpers.h"

HRESULT DpapiProtect(const BYTE* pbData, DWORD cbData, DWORD dwFlags, std::vector<BYTE>& outProtected) {
	if (!pbData || cbData == 0) {
		return E_INVALIDARG;
	}

	outProtected.clear();
	DATA_BLOB inBlob {cbData, const_cast<BYTE*>(pbData)};
	DATA_BLOB outBlob = { 0, nullptr };

	BOOL ok = CryptProtectData(
		&inBlob,
		nullptr, // opis
		nullptr, // optional entropy
		nullptr, // reserved
		nullptr, // prompt struct
		dwFlags,
		&outBlob
	);

	if (!ok) {
		return HRESULT_FROM_WIN32(GetLastError());
	}
	outProtected.assign(outBlob.pbData, outBlob.pbData + outBlob.cbData);

	SecureZeroMemory(outBlob.pbData, outBlob.cbData);
	LocalFree(outBlob.pbData);

	return S_OK;
}

HRESULT DpapiUnprotect(const BYTE* pbData, DWORD cbData, DWORD dwFlags, std::vector<BYTE>& outPlain) {
	if (!pbData || cbData == 0) {
		return E_INVALIDARG;
	}
	outPlain.clear();
	DATA_BLOB inBlob {cbData, const_cast<BYTE*>(pbData)};
	DATA_BLOB outBlob = { 0, nullptr };

	BOOL ok = CryptUnprotectData(
		&inBlob,
		nullptr, // opis
		nullptr, // optional entropy
		nullptr, // reserved
		nullptr, // prompt struct
		dwFlags,
		&outBlob
	);
	if (!ok) {
		return HRESULT_FROM_WIN32(GetLastError());
	}
	outPlain.assign(outBlob.pbData, outBlob.pbData + outBlob.cbData);

	SecureZeroMemory(outBlob.pbData, outBlob.cbData);
	LocalFree(outBlob.pbData);

	return S_OK;
}

HRESULT DpapiProtectString(const std::wstring& plain, DWORD dwFlags, std::vector<BYTE>& outProtected) {
	return DpapiProtect(reinterpret_cast<const BYTE*>(plain.data()), static_cast<DWORD>(plain.size() * sizeof(wchar_t)), dwFlags, outProtected);
}

HRESULT DpapiUnprotectToString(const std::vector<BYTE>& protectedBlob, DWORD dwFlags, std::wstring& outPlain) {
	std::vector<BYTE> plainBlob;
	HRESULT hr = DpapiUnprotect(protectedBlob.data(), static_cast<DWORD>(protectedBlob.size()), dwFlags, plainBlob);
	if (FAILED(hr)) {
		return hr;
	}
	outPlain.assign(reinterpret_cast<const wchar_t*>(plainBlob.data()), plainBlob.size() / sizeof(wchar_t));
	return S_OK;
}
