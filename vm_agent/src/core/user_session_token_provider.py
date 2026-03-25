from __future__ import annotations

import win32security
import win32ts
import win32profile
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class UserSessionTokenProvider:
    """
    Token provider dla sesji użytkownika (Console/RDP).
    Pobiera token z aktywnej sesji i udostępnia go do CreateProcessAsUser.
    """
    
    def __init__(self, session_id: int):
        self.session_id = session_id
        self._user_token: Optional[int] = None
        self._primary_token: Optional[int] = None
        self._username: Optional[str] = None
        self._domain: Optional[str] = None
        self._session_name: Optional[str] = None
    
    @classmethod
    def get_all_active_sessions(cls) -> List["UserSessionTokenProvider"]:
        """Zwraca listę wszystkich aktywnych sesji (Console + RDP)."""
        sessions = []
        for session in win32ts.WTSEnumerateSessions(win32ts.WTS_CURRENT_SERVER_HANDLE):
            session_id = session["SessionId"]
            state = session["State"]
            
            if state == win32ts.WTSActive:
                try:
                    provider = cls(session_id)
                    provider._session_name = session.get("WinStationName", "Unknown")
                    sessions.append(provider)
                    logger.info(f"Found active session: ID={session_id}, Name={provider._session_name}")
                except Exception as e:
                    logger.warning(f"Could not create session for ID={session_id}: {e}")
        
        return sessions
    
    @classmethod
    def from_active_console(cls) -> "UserSessionTokenProvider":
        """Tworzy provider z aktywnej konsoli (główny monitor)."""
        session_id = win32ts.WTSGetActiveConsoleSessionId()
        if session_id in (-1, 0xFFFFFFFF):
            raise RuntimeError("No active console session")
        return cls(session_id)
    
    @classmethod
    def from_session_id(cls, session_id: int) -> "UserSessionTokenProvider":
        """Tworzy provider z konkretnego ID sesji."""
        return cls(session_id)
    
    @classmethod
    def from_username(cls, username: str) -> "UserSessionTokenProvider":
        """Znajduje sesję po nazwie użytkownika."""
        for session in cls.get_all_active_sessions():
            session._acquire_token()
            if session.get_username().lower() == username.lower() or session._username.lower() == username.lower():
                return session
        raise ValueError(f"No active session for user '{username}'")
    
    def _acquire_token(self) -> None:
        """Pobiera token użytkownika z sesji (wymaga LocalSystem)."""
        if self._user_token:
            return
        
        logger.info(f"Acquiring user token for session {self.session_id}")
        self._user_token = win32ts.WTSQueryUserToken(self.session_id)
        
        self._primary_token = win32security.DuplicateTokenEx(
            self._user_token,
            win32security.TOKEN_ALL_ACCESS,
            win32security.SecurityImpersonation,
            win32security.TokenPrimary,
            None,
        )
        
        sid = win32security.GetTokenInformation(
            self._primary_token, 
            win32security.TokenUser
        )[0]
        self._username, self._domain, _ = win32security.LookupAccountSid(None, sid)
        logger.info(f"Token acquired: {self._domain}\\{self._username}")
    
    def get_token(self) -> int:
        """Zwraca PRIMARY token (handle)."""
        if not self._primary_token:
            self._acquire_token()
        return self._primary_token
    
    def get_environment(self) -> dict:
        """Zwraca environment block użytkownika."""
        if not self._primary_token:
            self._acquire_token()
        return win32profile.CreateEnvironmentBlock(self._primary_token, False)
    
    def get_desktop(self) -> str:
        """Zwraca desktop w sesji użytkownika."""
        return r"winsta0\default"
    
    def get_username(self) -> str:
        """Zwraca pełną nazwę użytkownika (DOMAIN\\user)."""
        if not self._username:
            self._acquire_token()
        return f"{self._domain}\\{self._username}"
    
    @property
    def session_name(self) -> str:
        return self._session_name or f"Session-{self.session_id}"
    
    def close(self) -> None:
        """Zamyka handly tokenów."""
        if self._primary_token:
            self._primary_token.Close()
            self._primary_token = None
        if self._user_token:
            self._user_token.Close()
            self._user_token = None
        logger.info(f"Session {self.session_id} tokens closed")
    
    def __enter__(self):
        self._acquire_token()
        return self
    
    def __exit__(self, *args):
        self.close()
    
    def __repr__(self):
        return f"<UserSessionTokenProvider id={self.session_id} name={self.session_name} user={self.get_username() if self._username else 'unknown'}>"