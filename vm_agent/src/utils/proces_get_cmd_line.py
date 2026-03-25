import ctypes
from ctypes import wintypes
import win32api

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

# Flagi dostępu
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Reserved", ctypes.c_byte * 4), # Padding dla x64
        ("Buffer", ctypes.c_void_p),     # Używamy void_p, bo to adres w TAMTYM procesie
    ]

class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),  # <-- tu musi być c_void_p!
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("Reserved3", ctypes.c_void_p),
    ]

def get_command_line(hProc: int = None, pid: int = None) -> str:
    
    #hProc = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)

    if not hProc:
        raise Exception(f"Failed to open process {pid}, error code: {ctypes.get_last_error()}")

    try:
        # 1. Pobierz adres PEB
        pbi = PROCESS_BASIC_INFORMATION()
        succ =ntdll.NtQueryInformationProcess(hProc, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None)
        peb_addr = pbi.PebBaseAddress

        if succ != 0: 
            raise Exception(f"Failed to query process information for {hProc}, error code: {succ}")
        
        # 2. Odczytaj adres ProcessParameters z PEB
        # W x64 ProcessParameters jest pod offsetem 0x20 od początku PEB
        ptr_process_params = ctypes.c_void_p()
        succ = kernel32.ReadProcessMemory(hProc, ctypes.c_void_p(peb_addr + 0x20), ctypes.byref(ptr_process_params), 8, None)

        if not succ:
            err = win32api.GetLastError()
            if err > 0:
                raise Exception(f"Failed to read PEB for process {hProc}, error code: {err}")
            
        # 3. Odczytaj strukturę UNICODE_STRING CommandLine
        # W x64 CommandLine znajduje się pod offsetem 0x70 wewnątrz RTL_USER_PROCESS_PARAMETERS
        cmd_line_unicode = UNICODE_STRING()
        # Z c++ ReadProcesessMemory(int, void*, void*, size_t, size_t*)
        succ = kernel32.ReadProcessMemory(hProc, ctypes.c_void_p(ptr_process_params.value + 0x70), ctypes.byref(cmd_line_unicode), ctypes.sizeof(cmd_line_unicode), None)

        if not succ:
            err = win32api.GetLastError()
            if err > 0:
                raise Exception(f"Failed to read CommandLine for process {hProc}, error code: {err}")

        if cmd_line_unicode.Buffer is None:
            return ""

        # 4. Odczytaj faktyczny bufor tekstowy
        # Length jest w bajtach!
        buffer = ctypes.create_unicode_buffer(cmd_line_unicode.Length // 2)
        succ = kernel32.ReadProcessMemory(hProc, ctypes.c_void_p(cmd_line_unicode.Buffer), buffer, cmd_line_unicode.Length, None)

        if not succ:
            err = win32api.GetLastError()
            if err > 0:
                raise Exception(f"Failed to read CommandLine buffer for process {hProc}, error code: {err}")

        return str(buffer.value)

    finally:
        if pid is not None:
            kernel32.CloseHandle(hProc)