#pragma once

#include <windows.h>
#include <vector>
#include <string>

HRESULT DpapiProtect(
    _In_reads_bytes_(cbData) const BYTE* pbData,
    _In_ DWORD cbData,
    _In_ DWORD dwFlags, // np. CRYPTPROTECT_LOCAL_MACHINE
    _Out_ std::vector<BYTE>& outProtected);

HRESULT DpapiUnprotect(
    _In_reads_bytes_(cbData) const BYTE* pbData,
    _In_ DWORD cbData,
    _In_ DWORD dwFlags,
    _Out_ std::vector<BYTE>& outPlain);

HRESULT DpapiProtectString(
    _In_ const std::wstring& plain,
    _In_ DWORD dwFlags,
    _Out_ std::vector<BYTE>& outProtected);

HRESULT DpapiUnprotectToString(
    _In_ const std::vector<BYTE>& protectedBlob,
    _In_ DWORD dwFlags,
    _Out_ std::wstring& outPlain);