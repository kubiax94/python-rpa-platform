# For process manager to detect context of users where session live

from __future__ import annotations

import os
import win32api
import win32security
import win32ts
import logging
from typing import Optional

from vm_agent.src.core.token_provider import ITokenProvider
from vm_agent.src.core.system_token_provider import SystemTokenProvider
from vm_agent.src.core.user_session_token_provider import UserSessionTokenProvider

logger = logging.getLogger(__name__)


class AgentContext:
    """
    Detects the execution context of the agent and provides the appropriate TokenProvider.
    """
    
    def __init__(self):
        self._current_user: Optional[str] = None
        self._session_id: Optional[int] = None
        self._is_system: bool = False
        self._is_service: bool = False
        
        self._detect()
    
    def _detect(self) -> None:
        """Detect the execution context (System, User, Service)."""
        try:
            # Get the current process token
            process_token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(),
                win32security.TOKEN_QUERY
            )
            
            # Get user SID
            sid = win32security.GetTokenInformation(process_token, win32security.TokenUser)[0]
            username, domain, _ = win32security.LookupAccountSid(None, sid)
            self._current_user = f"{domain}\\{username}"
            
            # Check if LocalSystem
            system_sid = win32security.ConvertStringSidToSid("S-1-5-18")  # NT AUTHORITY\SYSTEM
            self._is_system = win32security.WinServiceSid
            
            # Get session ID
            self._session_id = win32ts.ProcessIdToSessionId(os.getpid())
            
            # Check if service (Session 0)
            self._is_service = (self._session_id == 0)
            
            logger.info(f"Agent context: user={self._current_user}, session={self._session_id}, "
                       f"is_system={self._is_system}, is_service={self._is_service}")
            
        except Exception as e:
            logger.error(f"Failed to detect agent context: {e}")
            raise
    
    def is_local_system(self) -> bool:
        return self._is_system
    
    def is_service_session(self) -> bool:
        return self._is_service
    
    def is_user_session(self) -> bool:
        return not self._is_service and self._session_id > 0
    
    def get_current_user(self) -> str:
        """Return the username in whose context the agent is running."""
        return self._current_user
    
    def get_session_id(self) -> int:
        """Return the session ID in which the agent is running."""
        return self._session_id
    
    def get_token_provider_for_self(self) -> ITokenProvider:
        """
        Return TokenProvider for the current agent context.
        If agent = LocalSystem → SystemTokenProvider
        If agent = User session → UserSessionTokenProvider(current session)
        """
        if self._token_provider:
            return self._token_provider
        
        if self.is_local_system():
            logger.info("Agent runs as LocalSystem → using SystemTokenProvider")
            self._token_provider = SystemTokenProvider()
        else:
            logger.info(f"Agent runs in user session {self._session_id} → using UserSessionTokenProvider")
            self._token_provider = UserSessionTokenProvider.from_session_id(self._session_id)
        
        return self._token_provider
    
    def get_token_provider_for_target(self, target_session_id: Optional[int] = None, 
                                      target_username: Optional[str] = None) -> ITokenProvider:
        """
        Return TokenProvider for desired session/user.
        
        Args:
            target_session_id: specific session (e.g., 2 for RDP)
            target_username: specific user (e.g., "DOMAIN\\robot")
        
        Returns:
            TokenProvider for the desired context.
        
        Raises:
            PermissionError: if the agent lacks permissions (non-System trying to get token of another user)
        """
        # If no target specified, use current context
        if not target_session_id and not target_username:
            return self.get_token_provider_for_self()
        
        # Check permissions
        if not self.is_local_system():
            raise PermissionError(
                f"Agent runs as {self._current_user} (not LocalSystem). "
                "Cannot create processes in other user sessions."
            )
        
        # Wybierz provider na podstawie targetu
        if target_username:
            logger.info(f"Creating TokenProvider for user: {target_username}")
            return UserSessionTokenProvider.from_username(target_username)
        
        if target_session_id is not None:
            logger.info(f"Creating TokenProvider for session: {target_session_id}")
            return UserSessionTokenProvider.from_session_id(target_session_id)
        
        # Fallback: aktywna konsola
        logger.info("No specific target → using active console")
        return UserSessionTokenProvider.from_active_console()
    
    def __repr__(self):
        return (f"<AgentContext user={self._current_user} session={self._session_id} "
                f"system={self._is_system} service={self._is_service}>")