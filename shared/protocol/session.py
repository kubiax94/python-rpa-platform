from dataclasses import field
import time
from enum import Enum
from typing import Optional


class SessionState(Enum):
    INIT = "init"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"

class Session:
    agent_id: str
    session_id: Optional[str] = None
    state: SessionState = SessionState.INIT
    created_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())
    last_pong_ts: float = 0.0
    retries: int = 0

    def set_state(self, st: SessionState) -> None:
        self.state = st
        self.updated_at = time.time()