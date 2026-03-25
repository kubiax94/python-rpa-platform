import ctypes
import datetime
import win32api

kernel32 = ctypes.windll.kernel32

creation_time = ctypes.c_ulonglong()

def get_process_creation_date(handle: int = None, pid: int = None) -> datetime.datetime:
    if handle is None:
        handle = kernel32.OpenProcess(0x0400, False, pid)
    
    if not handle:
        err = win32api.GetLastError()
        if err > 0:
            raise Exception(f"Failed to open process {pid}, error code: {err}")

    creation_time = ctypes.c_ulonglong()
    exit_time = ctypes.c_ulonglong()
    kernel_time = ctypes.c_ulonglong()
    user_time = ctypes.c_ulonglong()

    succ = kernel32.GetProcessTimes(
        handle,
        ctypes.byref(creation_time),
        ctypes.byref(exit_time),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time)
    )
    if pid is not None:
        kernel32.CloseHandle(handle)
    
    if not succ:
        err = win32api.GetLastError()
        if err > 0:
            raise Exception(f"Failed to get process times for {handle}, error code: {err}")

    start = datetime.datetime(1601, 1, 1) + datetime.timedelta(
        microseconds=creation_time.value // 10
    )
    
    return start

