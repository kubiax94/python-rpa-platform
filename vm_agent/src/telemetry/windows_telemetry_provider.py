import logging
import time
import os
import ctypes
import json
import platform
import shlex
import shutil
import socket
import struct
import urllib.error
import urllib.request
import winreg
from ctypes import wintypes
from typing import Optional

import win32api

from vm_agent.src.telemetry.Itelemetry_provider import ITelemetryProvider
from vm_agent.src.telemetry.process_info import CpuHistory, ProcessInfo, ProcessTelemetry

ProcessTelemetryIdInformation = 64
STATUS_SUCCESS = 0

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)

ConvertSidToStringSidW = advapi32.ConvertSidToStringSidW
ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
ConvertSidToStringSidW.restype = wintypes.BOOL

GetProcessHandleCount = kernel32.GetProcessHandleCount
GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
GetProcessHandleCount.restype = wintypes.BOOL

GetProcessIoCounters = kernel32.GetProcessIoCounters

GlobalMemoryStatusEx = kernel32.GlobalMemoryStatusEx
GetTickCount64 = kernel32.GetTickCount64
GetSystemTimes = kernel32.GetSystemTimes

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]

GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]
GlobalMemoryStatusEx.restype = wintypes.BOOL
GetTickCount64.restype = ctypes.c_ulonglong
GetSystemTimes.argtypes = [
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
    ctypes.POINTER(wintypes.FILETIME),
]
GetSystemTimes.restype = wintypes.BOOL
GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IO_COUNTERS)]
GetProcessIoCounters.restype = wintypes.BOOL

GetIfTable = iphlpapi.GetIfTable
GetIfTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.ULONG), wintypes.BOOL]
GetIfTable.restype = wintypes.DWORD

NtQuerySystemInformation = ntdll.NtQuerySystemInformation
NtQuerySystemInformation.argtypes = [
    wintypes.ULONG,
    ctypes.c_void_p,
    wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]
NtQuerySystemInformation.restype = ctypes.c_long

ERROR_INSUFFICIENT_BUFFER = 122
IF_TYPE_SOFTWARE_LOOPBACK = 24
SYSTEM_PERFORMANCE_INFORMATION_CLASS = 2

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

class PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("ExitStatus", ctypes.c_long),
        ("PebBaseAddress", ctypes.c_void_p),
        ("AffinityMask", ctypes.c_size_t), # c_size_t dopasowuje się do 32/64 bit
        ("BasePriority", ctypes.c_long),
        ("UniqueProcessId", ctypes.c_size_t),
        ("InheritedFromUniqueProcessId", ctypes.c_size_t),
    ]

class UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_void_p),
    ]

class MIB_IFROW(ctypes.Structure):
    _fields_ = [
        ("wszName", wintypes.WCHAR * 257),
        ("_padding", wintypes.USHORT),
        ("dwIndex", wintypes.DWORD),
        ("dwMtu", wintypes.DWORD),
        ("dwSpeed", wintypes.DWORD),
        ("dwPhysAddrLen", wintypes.DWORD),
        ("bPhysAddr", ctypes.c_ubyte * 8),
        ("dwAdminStatus", wintypes.DWORD),
        ("dwOperStatus", wintypes.DWORD),
        ("dwLastChange", wintypes.DWORD),
        ("dwInOctets", wintypes.DWORD),
        ("dwInUcastPkts", wintypes.DWORD),
        ("dwInNUcastPkts", wintypes.DWORD),
        ("dwInDiscards", wintypes.DWORD),
        ("dwInErrors", wintypes.DWORD),
        ("dwInUnknownProtos", wintypes.DWORD),
        ("dwOutOctets", wintypes.DWORD),
        ("dwOutUcastPkts", wintypes.DWORD),
        ("dwOutNUcastPkts", wintypes.DWORD),
        ("dwOutDiscards", wintypes.DWORD),
        ("dwOutErrors", wintypes.DWORD),
        ("dwOutQLen", wintypes.DWORD),
        ("dwDescrLen", wintypes.DWORD),
        ("bDescr", ctypes.c_ubyte * 256),
    ]

FILTER_INTERFACE_MARKERS = (
    "-WFP Native MAC Layer LightWeight Filter-",
    "-Npcap Packet Driver (NPCAP)-",
    "-VirtualBox NDIS Light-Weight Filter-",
    "-QoS Packet Scheduler-",
    "-WFP 802.3 MAC Layer LightWeight Filter-",
)

# Flagi dostępu do RPM
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

import win32process # Dla GetProcessMemoryInfo i GetProcessHandleCount

class WindowsTelemetryProvider(ITelemetryProvider):
    def __init__(self):
        self.ntdll = ctypes.WinDLL("ntdll")
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.buffer = ctypes.create_string_buffer(8192) # Zwiększamy bufor dla pewności
        self.cpu_count = os.cpu_count() or 1
        self.tick_to_s = 1 / 10_000_000
        self._drive_map = self._build_drive_map()
        self._system_snapshot_cache: dict = {}
        self._system_snapshot_cache_expiry = 0.0
        self._system_snapshot_ttl = 60.0
        self._system_cpu_prev: Optional[dict[str, int]] = None
        self._system_io_prev: Optional[dict[str, float]] = None

        self.kernel32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE,   # hProcess
            ctypes.c_void_p,   # lpBaseAddress (TUTAJ BYŁ BŁĄD - to musi być c_void_p)
            ctypes.c_void_p,   # lpBuffer
            ctypes.c_size_t,   # nSize
            ctypes.POINTER(ctypes.c_size_t) # lpNumberOfBytesRead
        ]
        self.kernel32.ReadProcessMemory.restype = wintypes.BOOL

        self.ntdll.NtQueryInformationProcess.argtypes = [
            wintypes.HANDLE,   # hProcess
            ctypes.c_int,      # ProcessInformationClass
            ctypes.c_void_p,   # ProcessInformation
            wintypes.ULONG,    # ProcessInformationLength
            ctypes.POINTER(wintypes.ULONG) # ReturnLength
        ]

        self.ntdll.NtQueryInformationProcess.restype = ctypes.c_long 
    def _get_total_ram_bytes(self) -> int:
        memory_status = MEMORYSTATUSEX()
        memory_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if GlobalMemoryStatusEx(ctypes.byref(memory_status)):
            return int(memory_status.ullTotalPhys)
        return 0

    def _get_uptime_seconds(self) -> int:
        try:
            return int(GetTickCount64() / 1000)
        except Exception:
            return 0

    def _get_cpu_model(self) -> str:
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as cpu_key:
                cpu_name, _ = winreg.QueryValueEx(cpu_key, "ProcessorNameString")
                return str(cpu_name).strip()
        except OSError:
            return ""

    def _get_disk_metrics(self) -> tuple[int, int, str]:
        system_drive = os.environ.get("SystemDrive", "C:")
        try:
            usage = shutil.disk_usage(f"{system_drive}\\")
            return int(usage.total), int(usage.free), system_drive
        except OSError:
            return 0, 0, system_drive

    def _fetch_json(self, url: str, headers: Optional[dict[str, str]] = None, timeout: float = 1.5) -> Optional[dict]:
        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
                return payload if isinstance(payload, dict) else None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            logging.debug(f"Failed to fetch telemetry metadata from {url}: {exc}")
            return None

    def _get_azure_instance_metadata(self) -> dict:
        metadata = self._fetch_json(
            "http://169.254.169.254/metadata/instance?api-version=2021-02-01&format=json",
            headers={"Metadata": "true"},
        )
        if not metadata:
            return {"is_azure": False}

        compute = metadata.get("compute") or {}
        network = metadata.get("network") or {}
        interfaces = network.get("interface") or []
        primary_interface = interfaces[0] if interfaces else {}
        ipv4 = primary_interface.get("ipv4") or {}
        ip_addresses = ipv4.get("ipAddress") or []
        primary_ip = ip_addresses[0] if ip_addresses else {}

        return {
            "is_azure": True,
            "azure_vm_name": compute.get("name") or "",
            "azure_vm_size": compute.get("vmSize") or "",
            "azure_location": compute.get("location") or "",
            "azure_resource_group": compute.get("resourceGroupName") or "",
            "azure_subscription_id": compute.get("subscriptionId") or "",
            "azure_zone": compute.get("zone") or "",
            "azure_offer": compute.get("offer") or "",
            "azure_sku": compute.get("sku") or "",
            "azure_private_ip": primary_ip.get("privateIpAddress") or "",
            "azure_public_ip": primary_ip.get("publicIpAddress") or "",
        }

    def _get_azure_maintenance(self, is_azure: bool) -> dict:
        if not is_azure:
            return {"maintenance_summary": "Non-Azure host"}

        scheduled_events = self._fetch_json(
            "http://169.254.169.254/metadata/scheduledevents?api-version=2020-07-01",
            headers={"Metadata": "true"},
        )
        if scheduled_events is None:
            return {"maintenance_summary": "Unavailable"}

        events = scheduled_events.get("Events") or []
        if not events:
            return {
                "maintenance_state": "Clear",
                "maintenance_summary": "No scheduled events",
            }

        first_event = events[0]
        event_type = first_event.get("EventType") or "Maintenance"
        event_status = first_event.get("EventStatus") or "Scheduled"
        not_before = first_event.get("NotBefore") or ""
        resources = first_event.get("Resources") or []
        resource_hint = ""
        if resources:
            preview = ", ".join(str(resource) for resource in resources[:2])
            resource_hint = f" on {preview}"
            if len(resources) > 2:
                resource_hint += f" (+{len(resources) - 2} more)"

        summary = f"{event_type} {event_status}".strip()
        if not_before:
            summary = f"{summary} at {not_before}"
        if resource_hint:
            summary = f"{summary}{resource_hint}"
        if len(events) > 1:
            summary = f"{summary} (+{len(events) - 1} more events)"

        return {
            "maintenance_state": event_status,
            "maintenance_event_type": event_type,
            "maintenance_not_before": not_before,
            "maintenance_summary": summary,
        }

    def _refresh_system_snapshot(self) -> None:
        total_disk_bytes, free_disk_bytes, system_drive = self._get_disk_metrics()
        azure_instance = self._get_azure_instance_metadata()
        maintenance = self._get_azure_maintenance(bool(azure_instance.get("is_azure")))

        self._system_snapshot_cache = {
            "hostname": socket.gethostname(),
            "os_name": platform.system(),
            "os_version": platform.release(),
            "os_build": platform.version(),
            "cpu_model": self._get_cpu_model(),
            "logical_cores": self.cpu_count,
            "total_ram_bytes": self._get_total_ram_bytes(),
            "system_drive": system_drive,
            "disk_total_bytes": total_disk_bytes,
            "disk_free_bytes": free_disk_bytes,
            **azure_instance,
            **maintenance,
        }
        self._system_snapshot_cache_expiry = time.monotonic() + self._system_snapshot_ttl

    def _filetime_to_int(self, value: wintypes.FILETIME) -> int:
        return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)

    def _get_system_cpu_usage(self) -> float:
        idle_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()

        if not GetSystemTimes(ctypes.byref(idle_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return 0.0

        current = {
            "idle": self._filetime_to_int(idle_time),
            "kernel": self._filetime_to_int(kernel_time),
            "user": self._filetime_to_int(user_time),
        }

        if not self._system_cpu_prev:
            self._system_cpu_prev = current
            return 0.0

        idle_delta = current["idle"] - self._system_cpu_prev["idle"]
        kernel_delta = current["kernel"] - self._system_cpu_prev["kernel"]
        user_delta = current["user"] - self._system_cpu_prev["user"]
        total_delta = kernel_delta + user_delta
        busy_delta = total_delta - idle_delta
        self._system_cpu_prev = current

        if total_delta <= 0:
            return 0.0

        return max((busy_delta / total_delta) * 100.0, 0.0)

    def _read_system_disk_counters(self) -> tuple[int, int]:
        buffer = ctypes.create_string_buffer(4096)
        return_length = wintypes.ULONG(0)
        status = NtQuerySystemInformation(
            SYSTEM_PERFORMANCE_INFORMATION_CLASS,
            buffer,
            len(buffer),
            ctypes.byref(return_length),
        )
        if status != STATUS_SUCCESS:
            raise OSError(f"NtQuerySystemInformation failed with status {status}")

        read_bytes, write_bytes = struct.unpack_from("<4q", buffer.raw, 0)[1:3]
        return max(int(read_bytes), 0), max(int(write_bytes), 0)

    def _read_network_counters(self) -> tuple[int, int]:
        buffer_size = wintypes.ULONG(0)
        status = GetIfTable(None, ctypes.byref(buffer_size), False)
        if status not in (STATUS_SUCCESS, ERROR_INSUFFICIENT_BUFFER):
            raise OSError(f"GetIfTable size query failed with status {status}")

        buffer = ctypes.create_string_buffer(buffer_size.value)
        status = GetIfTable(buffer, ctypes.byref(buffer_size), False)
        if status != STATUS_SUCCESS:
            raise OSError(f"GetIfTable failed with status {status}")

        num_entries = struct.unpack_from("<I", buffer.raw, 0)[0]
        row_size = ctypes.sizeof(MIB_IFROW)
        offset = ctypes.sizeof(wintypes.DWORD)
        per_adapter_totals: dict[str, tuple[int, int]] = {}

        for index in range(num_entries):
            row = MIB_IFROW.from_buffer_copy(buffer.raw, offset + (index * row_size))
            if row.dwOperStatus not in (4, 5):
                continue

            description = bytes(row.bDescr[:row.dwDescrLen]).decode(errors="ignore").rstrip("\x00")
            if description.startswith("Software Loopback Interface"):
                continue

            normalized_description = description
            for marker in FILTER_INTERFACE_MARKERS:
                if marker in normalized_description:
                    normalized_description = normalized_description.split(marker, 1)[0]
                    break

            current_in = int(row.dwInOctets)
            current_out = int(row.dwOutOctets)
            previous = per_adapter_totals.get(normalized_description)
            if previous is None:
                per_adapter_totals[normalized_description] = (current_in, current_out)
            else:
                per_adapter_totals[normalized_description] = (
                    max(previous[0], current_in),
                    max(previous[1], current_out),
                )

        total_in = sum(adapter[0] for adapter in per_adapter_totals.values())
        total_out = sum(adapter[1] for adapter in per_adapter_totals.values())

        return total_in, total_out

    def _get_system_io_metrics(self) -> dict:
        current_timestamp = time.monotonic()

        try:
            disk_read_bytes, disk_write_bytes = self._read_system_disk_counters()
        except Exception as exc:
            logging.debug(f"Failed to read disk IO counters: {exc}")
            disk_read_bytes, disk_write_bytes = 0, 0

        try:
            network_recv_bytes, network_sent_bytes = self._read_network_counters()
        except Exception as exc:
            logging.debug(f"Failed to read network counters: {exc}")
            network_recv_bytes, network_sent_bytes = 0, 0

        metrics = {
            "disk_read_bps": 0.0,
            "disk_write_bps": 0.0,
            "network_recv_bps": 0.0,
            "network_sent_bps": 0.0,
        }

        if self._system_io_prev:
            delta_time = current_timestamp - self._system_io_prev["timestamp"]
            if delta_time > 0:
                metrics["disk_read_bps"] = max((disk_read_bytes - self._system_io_prev["disk_read_bytes"]) / delta_time, 0.0)
                metrics["disk_write_bps"] = max((disk_write_bytes - self._system_io_prev["disk_write_bytes"]) / delta_time, 0.0)

                network_in_delta = network_recv_bytes - self._system_io_prev["network_recv_bytes"]
                network_out_delta = network_sent_bytes - self._system_io_prev["network_sent_bytes"]
                if network_in_delta < 0:
                    network_in_delta += 2 ** 32
                if network_out_delta < 0:
                    network_out_delta += 2 ** 32

                metrics["network_recv_bps"] = max(network_in_delta / delta_time, 0.0)
                metrics["network_sent_bps"] = max(network_out_delta / delta_time, 0.0)

        self._system_io_prev = {
            "timestamp": current_timestamp,
            "disk_read_bytes": float(disk_read_bytes),
            "disk_write_bytes": float(disk_write_bytes),
            "network_recv_bytes": float(network_recv_bytes),
            "network_sent_bytes": float(network_sent_bytes),
        }

        return {key: round(value, 2) for key, value in metrics.items()}

    def _get_string_at_offset(self, offset: int) -> str:
        if offset == 0: return ""
        ptr = ctypes.addressof(self.buffer) + offset
        return ctypes.wstring_at(ptr)
    
    def _get_sid_at_offset(self, offset: int):
        if offset == 0: return "N/A"
        
        sid_ptr = ctypes.addressof(self.buffer) + offset
        
        string_sid = wintypes.LPWSTR()
        
        if ConvertSidToStringSidW(sid_ptr, ctypes.byref(string_sid)):
            result = string_sid.value  # Pobierz wartość stringa
            kernel32.LocalFree(string_sid)  # ZWOLNIJ PAMIĘĆ (Windows alokuje ją dla nas)
            return result
        return "Error converting SID"

    def _get_handle_count(self, hProcess: int) -> int:
        count = wintypes.DWORD()
        if self.kernel32.GetProcessHandleCount(hProcess, ctypes.byref(count)):
            return count.value
        return 0

    def _get_process_io_counters(self, hProcess: int, cpu_history: Optional[CpuHistory], delta_time: float) -> dict[str, float | int]:
        counters = IO_COUNTERS()
        if not GetProcessIoCounters(hProcess, ctypes.byref(counters)):
            return {
                "read_bytes": 0,
                "write_bytes": 0,
                "other_bytes": 0,
                "read_bps": 0.0,
                "write_bps": 0.0,
                "other_bps": 0.0,
            }

        read_bytes = int(counters.ReadTransferCount)
        write_bytes = int(counters.WriteTransferCount)
        other_bytes = int(counters.OtherTransferCount)
        read_bps = 0.0
        write_bps = 0.0
        other_bps = 0.0

        if cpu_history and cpu_history.last_timestamp > 0 and delta_time > 0:
            read_bps = max((read_bytes - cpu_history.last_io_read_bytes) / delta_time, 0.0)
            write_bps = max((write_bytes - cpu_history.last_io_write_bytes) / delta_time, 0.0)
            other_bps = max((other_bytes - cpu_history.last_io_other_bytes) / delta_time, 0.0)

        if cpu_history:
            cpu_history.last_io_read_bytes = read_bytes
            cpu_history.last_io_write_bytes = write_bytes
            cpu_history.last_io_other_bytes = other_bytes

        return {
            "read_bytes": read_bytes,
            "write_bytes": write_bytes,
            "other_bytes": other_bytes,
            "read_bps": round(read_bps, 2),
            "write_bps": round(write_bps, 2),
            "other_bps": round(other_bps, 2),
        }

    def _read_remote_unicode(self, hProcess: int, address: int) -> str:
        """Czyta UNICODE_STRING z pamięci innego procesu (dla CWD)"""
        try:
            u_str = UNICODE_STRING()
            self.kernel32.ReadProcessMemory(hProcess, address, ctypes.byref(u_str), ctypes.sizeof(u_str), None)
            if u_str.Length > 0:
                buf = ctypes.create_unicode_buffer(u_str.Length // 2)
                self.kernel32.ReadProcessMemory(hProcess, u_str.Buffer, buf, u_str.Length, None)
                return buf.value
        except: pass
        return ""
   
    def _build_drive_map(self) -> dict:
        """Buduje mapę \\Device\\HarddiskVolumeX -> C:, D:, itd."""
        drive_map = {}
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            drive = f"{letter}:"
            try:
                device_path = win32api.QueryDosDevice(drive)
                if device_path:
                    drive_map[device_path[0].lower()] = drive
            except:
                continue
        return drive_map

    def _resolve_device_path(self, path: str) -> str:
        """Konwertuje \\Device\\HarddiskVolumeX\\... na C:\\..."""
        if not path:
            return path
        path_lower = path.lower()
        for device, drive in self._drive_map.items():
            if path_lower.startswith(device.lower()):
                return drive + path[len(device):]
        return path
   
    def get_info(self, hProcess: int) -> Optional[ProcessInfo]:
        """Zbiera dane statyczne (ImagePath, Args, User, CWD, PPID)"""
        info = ProcessInfo()
        
        # 1. PPID i PEB Address (Class 0)
        pbi = PROCESS_BASIC_INFORMATION()
        if self.ntdll.NtQueryInformationProcess(hProcess, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), None) == 0:
            info.ppid = pbi.InheritedFromUniqueProcessId
            peb_addr = pbi.PebBaseAddress

            # 2. CWD z PEB (wymaga ReadProcessMemory)
            # Offsety x64: PEB->ProcessParameters (0x20), Params->CurrentDirectory (0x38)
            ptr_size = ctypes.sizeof(ctypes.c_void_p)
            params_ptr = ctypes.c_void_p()
            self.kernel32.ReadProcessMemory(hProcess, ctypes.c_void_p(peb_addr + 0x20), ctypes.byref(params_ptr), ptr_size, None)
            info.cwd = self._resolve_device_path(self._read_remote_unicode(hProcess, params_ptr.value + 0x38))

        # 3. Telemetry ID (Class 64) dla Path, Args, SID, SessionID
        pbi_tel = ctypes.cast(self.buffer, ctypes.POINTER(_PROCESS_TELEMETRY_ID_INFORMATION)).contents
        pbi_tel.HeaderSize = ctypes.sizeof(_PROCESS_TELEMETRY_ID_INFORMATION)
        
        status = self.ntdll.NtQueryInformationProcess(hProcess, 64, ctypes.byref(self.buffer), ctypes.sizeof(self.buffer), None)
        if status == 0:
            info.pid = pbi_tel.ProcessId
            info.sessionid = pbi_tel.SessionId
            raw_image_path = self._get_string_at_offset(pbi_tel.ImagePathOffset)
            info.image_path = self._resolve_device_path(raw_image_path)
            info.exe = os.path.basename(info.image_path) if info.image_path else "unknown"
            cmd = self._get_string_at_offset(pbi_tel.CommandLineOffset)

            if cmd:
                parts = shlex.split(cmd, posix=False)
                info.cmd = cmd
                raw_exe = parts[0].strip('"') if parts else ""
                info.exe_path = os.path.dirname(raw_exe)
                info.exe = os.path.basename(raw_exe)  # ← dodaj to!
                info.args = " ".join(parts[1:]).strip('"') if len(parts) > 1 else ""
            else:
                info.exe_path = ""
                info.args = ""

            logging.info(f"TELEMETRY: image_path='{info.image_path}', exe_path='{info.exe_path}', exe='{info.exe}', args='{info.args}'")

            info.user = self._get_sid_at_offset(pbi_tel.UserSidOffset)
            info.creation_time = pbi_tel.CreateTime * self.tick_to_s

        return info

    def get_telemetry(self, hProcess: int, cpu_history: Optional[CpuHistory]) -> Optional[ProcessTelemetry]:
        """Zbiera dane dynamiczne (CPU, RAM, Handles, ExitCode)"""
        # 1. CPU Usage
        creation_time, exit_time, kernel_time, user_time = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
        if not self.kernel32.GetProcessTimes(hProcess, ctypes.byref(creation_time), ctypes.byref(exit_time), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return None

        current_cpu_time = kernel_time.value + user_time.value
        current_ts = time.perf_counter()
        cpu_p = 0.0
        delta_time = 0.0

        if cpu_history and cpu_history.last_timestamp > 0:
            d_cpu = current_cpu_time - cpu_history.last_cpu_time
            delta_time = current_ts - cpu_history.last_timestamp
            if delta_time > 0:
                cpu_p = (d_cpu * self.tick_to_s / delta_time) / self.cpu_count * 100.0

        io_counters = self._get_process_io_counters(hProcess, cpu_history, delta_time)

        if cpu_history:
            cpu_history.last_cpu_time = current_cpu_time
            cpu_history.last_timestamp = current_ts

        # 2. RAM & Handles (używając win32process dla wygody, bo i tak mamy uchwyt)
        try:
            mem = win32process.GetProcessMemoryInfo(hProcess)
            h_count = self._get_handle_count(hProcess)
            exit_code = win32process.GetExitCodeProcess(hProcess)
        except:
            mem = {"WorkingSetSize": 0, "PagefileUsage": 0}
            h_count = 0
            exit_code = 0

        return ProcessTelemetry(
            pid=0, # wypełni AbstractProcess
            cpu_usage=round(cpu_p, 2),
            working_set=mem["WorkingSetSize"],
            private_bytes=mem["PagefileUsage"],
            handle_count=h_count,
            exit_code=exit_code,
            io_counters=io_counters,
        )

    def get_system_metrics(self) -> dict:
        cpu_usage = self._get_system_cpu_usage()
        io_metrics = self._get_system_io_metrics()

        if time.monotonic() >= self._system_snapshot_cache_expiry:
            self._refresh_system_snapshot()

        return {
            "cpu_usage": round(max(cpu_usage, 0.0), 2),
            "uptime_seconds": self._get_uptime_seconds(),
            **io_metrics,
            **self._system_snapshot_cache,
        }

    def get_full_info(self, hProcess: int, cpu_history: CpuHistory) -> tuple[ProcessInfo, ProcessTelemetry]:
        info = self.get_info(hProcess)
        telemetry = self.get_telemetry(hProcess, cpu_history)
        return info, telemetry
    