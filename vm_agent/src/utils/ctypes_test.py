import ctypes
from ctypes import wintypes
import logging

# Konstały NT
ProcessTelemetryIdInformation = 64
STATUS_SUCCESS = 0

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

class _PROCESS_TELEMETRY_ID_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("HeaderSize", wintypes.ULONG),
        ("ProcessId", wintypes.ULONG),
        ("ProcessStartKey", ctypes.c_uint64),
        ("CreateTime", ctypes.c_uint64),
        ("CreateInterruptTime", ctypes.c_uint64),
        ("CreateUnbiasedInterruptTime", ctypes.c_uint64),
        ("ProcessSequenceNumber", ctypes.c_uint64),
        ("SessionCreateTime", ctypes.c_uint64),
        ("SessionId", wintypes.ULONG),
        ("BootId", wintypes.ULONG),
        ("ImageChecksum", wintypes.ULONG),
        ("ImageTimeDateStamp", wintypes.ULONG),
        ("UserSidOffset", wintypes.ULONG),
        ("ImagePathOffset", wintypes.ULONG),
        ("PackageNameOffset", wintypes.ULONG),
        ("RelativeAppNameOffset", wintypes.ULONG),
        ("CommandLineOffset", wintypes.ULONG),
    ]

def get_process_details(pid: int):
    # 1. Musimy otworzyć proces
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000 # Czasem wystarczy do telemetrii
    hProc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    kernel32.LSALogonUser()
    if not hProc:
        return None

    try:
        # 2. ALOKACJA BUFORA
        # Ta struktura ma zmienną długość. Offsety wskazują na dane PO strukturze.
        # Alokujemy np. 4KB, żeby zmieścić strukturę + stringi (ścieżkę, komendę)
        buffer_size = 4096
        buffer = ctypes.create_string_buffer(buffer_size)
        
        # Rzutujemy początek bufora na naszą strukturę
        pbi = ctypes.cast(buffer, ctypes.POINTER(_PROCESS_TELEMETRY_ID_INFORMATION)).contents
        pbi.HeaderSize = ctypes.sizeof(_PROCESS_TELEMETRY_ID_INFORMATION)

        return_length = wintypes.ULONG()
        
        status = ntdll.NtQueryInformationProcess(
            hProc, 
            ProcessTelemetryIdInformation, 
            ctypes.byref(buffer), 
            buffer_size, 
            ctypes.byref(return_length)
        )

        if status == STATUS_SUCCESS:
            # 3. CZYTANIE STRINGÓW PRZEZ OFFSETY
            # CommandLineOffset to liczba bajtów od początku bufora do stringa (WideChar - UTF16)
            def get_string_at_offset(offset):
                if offset == 0: return ""
                # Ustawiamy wskaźnik na początek stringa w buforze
                ptr = ctypes.addressof(buffer) + offset
                # Windows zwraca tam zazwyczaj PWSTR (null-terminated UTF-16)
                return ctypes.wstring_at(ptr)
            
            user_sid = get_string_at_offset(pbi.UserSidOffset)
            cmd_line = get_string_at_offset(pbi.CommandLineOffset)
            image_path = get_string_at_offset(pbi.ImagePathOffset)
            package_name = get_string_at_offset(pbi.PackageNameOffset)
            relative_app_name = get_string_at_offset(pbi.RelativeAppNameOffset)


            print(f"PID: {pid} | Session: {pbi.SessionId}")
            print(f"StartKey: {pbi.ProcessStartKey}")
            print(f"Path: {image_path}")
            print(f"Cmd: {cmd_line}")
            print(f"Package: {package_name}")
            print(f"RelativeAppName: {relative_app_name}")
            print(f"User SID: {user_sid}")
            
            return cmd_line
        else:
            print(f"NTSTATUS Error: {hex(status & 0xffffffff)}")
            
    finally:
        # KLUCZOWE: Zamykamy uchwyt, żeby nie było wycieku (to o czym pisaliśmy!)
        kernel32.CloseHandle(hProc)

get_process_details(15708)