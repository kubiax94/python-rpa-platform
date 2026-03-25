import time
import win32ts
import win32profile
import win32security
import win32process
import win32con
import win32api
import logging
from typing import Dict, Optional, Tuple
from vm_agent.src.core.abstract_proces import AbstractProcess, ProcessStatus
from vm_agent.src.core.clock import Clock
from vm_agent.src.core.ilifecycle import ILifeCycle
from vm_agent.src.core.isession_manager import ISessionManager
from vm_agent.src.core.user_session import UserSession
from vm_agent.src.telemetry.Itelemetry_provider import ITelemetryProvider
from vm_agent.src.telemetry.windows_telemetry_provider import WindowsTelemetryProvider

logger = logging.getLogger(__name__)


class SessionManager(ILifeCycle, ISessionManager):
    """
    Manages user sessions - both existing and programmatically created.
    Can login users via credentials from server.
    """
    
    def __init__(self):
        self.telemetry: ITelemetryProvider = WindowsTelemetryProvider()
        self._system_session: UserSession = UserSession(0, telemetry_provider=self.telemetry)  # System session
        self._sessions: Dict[str, UserSession] = {}
        self._running = False
        self._init = False
    
    def on_start(self) -> None:
        logger.info("SessionManager starting...")
        self._running = True
        self._refresh_sessions()
        self.discover_processes_per_session()
        
        if not self._sessions:
            logger.warning("⚠️ No sessions - waiting for login command or user login")
        else:
            logger.info(f"✅ Active sessions: {len(self._sessions)} interactive")

        for session in self._sessions.values():
            session.on_start()
    
    def on_tick(self) -> None:
        if not self._running:
            return

        try:
            if Clock.get_time() % 30 == 0:
                self._refresh_sessions()
                self.discover_processes_per_session()
            
            # tick for lifecycle of each session
            self._system_session.on_tick()
            if not self._system_session.is_healthy():
                logger.warning(f"System session {self._system_session.session_id} is unhealthy")
            for session in self._sessions.values():
                session.on_tick()
                if not session.is_healthy():
                    logger.warning(f"Session {session.session_id} is unhealthy")            
            
        except Exception as e:
            logger.exception(f"Error refreshing sessions: {e}")
    
    def on_stop(self) -> None:
        logger.info("SessionManager stopping...")
        self._running = False
        
        # Close interactive sessions
        for session_id in list(self._sessions.keys()):
            self._remove_session(session_id)
    
        
        logger.info("SessionManager stopped")
    
    def get_name(self) -> str:
        return "SessionManager"
    
    def is_healthy(self) -> bool:
        return self._running and (len(self._sessions) > 0 or len(self._token_sessions) > 0)
    
    def get_status(self, sync: bool = False) -> dict:
        status = {}
        status[f"session:{self._system_session.session_id}"] = {
            "type": "interactive",
            "session_id": self._system_session.session_id,
            "process_count": len(self._system_session._procs),
            **self._system_session.get_status(sync=sync)
        }
        for session in self._sessions.values():
            session_status = session.get_status(sync=sync)
            status[f"session:{session.session_id}"] = {
                "type": "interactive",
                "session_id": session.session_id,
                "process_count": len(session._procs),
                **session_status
            }

        return status
    
    # ========== Session Discovery ==========
    
    def _refresh_sessions(self) -> None:
        """Refresh interactive sessions (RDP/Console)"""
        try:
            server_handle = win32ts.WTS_CURRENT_SERVER_HANDLE
            sessions = win32ts.WTSEnumerateSessions(server_handle)
            
            for session in sessions:
                session_id = session["SessionId"]
                
                if session_id in [0, 65536, 65537]:
                    continue
                
                user_session_tmp = UserSession(session_id, telemetry_provider=self.telemetry)
                username = user_session_tmp.get_username()
                
                if not username:
                    continue
                
                if username not in self._sessions:
                    self._sessions[username] = user_session_tmp

                    continue

                user_old_session = self._sessions[username]
                user_old_session.telemetry = self.telemetry
                if user_old_session.session_id != session_id:
                    logger.info(f"Session change detected for user {username}: {user_old_session.session_id} -> {session_id}")
                    user_old_session.session_id = session_id
                    user_old_session._state = user_session_tmp.get_state()
                    user_old_session.close_all_processes()
                    continue

        except Exception as e:
            logger.exception(f"Error enumerating sessions: {e}")
    
    def _remove_session(self, session_id: int) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            try:
                session.close()
                logger.info(f"🔚 Interactive session closed: {session_id}")
            except Exception as e:
                logger.error(f"Error closing session {session_id}: {e}")
    
    def _remove_token_session(self, username: str) -> None:
        session = self._token_sessions.pop(username, None)
        if session:
            try:
                session.close()
                logger.info(f"🔚 Token session closed: {username}")
            except Exception as e:
                logger.error(f"Error closing token session {username}: {e}")
        """
        Logout user (remove token session).
        
        Args:
            username: Username to logout
        
        Returns:
            True if logged out, False if not found
        """
        username_lower = username.lower()
        
        if username_lower in self._token_sessions:
            self._remove_token_session(username_lower)
            logger.info(f"🔚 User logged out: {username}")
            return True
        
        logger.warning(f"User not found: {username}")
        return False
    
    # ========== Public API ==========

    def discover_processes_per_session(self):
        pids = set(win32process.EnumProcesses())
        session_map = {session.session_id: session for session in self._sessions.values()}

        removed_total = self._system_session.reconcile_live_processes(pids)
        for session in self._sessions.values():
            removed_total += session.reconcile_live_processes(pids)
        if removed_total > 0:
            logger.info(f"Removed {removed_total} stale managed processes during reconcile")

        managed_pids = set(self._system_session._procs.keys())
        for session in self._sessions.values():
            managed_pids.update(session._procs.keys())
            
        # Przypisz nowe i aktualizuj istniejące procesy
        for pid in pids:
            if pid in managed_pids:
                continue
            try:
                session_id = win32ts.ProcessIdToSessionId(pid)
                session = session_map.get(session_id)
                if session:
                    procs = session._procs
                else:
                    procs = self._system_session._procs

                if pid not in procs:
                    proc = AbstractProcess("unknown", "", "", True, telemetry_provider=self.telemetry)
                    proc.set_pid(pid)        
                    procs[pid] = proc
                    proc.on_start()

            except Exception as e:
                logger.debug(f"Error processing PID={pid}: {e}")
                continue
   
    def has_session(self) -> bool:
        """Check if any session exists (interactive or token)"""
        return len(self._sessions) > 0
    
    def get_session_by_username(self, username: str) -> Optional[UserSession]:
        """
        Get session by username.
        Checks interactive sessions first, then token sessions.
        """
        username_lower = username.lower().strip()

        if not username_lower:
            return self.get_primary_session()
        
        for session in self._sessions.values():
            session_username = session.get_username() or ""
            session_fullname = session.get_fullname() or ""
            session_name = session.get_session_name() or ""

            if (
                session_username.lower() == username_lower or
                session_fullname.lower() == username_lower or
                session_name.lower() == username_lower
            ):
                return session

            if "\\" in username_lower and session_username.lower() == username_lower.split("\\", 1)[1]:
                return session
    
    def get_primary_session(self) -> Optional[UserSession]:
        """
        Get best available session.
        Priority: Console > RDP > First token session
        """
        # Try console
        console_session_id = win32ts.WTSGetActiveConsoleSessionId()
        if console_session_id in self._sessions:
            return self._sessions[console_session_id]
        
        # Try any interactive
        if self._sessions:
            return next(iter(self._sessions.values()))
        
        # Try any token session
        if self._token_sessions:
            return next(iter(self._token_sessions.values()))
        
        return None

    def get_system_session(self) -> UserSession:
        return self._system_session
    
    def get_all_sessions(self) -> list[UserSession]:
        """Get all sessions (interactive + token)"""
        return list(self._sessions.values())
    
    def list_logged_in_users(self) -> list[dict]:
        """List all logged in users with details"""
        users = []
        
        # Interactive sessions
        for sid, session in self._sessions.items():
            users.append({
                "username": session.get_username(),
                "type": "interactive",
                "session_id": sid,
                "process_count": len(session._procs)
            })
        
        # Token sessions
        for username, session in self._token_sessions.items():
            users.append({
                "username": username,
                "type": "token",
                "session_id": -1,
                "process_count": len(session._procs)
            })
        
        return users