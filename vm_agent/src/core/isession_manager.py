from typing import Protocol

class ISessionManager(Protocol):
    def discover_processes_per_session(self) -> None:
        ...