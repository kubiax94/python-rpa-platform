from __future__ import annotations
from enum import Enum
import os
import time

import win32api
import win32con
import win32process
import win32security
import win32ts
import win32profile
import win32service
import logging
from typing import Optional, List

from vm_agent.src.core.abstract_proces import AbstractProcess
from vm_agent.src.core.process_manager import ProcessManager
from vm_agent.src.telemetry.Itelemetry_provider import ITelemetryProvider

logger = logging.getLogger(__name__)

class SessionState(Enum):
    Active = win32ts.WTSActive
    Connected = win32ts.WTSConnected
    ConnectQuery = win32ts.WTSConnectQuery
    Shadow = win32ts.WTSShadow
    Disconnected = win32ts.WTSDisconnected
    Idle = win32ts.WTSIdle
    Listen = win32ts.WTSListen
    Reset = win32ts.WTSReset
    Down = win32ts.WTSDown
    Init = win32ts.WTSInit

class UserSession(ProcessManager):
    """
    Manages a user session: token, environment, and processes.
    Extends ProcessManager to add session-specific logic (login, token handling).
    """
    
    def __init__(self, session_id: int, is_monitored: bool = False, telemetry_provider: ITelemetryProvider = None):
        super().__init__(telemetry_provider=telemetry_provider)
        self.session_id = session_id
        self._initialized = False
        self._process_explorer: Optional[AbstractProcess] = None
        self._user_token: Optional[int] = None
        self._primary_token: Optional[int] = None
        self._username: Optional[str] = None
        self._domain: Optional[str] = None
        self._session_name: Optional[str] = None
        self._state: SessionState = SessionState.Init
        self._down_time: int = 0  # in seconds
        self._is_monitored: bool = is_monitored
        self._down_time: float = 0.0  # in seconds
        self._last_window_refresh_at: float = 0.0
    
    @classmethod
    def get_all_active_sessions(cls) -> List["UserSession"]:
        """
        Discovers all active user sessions (Console + RDP).
        
        Returns:
            List of UserSession objects (one per active session)
        """
        sessions = []
        for session in win32ts.WTSEnumerateSessions(win32ts.WTS_CURRENT_SERVER_HANDLE):
            session_id = session["SessionId"]
            state = session["State"]
            
            # WTSActive = 0 (active session)
            if state == win32ts.WTSActive:
                try:
                    user_session = cls(session_id)
                    user_session._session_name = f"{session.get(user_session.get_name(), 'Unknown')}-"
                    sessions.append(user_session)
                    logger.info(f"Found active session: ID={session_id}, Name={user_session._session_name}")
                except Exception as e:
                    logger.warning(f"Could not create session for ID={session_id}: {e}")
            else:
                logger.info(f"Skipping non-active session: ID={session_id}, State={state}")
        
        return sessions
    
    @classmethod
    def from_active_console(cls) -> "UserSession":
        """
        Creates session from active console (physical monitor).
        
        Returns:
            UserSession for console session
        
        Raises:
            RuntimeError: No active console session
        """
        session_id = win32ts.WTSGetActiveConsoleSessionId()
        if session_id in (-1, 0xFFFFFFFF):
            raise RuntimeError("No active console session")
        return cls(session_id)
    
    @classmethod
    def from_session_id(cls, session_id: int) -> "UserSession":
        """
        Creates session from specific session ID.
        
        Args:
            session_id: Windows session ID
        
        Returns:
            UserSession for that session
        """
        return cls(session_id)
    
    @classmethod
    def from_username(cls, username: str) -> "UserSession":
        """
        Finds session by username (case-insensitive).
        
        Args:
            username: User name (e.g., "DOMAIN\\user" or "user")
        
        Returns:
            UserSession for that user
        
        Raises:
            ValueError: User not found in active sessions
        """
        for session in cls.get_all_active_sessions():
            session.acquire_token()  # fetch username from token
            if session.get_username().lower() == username.lower() or session._username.lower() == username.lower():
                return session
        raise ValueError(f"No active session for user '{username}'")
    
    @classmethod
    def from_token(cls, token: int, username: str, session_id: int = -1) -> UserSession:
        """
        Create from user token (programmatic login).
        
        Args:
            token: Primary token handle
            username: Username
            session_id: Session ID (use -1 for token-based)
        
        Returns:
            UserSession instance
        """
        instance = cls(session_id)
        instance._primary_token = token
        instance.session_id = session_id
        instance._username = username
        instance._session_name = "Token-based"
        
        logger.info(f"UserSession created from token: {username}")
        return instance

    def acquire_token(self) -> None:
        """
        Acquires user token from session (requires LocalSystem privileges).
        Token is cached for reuse.
        """
        if self._user_token:
            return  # already acquired
        if (self.session_id > 0):
            logger.info(f"Acquiring user token for session {self.session_id}")
            self._user_token = win32ts.WTSQueryUserToken(self.session_id)
        elif self.session_id == 0:
            logger.info(f"Acquiring user token for Session 0 (Service)")
            hProcess = win32api.GetCurrentProcess()
            self._user_token = win32security.OpenProcessToken(hProcess, win32security.TOKEN_ALL_ACCESS)
            win32api.CloseHandle(hProcess)
        else:
            raise RuntimeError(f"Cannot acquire token for session {self.session_id}")
        
        # Duplicate as PRIMARY token (required for CreateProcessAsUser)
        self._primary_token = win32security.DuplicateTokenEx(
            self._user_token,
            win32security.SecurityImpersonation,
            win32security.TOKEN_ALL_ACCESS,
            win32security.TokenPrimary,
            None,
        )
        
        # Extract username/domain from token
        sid = win32security.GetTokenInformation(
            self._primary_token, 
            win32security.TokenUser
        )[0]

        self._username, self._domain, _ = win32security.LookupAccountSid(None, sid)
        logger.info(f"Token acquired: {self._domain}\\{self._username}")

    def get_fullname(self) -> Optional[str]:
        if self.session_id == 0:
            self._domain = self._domain or "NT AUTHORITY"
            self._username = self._username or "SYSTEM"
            return f"{self._domain}\\{self._username}"

        try:
            self._domain = win32ts.WTSQuerySessionInformation(
                win32ts.WTS_CURRENT_SERVER_HANDLE,
                self.session_id,
                win32ts.WTSDomainName
            )
            return f"{self._domain}\\{self.get_username()}"
        except Exception as e:
            self._state = SessionState.Down
            logger.error(f"Error getting fullname for session {self.session_id}: {e}")
            return None

    def get_username(self) -> Optional[str]:
        if self.session_id == 0:
            self._username = self._username or "SYSTEM"
            self._domain = self._domain or "NT AUTHORITY"
            return self._username

        try:
            self._username = win32ts.WTSQuerySessionInformation(
                win32ts.WTS_CURRENT_SERVER_HANDLE,
                self.session_id,
                win32ts.WTSUserName
            )
            return self._username
        except Exception as e:
            self._state = SessionState.Down
            logger.error(f"Error getting username for session {self.session_id}: {e}")
            return self._username
    
    def get_session_name(self) -> str:
        """
        Returns session name (e.g., "Console", "RDP-Tcp#0").
        
        Returns:
            Session name
        """
        if self._session_name:
            return self._session_name

        if self.session_id == 0:
            self._session_name = win32api.GetComputerName()
            return self._session_name

        try:
            self._session_name = win32ts.WTSQuerySessionInformation(
                win32ts.WTS_CURRENT_SERVER_HANDLE,
                self.session_id,
                win32ts.WTSWinStationName
            )
        except Exception:
            pass

        username = self.get_username()
        if self._session_name:
            return self._session_name
        if username:
            return f"{win32api.GetComputerName()}-{username}"
        return f"Session-{self.session_id}"
    
    def _create_process(self, process: AbstractProcess) -> AbstractProcess:
        """
        Creates process as user (via CreateProcessAsUser).
        Implements abstract method from ProcessManager.
        
        Args:
            exe: Executable path
            cmd: Full command line
            cwd: Working directory
            visible: Show window flag
        
        Returns:
            Tuple: (hProcess, hThread, pid, tid)
        """
        # Ensure token is acquired
        if not self._primary_token:
            self.acquire_token()
        
        token_to_use = self._primary_token

        if self._process_explorer and self._process_explorer.is_running():
            logger.info(f"Using explorer.exe token for session {self.session_id}")
            ehandle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, self._process_explorer.pid)
            token_to_use = win32security.OpenProcessToken(ehandle, win32con.TOKEN_ALL_ACCESS)
        # Get user environment
        env = win32profile.CreateEnvironmentBlock(token_to_use, False)
        
        # Setup startup info
        startup = process.get_startupinfo()
        
        creation_flags = win32con.CREATE_UNICODE_ENVIRONMENT
        if not process.visible:
            creation_flags |= getattr(win32con, "CREATE_NO_WINDOW", 0x08000000)
        # Create process as user
        cwd = process.pinfo.cwd if process.pinfo.cwd else os.path.dirname(process.pinfo.image_path or process.pinfo.exe_path or "")
        # Resolve device paths (\Device\HarddiskVolume3\... → C:\...)
        if cwd and cwd.startswith("\\Device\\") and self.telemetry:
            cwd = self.telemetry._resolve_device_path(cwd)
        if not cwd or cwd.startswith("\\Device\\"):
            cwd = None  # Windows użyje domyślnego katalogu
        
        logger.info(f"Creating process as {self.get_username()} with command: {process.get_cmd()} and cwd: {cwd}")

        inherit_handles = process.requires_handle_inheritance()

        hProcess, hThread, pid, tid = win32process.CreateProcessAsUser(
            token_to_use,
            None,
            process.get_cmd(),
            None,
            None,
            inherit_handles,
            creation_flags,
            env,
            cwd,
            startup,
        )

        process.pid = pid
        process.hProcess = hProcess
        process.hThread = hThread
        
        logger.debug(f"Created process as {self.get_username()}: PID={pid}")
        return process

    def start_transient_process(self, process: AbstractProcess) -> AbstractProcess:
        """
        Starts a helper process in this session without registering it in the managed process list.
        Useful for short-lived session-bound operations such as screenshots.
        """
        if process.pinfo.cwd is None:
            process.pinfo.cwd = os.path.dirname(process.pinfo.exe) or None

        self._create_process(process)
        return process

    def should_refresh_windows(self, interval_sec: float) -> bool:
        return (time.time() - self._last_window_refresh_at) >= interval_sec

    def mark_windows_refreshed(self) -> None:
        self._last_window_refresh_at = time.time()

    def apply_window_snapshot(self, window_snapshot: dict[str, dict]) -> None:
        window_map = {int(pid): data for pid, data in window_snapshot.items()}
        process_map = {proc.pid: proc for proc in self._procs.values() if proc.pid is not None}
        console_host_by_parent: dict[int, int] = {}

        for proc in process_map.values():
            if proc.pinfo.exe.lower() == "conhost.exe" and proc.pinfo.ppid in process_map and proc.pid in window_map:
                console_host_by_parent[proc.pinfo.ppid] = proc.pid

        def resolve_capture_target(pid: int) -> tuple[int | None, str]:
            if pid in window_map:
                window_kind = (window_map[pid] or {}).get("window_kind") or "top-level"
                if window_kind == "child-window":
                    return pid, "child-window"
                return pid, "direct-window"

            current_pid = pid
            visited: set[int] = set()
            while current_pid not in visited:
                visited.add(current_pid)
                host_pid = console_host_by_parent.get(current_pid)
                if host_pid is not None:
                    return host_pid, "console-host"

                proc = process_map.get(current_pid)
                if proc is None or proc.pinfo.ppid is None:
                    break
                current_pid = proc.pinfo.ppid

            return None, ""

        for proc in process_map.values():
            target_pid, target_kind = resolve_capture_target(proc.pid)
            target_window = window_map.get(target_pid) if target_pid is not None else None
            new_has_window = target_pid is not None
            new_title = (target_window or {}).get("window_title") or ""
            new_hwnd = (target_window or {}).get("hwnd")
            new_windows = list((target_window or {}).get("windows") or [])

            if (
                proc.pinfo.has_window != new_has_window or
                proc.pinfo.window_title != new_title or
                proc.pinfo.window_hwnd != new_hwnd or
                proc.pinfo.windows != new_windows or
                proc.pinfo.capture_target_pid != target_pid or
                proc.pinfo.capture_target_kind != target_kind
            ):
                proc.pinfo.has_window = new_has_window
                proc.pinfo.window_title = new_title
                proc.pinfo.window_hwnd = new_hwnd
                proc.pinfo.windows = new_windows
                proc.pinfo.capture_target_pid = target_pid
                proc.pinfo.capture_target_kind = target_kind
                proc._it_change = True
    
    def get_state(self) -> SessionState:
        # Returns current session state as string.
        try:
            state = win32ts.WTSQuerySessionInformation(
                win32ts.WTS_CURRENT_SERVER_HANDLE,
                self.session_id,
                win32ts.WTSConnectState
            )

            logger.debug(f"Session {self.session_id} state queried: {SessionState(state).name}")

            if state != self._state.value:
                logger.info(f"Session {self.session_id} state changed: {self._state} -> {state}")
                self._state = SessionState(state)
            return self._state
        except Exception as e:
            self._state = SessionState.Down
            logger.error(f"Error querying session state for {self.session_id}: {win32api.GetLastError()}")
            return SessionState.Down

    def close(self) -> None:
        """
        Closes token handles and terminates all processes.
        Called on session cleanup.
        """
        # Close all processes managed by this session
        if self.get_state() != SessionState.Down:
            self.close_all_processes()
        
        # Close token handles
        if self._primary_token:
            self._primary_token.Close()
            self._primary_token = None
        if self._user_token:
            self._user_token.Close()
            self._user_token = None
        
        logger.info(f"Session {self.session_id} closed")
    
    def is_initialized(self) -> bool:
        user_init = self.find_process_by_exe("userinit.exe")
        
        # if userunit.exe is running session is still initializing
        if len(user_init) > 0:
            self._state = SessionState.Init
            return False

        if self.session_id > 0:
            explorer = self.find_process_by_exe("explorer.exe")
            if len(explorer) > 0 :
                self._process_explorer = explorer[0]
                return True
        else:
            self._process_explorer = None
            self.get_state()
            if self._state != SessionState.Down:
                return True
        
        return False

    def get_status(self, sync: bool = False) -> Optional[dict]:
        fullname = self.get_fullname()
        return {
            "session_id": self.session_id,
            "session_name": self.get_session_name(),
            "username": fullname or "unknown",
            "type": "user_session",
            "status": self._state.name if isinstance(self._state, SessionState) else str(self._state),
            "process_count": len(self._procs),
            "processes": super().get_status(sync=sync)
        }

    def on_start(self) -> None:

        self._initialized = self.is_initialized()
        
        self.get_state()
        
        if self._state == SessionState.Down:
            logger.error(f"Session {self.session_id} is down, cannot start ProcessManager.")
            return
        
        ## Try to find explorer.exe in this session for desktop check
        if len(self._procs) > 0:
            for proces in self._procs.values():
                if proces.pinfo.exe.lower().endswith("explorer.exe"):
                    self._process_explorer = proces
                    logger.info(f"Explorer.exe found in session {self.session_id}, desktop should be available.")
                    break
        
        if not self._process_explorer:
            logger.warning(f"Explorer.exe not found in session {self.session_id}, desktop may not be available.")
        
        super().on_start()

    def on_tick(self) -> None:

        if self._initialized == False:
            self._initialized = self.is_initialized()
            if self._initialized:
                logger.info(f"Session {self.session_id} has been initialized.")
            else:
                
                logger.info(f"Session {self.session_id} is still initializing")
                super().on_tick()
                return  # still initializing, skip tick
            
        self.get_state()

        # If session is down, skip tick processing
        if self._state == SessionState.Down:
            self._down_time += 1.0
            if self._down_time % 5 == 0:
                logger.warning(f"Session {self.session_id} is down for {self._down_time} seconds, skipping tick.")
            return  # session is down, skip  
        
        if (not self._process_explorer or not self._process_explorer.is_running()) and self.session_id > 0:
            for proces in self._procs.values():
                if proces.pinfo.exe.lower().endswith("explorer.exe"):
                    self._process_explorer = proces
                    logger.info(f"Explorer.exe found in session {self.session_id} during tick.")
                    break
            logger.warning(f"Explorer.exe in session {self.session_id} is not running, desktop may be unavailable.")
        #Process Manager Tick
        super().on_tick()

    def __repr__(self):
        username = self.get_username() if self._username else "unknown"
        return f"<UserSession id={self.session_id} name={self.get_session_name()} user={username}>"