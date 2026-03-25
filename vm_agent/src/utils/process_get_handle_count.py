import ctypes
import ctypes.wintypes

def get_handle_count(pid):
    PROCESS_QUERY_INFORMATION = 0x0400
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        return None
    count = ctypes.wintypes.DWORD()
    res = ctypes.windll.kernel32.GetProcessHandleCount(handle, ctypes.byref(count))
    ctypes.windll.kernel32.CloseHandle(handle)
    if not res:
        return None
    return count.value

print(get_handle_count(3332))  # podaj PID