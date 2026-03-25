from __future__ import annotations
import os
import win32con
import win32event
import win32process
import logging
from typing import Dict, List, Optional

from vm_agent.src.core.abstract_proces import AbstractProcess, ProcessStatus
from vm_agent.src.core.ilifecycle import ILifeCycle
from vm_agent.src.core.iprocess_manager import IProcessManager
from vm_agent.src.telemetry.Itelemetry_provider import ITelemetryProvider

logger = logging.getLogger(__name__)

PIDS_FILE = r"C:\VmAgent\managed_pids.json"

class ProcessManager(ILifeCycle, IProcessManager):
    """
    Base class for managing processes.
    Handles process lifecycle: start, monitor, terminate.
    
    Subclasses must implement _create_process() to define how processes are started
    (e.g., CreateProcess vs CreateProcessAsUser).
    """
    
    def __init__(self, telemetry_provider: ITelemetryProvider = None):
        # PID → process info
        self._procs: Dict[int, AbstractProcess] = {}
        self.telemetry: ITelemetryProvider = telemetry_provider

    def _create_process(self, process: AbstractProcess) -> AbstractProcess:
        """
        Abstract method: creates a process (must be implemented by subclasses).
        
        Args:
            exe: Executable path
            cmd: Full command line (quoted exe + args)
            cwd: Working directory
            visible: Show window flag
        
        Returns:
            Tuple: (hProcess, hThread, pid, tid)
        
        Raises:
            NotImplementedError: If not overridden by subclass
        """
        raise NotImplementedError("Subclasses must implement _create_process()")
    
    def wait(self, pid: int, timeout_ms: int = 0) -> bool:
        """
        Waits for process to exit.
        
        Args:
            pid: Process ID
            timeout_ms: Timeout in milliseconds (0 = infinite)
        
        Returns:
            True if process exited, False if timeout
        """
        info = self._procs.get(pid)
        if not info:
            return True  # already exited or not found
        rc = win32event.WaitForSingleObject(info["hProcess"], timeout_ms)
        return rc == win32con.WAIT_OBJECT_0
    
    def get_exit_code(self, pid: int) -> Optional[int]:
        """
        Gets process exit code.
        
        Args:
            pid: Process ID
        
        Returns:
            Exit code or None if process not found
        """
        info = self._procs.get(pid)
        if not info:
            return None
        return win32process.GetExitCodeProcess(info["hProcess"])
    
    def terminate(self, pid: int, exit_code: int = 1) -> None:
        """
        Forcefully terminates a process.
        
        Args:
            pid: Process ID
            exit_code: Exit code to set (default: 1)
        """
        
        if not self._procs.get(pid):
            logger.warning(f"Cannot terminate PID={pid}: not found")
            return
        
        win32process.TerminateProcess(self._procs[pid].hProcess, exit_code)
        logger.info(f"Terminated PID={pid}")

    def try_restart_process(self, pid: int) -> bool:
        proces = self._procs.get(pid)
        if not proces or proces._is_monitored == False:
            logger.error(f"Cannot restart PID={pid}: not found")
            return False
        if proces.is_running():
            logger.info(f"Process PID={pid} is already running, no need to restart")
            return True
        
        try:
            logger.info(f"Restarting process PID={pid}: {proces.get_cmd()}")
            match_process = [proc for proc in self._procs.values() if proc.pinfo.exe == proces.pinfo.exe and proc.is_running()]
            logger.info(f"Found {len(match_process)} matching processes for restart check")
            for match in match_process:
                logger.info(f"Checking existing process {proces} for command match {match}")
                if match.pinfo.args == proces.pinfo.args and match.is_running():
                    logger.info(f"Process with same parameters already running as PID={match.pid}, skipping restart")
                    proces.set_pid(match.pid)
                    return True
            

            self.start_process(proces)
            proces._down_time = 0
            return True
        except Exception as e:
            logger.error(f"Failed to restart PID={pid}: {e}")
            return False

    def get_status(self, sync: bool = False) -> dict:
        """
        Gets status of all managed processes.
        
        Returns:
            Dict of PID → process info
        """
        status = {}
        for [pid, proces] in self._procs.items():
            data = proces.to_json_only_change(sync=sync)
            if data:
                status[pid] = data
            
        return status

    def close_all_processes(self) -> None:
        """
        Closes all managed processes.
        It tries to close process by it's logic lifecycle onclose method.
        This method should not close any abstract process classes that are monitored.
        This is using custom on_close method from AbstractProcess class.
        """
        for pid, proces in list(self._procs.items()):
            monitored_process = proces._is_monitored
            try:
                proces.on_stop()
                if not monitored_process:
                    self._procs.pop(pid)
            except Exception as e:
                logger.error(f"Failed to close {proces}: {e}")

        logger.info("All not monitored processes closed")

    #IProcessManager methods
    def rebind_process(self, old_pid: int, new_pid: int, proc: AbstractProcess) -> None:
        """
        Rebinds a process from old PID to new PID.
        
        Args:
            old_pid: Old Process ID
            new_pid: New Process ID
            proc: AbstractProcess instance
        """
        if old_pid in self._procs:
            self._procs.pop(old_pid)
        self._procs[new_pid] = proc
        logger.info(f"Rebound process from PID={old_pid} to PID={new_pid}")
        
    def get_process(self, pid: int) -> Optional[AbstractProcess]:
        """
        Gets a managed process by PID.
        
        Args:
            pid: Process ID
        
        Returns:
            AbstractProcess instance or None if not found
        """
        return self._procs.get(pid)

    def get_all_processes(self) -> List[AbstractProcess]:
        """
        Gets all managed processes.
        
        Returns:
            List of AbstractProcess instances
        """
        return list(self._procs.values())

    def find_process_by_exe(self, exe: str) -> List[AbstractProcess]:
        """
        Finds all managed processes by executable path.
        
        Args:
            exe: Executable path to search for
        
        Returns:
            List of AbstractProcess instances
        """
        matches = []
        for proces in self._procs.values():
            if proces.pinfo.exe.lower() == exe.lower():
                matches.append(proces)
        return matches

    def find_process_by_cmd(self, cmd_substr: str) -> List[AbstractProcess]:
        """
        Finds all managed processes by command substring.
        
        Args:
            cmd_substr: Substring to search in command line
        
        Returns:
            List of AbstractProcess instances
        """
        matches = []
        for proces in self._procs.values():
            if cmd_substr.lower() in proces.get_cmd().lower():
                matches.append(proces)
        return matches
    
    def find_process_by_ppid(self, ppid: int) -> List[AbstractProcess]:
        """
        Finds all managed processes by parent PID.
        
        Args:
            ppid: Parent Process ID to search for
        
        Returns:
            List of AbstractProcess instances
        """
        matches = []
        for proces in self._procs.values():
            if proces.pinfo.ppid == ppid:
                matches.append(proces)
        return matches

    def start_process(self, proc: AbstractProcess) -> AbstractProcess:
        """
        Starts a process.
        
        Args:
            exe: Executable path (e.g., "notepad.exe" or "C:\\app\\robot.exe")
            args: Command-line arguments
            cwd: Working directory (default: exe directory)
            visible: Show window (True) or hide (False)
        
        Returns:
            Process ID (PID)
        
        Raises:
            Exception: If process creation fails
        """
        logger.info(f"Starting process: {proc.pinfo.exe} {proc.pinfo.args}")
        
        # TODO: Implementation of checking existing processes with same exe and args
        if proc.pinfo.cwd is None:
            proc.pinfo.cwd = os.path.dirname(proc.pinfo.exe) or None
        
        # Delegate to subclass implementation
        self._create_process(proc)
        self._procs[proc.pid] = proc
        proc.on_start()
        logger.info(f"Started PID={proc.pid}: {proc.get_cmd()}")
        return proc

    def stop_process(self, pid: int, force: bool = False) -> bool:
        """
        Stops a managed process.
        
        Args:
            pid: Process ID
            force: Force termination if True, only release resources and remove instance from loop if False
        
        Returns:
            True if process was stopped, False if not found
        """
        proces = self._procs.get(pid)
        if not proces:
            logger.warning(f"Cannot stop PID={pid}: not found")
            return False
        
        if force and proces.is_running():
            self.terminate(pid)
        else:
            proces.on_stop()
        
        self._procs.pop(pid)
        logger.info(f"Stopped PID={pid}")
        return True

    # Life Cycle methods
    def on_start(self):
        for pid, proces in list(self._procs.items()):
            if not proces.is_running() and not proces._is_monitored:
                proces.on_start()
            elif not proces.is_running() and proces._is_monitored:
                logger.info(f"Process PID={pid} is not running, attempting restart")
                self.try_restart_process(pid)
        
    def on_tick(self):  
        for proces in list(self._procs.values()):
            if not proces:
                continue
    
            if proces._status == ProcessStatus.AccessDenied:
                proces.on_tick()
                # For cleanup, remove processes that have been down for over 60 seconds
                if proces._down_time > 60:
                    proces.on_stop()
                    self._procs.pop(proces.pid, None) # None for saftey
                continue

            proces.on_tick()

            if proces.pid not in self._procs:
                continue

            if not proces.is_running() and not proces._is_monitored:
                proces.on_stop()
                self._procs.pop(proces.pid, None) # None for saftey
            elif not proces.is_running() and proces._is_monitored:
                if proces._down_time >= 5 and proces._status != ProcessStatus.AccessDenied:
                    logger.warning(f"Process PID={proces.pid} has been down for {proces._down_time} 5 sec, removing from manager")
                    proces._status = ProcessStatus.Restarting
                    try:
                        proces.on_restart()
                    except Exception as e:
                        logger.error(f"Failed to restart monitored process PID={proces.pid}: {e}")
                        proces._status = ProcessStatus.Failed

    def on_stop(self):
        pass

    def reconcile_live_processes(self, live_pids: set[int]) -> int:
        removed = 0
        for pid, proces in list(self._procs.items()):
            if pid in live_pids:
                continue

            if proces._is_monitored:
                continue

            try:
                proces.on_stop()
            except Exception as e:
                logger.debug(f"Failed to stop stale PID={pid} during reconcile: {e}")

            self._procs.pop(pid, None)
            removed += 1

        return removed

    def get_name(self) -> str:
        return "ProcessManager"

    def is_healthy(self) -> bool:
        for [pid, proces] in self._procs.items():
            if proces._is_monitored and not proces.is_running():
                logger.error(f"Monitored process PID={pid} is not running!")
                return False
        return True