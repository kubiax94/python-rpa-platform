#         Args:
#             exe: Executable path (e.g., "notepad.exe" or "C:\\app\\robot.exe")
#             args: Command-line arguments
#             cwd: Working directory (default: exe directory)
#             visible: Show window (True) or hide (False)

from __future__ import annotations
from datetime import datetime
from enum import Enum
import os
import random
import time
from typing import TYPE_CHECKING, Optional, Tuple

import win32api
import win32com.client
import win32con
import win32process
import win32event

import logging
from vm_agent.src.core.clock import Clock
from vm_agent.src.core.ilifecycle import ILifeCycle
from vm_agent.src.telemetry.Itelemetry_provider import ITelemetryProvider
from vm_agent.src.telemetry.process_info import CpuHistory, ProcessInfo, ProcessTelemetry
from vm_agent.src.utils.proces_get_cmd_line import get_command_line
from vm_agent.src.utils.process_creation_date import get_process_creation_date

if TYPE_CHECKING:
    from vm_agent.src.core.iprocess_manager import IProcessManager

# https://learn.microsoft.com/pl-pl/windows/win32/debug/system-error-codes--0-499-
class ProcessStatus(Enum):
    UKNOWN = -1
    AccessDenied = 5
    Restarting = -9999
    Running = win32con.STILL_ACTIVE
    Success = 0
    Failed = 1
    FileNotFound = 2
    TimeOut = 1067
    AuthError = 128 #Github SSH Auth error code
    ERROR_BROKEN_PIPE = 109
    NOTEPAD_FILE_ERROR = 459998

INVERT_SEC_CHANGE = 1/10_000_000  # Convert 100-nanosecond intervals to seconds

class AbstractProcess(ILifeCycle):
    #Optimalization FIX, python dict is dynamic but we know all fields in advance, we can remove this behavior
    __slots__ = [
        "pid", "hProcess", "hThread", "_pid_change",
        "visible", "_status", "cpu_history", "telemetry", "_update_interval", "_next_update_logic_time",
        "_it_change", "_down_time", "_is_monitored", "tinfo", "_last_send_state", "pinfo"
    ]

    def __init__(self, exe: str, args: str, cwd: str, visible: bool, telemetry_provider: ITelemetryProvider = None):
        self.pid = None
        self._pid_change = False
        self.hProcess = None
        self.hThread = None

        self.cpu_history: CpuHistory = CpuHistory()
        self.telemetry = telemetry_provider
        self.pinfo: ProcessInfo = ProcessInfo(
            pid=None,
            exe= os.path.basename(exe),
            exe_path= os.path.dirname(exe),
            cmd=f'"{exe}" {args}'.strip() if args else f'"{exe}"',
            args=args,
            cwd= cwd if cwd != "" else os.path.dirname(exe)
            )
        self.tinfo: Optional[ProcessTelemetry] = None
        self._last_send_state: Optional[ProcessTelemetry] = None

        self.visible: bool = visible
        self._status: Optional[ProcessStatus] = None
        self._it_change: bool = False
        self._down_time: float = 0
        self._is_monitored: bool = False
        self._update_interval: int = 1  # seconds
        self._next_update_logic_time: int = Clock.get_time() + random.uniform(0, self._update_interval)

    #This should be change to provide only user context for exe
    def _resolve_exe_path(self, exe):
        # Szukaj w PATH, System32, itp.
        # Zwróć pełną ścieżkę lub exe jeśli nie znajdziesz
        for path in os.environ["PATH"].split(os.pathsep):
            candidate = os.path.join(path, exe)
            if os.path.exists(candidate):
                return candidate
        return exe
    
    def close(self):
        if self.hProcess:
            win32api.CloseHandle(self.hProcess)
            self.hProcess = None
        if self.hThread:
            win32api.CloseHandle(self.hThread)
            self.hThread = None

    # Lifecycle method 's
    # ---------------------------------------
    def on_start(self):

        if self.pid is None:
            logging.warning(f"Process {self.pinfo.exe} has no PID set on start")
            self.set_state(ProcessStatus.Failed)
            return
        
        if not self.hProcess:
            try:
                self.hProcess = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, self.pid)
            except Exception as e:
                if "Access is denied" in str(e) or getattr(e, 'winerror', None) == 5:
                    self._mark_access_denied()
                    self.set_state(ProcessStatus.AccessDenied)
                    logging.error(f"Access denied when opening process PID={self.pid} on start")
                    return
                
                logging.error(f"Failed to open process PID={self.pid} on start: {e}")
                self.hProcess = None
                self.set_state(ProcessStatus.Failed)
                return

        try:
            self.cpu_history = CpuHistory()
            [pinfo, tinfo] = self.telemetry.get_full_info(int(self.hProcess), self.cpu_history)
            self.pinfo = pinfo
            self.pinfo.pid = self.pid
            if not self.pinfo.cmd:
                self.pinfo.cmd = self.get_cmd()
            self.tinfo = tinfo
            self.set_state(ProcessStatus.Running)
            self._it_change = True
        except Exception as e:
            logging.warning(f"Failed to get full telemetry for process PID={self.pid} on start, using fallback payload: {e}")
            self.pinfo.pid = self.pid
            if not self.pinfo.cmd:
                self.pinfo.cmd = self.get_cmd()
            self._ensure_fallback_telemetry()
            self.set_state(ProcessStatus.Running if self.get_exit_code() == ProcessStatus.Running.value else ProcessStatus.Failed)
            return
    # Tick for each lifecycle tick, please do not use logger there for prod
    def on_tick(self):

        current_logic_time = Clock.get_time()
        self._it_change = False
        self._check_state()

        if (self._status == ProcessStatus.AccessDenied):
            self._it_change = False
            self._down_time += 1
            return
        
        if not self.is_running() and self._is_monitored:
            self._down_time += 1
            return
        
        if current_logic_time >= self._next_update_logic_time:
            logging.debug(f"Updating telemetry for process {self.pinfo.exe} (PID={self.pid}) on tick at {current_logic_time}s")
            try:
                new_data = self.telemetry.get_telemetry(int(self.hProcess), self.cpu_history)
            except Exception as e:
                logging.debug(f"Failed to refresh telemetry for PID={self.pid}: {e}")
                if self.tinfo is None:
                    self._ensure_fallback_telemetry()
                self._next_update_logic_time = current_logic_time + self._update_interval
                return

            self._next_update_logic_time = current_logic_time + self._update_interval

            if new_data is None:
                if self.tinfo is None:
                    self._ensure_fallback_telemetry()
                return

            if new_data != self._last_send_state:
                self.tinfo = new_data
                self._it_change = True
            
                
        logging.debug(f"Life cycle tick {self.pinfo.exe} process is {self.is_running()}")

    def on_stop(self):
        logging.info(f"Stopping life cycle for process {self}")
        self.close()
        logging.info(f"Life cycle for {self} stopped")
    
    def on_restart(self, process_manager: "IProcessManager") -> bool:
        if not self._is_monitored:
            logging.warning(f"Process {self} is not monitored, cannot restart")
            return False
        
        logging.info(f"Restarting process {self}")
        try:
            if self.pid:
                process_manager.stop_process(self.pid, force=True)

            process_manager.start_process(self)
            self._down_time = 0
            logging.info(f"Process {self} restarted successfully")
            return True
        except Exception as e:
            logging.error(f"Failed to restart process {self}: {e}")
            return False

    def get_name(self):
        return self.exe

    def is_healthy(self) -> bool:
        #Default behaviour check if in tick process is up and running
        return self.is_running()

    # ---------------------------------------

    @staticmethod
    def create(exe: str, args: str, cwd: str, visible: bool) -> "AbstractProcess":
        return AbstractProcess(exe, args, cwd, visible)

    def is_running(self) -> bool:
        return self._status == ProcessStatus.Running

    def is_monitored(self) -> bool:
        return self._is_monitored
    
    def get_exit_code(self):
        if self._status == ProcessStatus.AccessDenied:
            return ProcessStatus.AccessDenied
        if not self.hProcess:
            return ProcessStatus.Failed
        return win32process.GetExitCodeProcess(self.hProcess)

    def get_cmd(self):
        logging.info(f"get_cmd: image_path='{self.pinfo.image_path}', exe_path='{self.pinfo.exe_path}', exe='{self.pinfo.exe}', args='{self.pinfo.args}'")

        if self.pinfo.image_path and not self.pinfo.image_path.startswith("\\Device\\"):
            exe_full = self.pinfo.image_path
        elif self.pinfo.exe_path:
            exe_full = os.path.join(self.pinfo.exe_path, self.pinfo.exe)
        else:
            exe_full = self.pinfo.exe

        cmd = f'"{exe_full}"'
        args = self.pinfo.args or ""

        if args:
            cmd = f'{cmd} {args}'
        return cmd.strip()
    
    def get_startupinfo(self) -> win32process.STARTUPINFO:
        startup_info = win32process.STARTUPINFO()
        
        startup_info.lpDesktop = r"winsta0\default"

        if not self.visible:
            startup_info.dwFlags |= win32con.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = win32con.SW_HIDE
        return startup_info

    def requires_handle_inheritance(self) -> bool:
        return False

    def wait_and_exit(self) -> bool:
        if not self.is_running():
            return True
        rc = win32event.WaitForSingleObject(self.hProcess, self.proces_time_out)
        return rc == win32con.WAIT_OBJECT_0

    def _mark_access_denied(self):
        if not self.pinfo.exe:
            self.pinfo.exe = "<Unknown - Access Denied>"
        if not self.pinfo.exe_path:
            self.pinfo.exe_path = "<Unknown - Access Denied>"
        if not self.pinfo.user:
            self.pinfo.user = "unknown"

        self.tinfo = ProcessTelemetry(
            pid=self.pid or -1,
            cpu_usage=0.0,
            working_set=0,
            private_bytes=0,
            handle_count=0,
            exit_code=ProcessStatus.AccessDenied.value,
            io_counters={
                "read_bytes": 0,
                "write_bytes": 0,
                "other_bytes": 0,
                "read_bps": 0.0,
                "write_bps": 0.0,
                "other_bps": 0.0,
            },
        )
        self._it_change = True

    def _ensure_fallback_telemetry(self):
        if self.pid is None:
            return

        exit_code = None
        try:
            exit_code = self.get_exit_code()
        except Exception:
            if isinstance(self._status, ProcessStatus):
                exit_code = self._status.value

        self.tinfo = ProcessTelemetry(
            pid=self.pid,
            cpu_usage=self.tinfo.cpu_usage if self.tinfo else 0.0,
            working_set=self.tinfo.working_set if self.tinfo else 0,
            private_bytes=self.tinfo.private_bytes if self.tinfo else 0,
            handle_count=self.tinfo.handle_count if self.tinfo else 0,
            exit_code=exit_code,
            io_counters=self.tinfo.io_counters if self.tinfo and self.tinfo.io_counters else {
                "read_bytes": 0,
                "write_bytes": 0,
                "other_bytes": 0,
                "read_bps": 0.0,
                "write_bps": 0.0,
                "other_bps": 0.0,
            },
        )
        self._it_change = True

    def set_pid(self, pid: int):
        if self.pid == pid:
            return
        
        self.pid = pid
        self._it_change = True
        self._pid_change = True

        self.close()

    def _set_pid(self, pid: int):
        
        if self.pid == pid:
            return
        
        self.pid = pid
        self._it_change = True
        self._pid_change = True

        if self.hProcess:
            win32api.CloseHandle(self.hProcess)
            self.hProcess = None
        
        if self.hThread:
            win32api.CloseHandle(self.hThread)
            self.hThread = None
            

        try:
            self.hProcess = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)
            modules = win32process.EnumProcessModules(self.hProcess)
            exe_path = win32process.GetModuleFileNameEx(self.hProcess, modules[0]) if modules else "unknown"
            self.exe = exe_path.split(os.sep)[-1]
            self.exe_path = exe_path
            try:

                self.creation_date = get_process_creation_date(int(self.hProcess))
                self.args = get_command_line(int(self.hProcess)).replace(f'"{self.exe_path}"', '').strip()

                self.set_state(ProcessStatus.Running)

            except Exception as e:
                logging.error(f"WMI query failed for PID={pid}: {e}")
                self.args = ""

            logging.info(f"Process PID={pid} opened successfully: {self.exe} {self.args} {self.creation_date}")
        except Exception as e:
            if "Access is denied" in str(e) or getattr(e, 'winerror', None) == 5:
                self.pid = pid
                self._mark_access_denied()
                self.set_state(ProcessStatus.AccessDenied)
                self.args = "<Unknown - Access Denied>"
                self.exe = "<Unknown - Access Denied>"
                self.exe_path = "<Unknown - Access Denied>"
                self.hProcess = None
                self.hThread = None
                logging.error(f"Access denied when opening process PID={pid}")
                return 
            #this could be dead process in the moment of open was still alive
            logging.error(f"Failed to open process PID={pid}: {e}")
            self.hProcess = None
            self.set_state(ProcessStatus.Failed)
    
    def set_state(self, status: ProcessStatus):
        if self._status == status:
            return
        
        # Fix for access denied process
        if self._status == ProcessStatus.AccessDenied:
            self._it_change = False
            return

        self._it_change = True
        try:
            self._status = status
        except Exception as e:
            logging.warning(f"Failed to set process status for PID={self.pid}: {status} - {e}")
            self._status = ProcessStatus.UKNOWN

    def to_json(self) -> Optional[dict]:
        if self._it_change:
            return {
                "pid": self.pid,
                "exe": self.exe,
                "args": self.args,
                "cwd": self.cwd,
                "visible": self.visible,
                "is_running": self.is_running(),
                "memory_usage": self._last_memory_usage,
                "cpu_usage": self._last_cpu_usage,
                "exit_code": self.get_exit_code(),
            } 
        #ide to only ocnce report status
        elif self._status == ProcessStatus.AccessDenied and self._down_time == 1:
            return {
                "pid": self.pid,
                "exe": self.exe,
                "args": self.args,
                "cwd": self.cwd,
                "visible": self.visible,
                "is_running": self.is_running(),
                "memory_usage": self._last_memory_usage,
                "cpu_usage": self._last_cpu_usage,
                "exit_code": self.get_exit_code(),
            }
        else:
            return None

    def to_json_only_change(self, sync: bool = False) -> Optional[dict]:
        # Jeśli nie ma telemetrii lub nic się nie zmieniło i nie wymuszamy sync -> wyjdź
        if not self.tinfo:
            self._ensure_fallback_telemetry()
        if not self.tinfo:
            return None
        if not sync and not self._it_change:
            return None
        
        # Klucz główny zawsze wysyłamy
        delta = {"pid": self.pid}

        # 1. DANE STATYCZNE (wysyłane rzadko: start lub sync)
        if self._last_send_state is None or sync:
            delta.update({
                "exe": self.pinfo.exe,
                "exe_path": self.pinfo.exe_path,
                "args": self.pinfo.args,
                "cmd": self.pinfo.cmd,
                "cwd": self.pinfo.cwd,
                "user": self.pinfo.user,
                "ppid": self.pinfo.ppid,
                "sessionid": self.pinfo.sessionid,
                "creation_time": self.pinfo.creation_time,
                "is_monitored": self._is_monitored,
                "has_window": self.pinfo.has_window,
                "window_title": self.pinfo.window_title,
                "window_hwnd": self.pinfo.window_hwnd,
                "windows": self.pinfo.windows,
                "capture_target_pid": self.pinfo.capture_target_pid,
                "capture_target_kind": self.pinfo.capture_target_kind,
            })

        # 2. DANE DYNAMICZNE (Telemetria)
        # Jeśli to sync, ślemy wszystko. Jeśli delta, ślemy tylko zmiany.
        t = self.tinfo
        l = self._last_send_state

        if sync or l is None:
            delta.update({
                "cpu_usage": t.cpu_usage,
                "memory_usage": {
                    "working_set_size": t.working_set,
                    "private_bytes": t.private_bytes
                },
                "handle_count": t.handle_count,
                "io_counters": t.io_counters,
                "exit_code": t.exit_code,
                "is_running": self.is_running()
            })
        else:
            # Porównujemy pole po polu dla maksymalnej oszczędności pasma
            if t.cpu_usage != l.cpu_usage: delta["cpu_usage"] = t.cpu_usage
            if t.working_set != l.working_set or t.private_bytes != l.private_bytes:
                delta["memory_usage"] = {"working_set_size": t.working_set, "private_bytes": t.private_bytes}
            if t.handle_count != l.handle_count: delta["handle_count"] = t.handle_count
            if t.io_counters != l.io_counters: delta["io_counters"] = t.io_counters
            if t.exit_code != l.exit_code: delta["exit_code"] = t.exit_code
            
            # Zawsze warto wysłać stan zdrowia procesu w delcie
            delta["is_running"] = self.is_running()

        # Zapamiętaj stan jako ostatnio wysłany
        # Używamy copy, jeśli tinfo jest mutowalne, ale dataclass slots jest ok
        self._last_send_state = self.tinfo 
        
        return delta

    def _check_state(self):
        try:
            self.set_state(ProcessStatus(self.get_exit_code()))
        except Exception as e:
            logging.warning(f"Failed to check process state for PID={self.pid}: {e}")
            self.set_state(ProcessStatus.UKNOWN)
    def __repr__(self):
        return f"<AbstractProcess pid={self.pid} exe={self.pinfo.exe} args={self.pinfo.args} status={self._status}>"