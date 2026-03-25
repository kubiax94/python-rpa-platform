from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional, Protocol

if TYPE_CHECKING:
    from vm_agent.src.core.abstract_proces import AbstractProcess

class IProcessManager(Protocol):
    """
    Interface for process manager components.
    Defines methods for managing processes within the agent.
    """

    def rebind_process(self, old_pid: int, new_pid: int, proc: "AbstractProcess") -> None:
        ...

    def start_task(self, task: "AbstractProcess") -> "AbstractProcess":
        ...

    def start_process(self, proc: "AbstractProcess") -> "AbstractProcess":
        ...
    
    def stop_process(self, pid: int, force: bool = False) -> bool:
        ...
        
    def find_process_by_ppid(self, ppid: int) -> List[AbstractProcess]:
        ...

    def get_process(self, pid: int) -> Optional["AbstractProcess"]:
        ...

    def get_all_processes(self) -> List["AbstractProcess"]:
        ...

    def find_process_by_exe(self, exe: str) -> List["AbstractProcess"]:
        ...
    
    def find_process_by_cmd(self, cmd_substr: str) -> List["AbstractProcess"]:
        ...
    
