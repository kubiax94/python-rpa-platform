from typing import List
import logging
from typing import override
from vm_agent.src.core.abstract_proces import AbstractProcess
from vm_agent.src.core.iprocess_manager import IProcessManager
from vm_agent.src.core.isession_manager import ISessionManager
from vm_agent.src.telemetry.Itelemetry_provider import ITelemetryProvider


class MonitoredProcess(AbstractProcess):
    __slots__ = ("_is_monitored",)

    def __init__(self, 
                 exe: str, 
                 args: str, 
                 cwd: str, 
                 visible: bool, 
                 session_manager: ISessionManager,
                 process_manager: IProcessManager = None,
                 telemetry_provider: ITelemetryProvider = None
                 ):
        super().__init__(exe, args, cwd, visible, telemetry_provider=telemetry_provider)
        self._is_monitored: bool = True
        self._session_manager = session_manager
        self._process_manager = process_manager
        self.childrens: List[int] = []
        # Append a unique identifier to the args for monitored processes, like browsers
        if (self.pinfo.exe != "notepad.exe"):
            if self.pinfo.args != "":
                self.pinfo.args += " --agent_id_1234"
            else:
                self.pinfo.args = "--agent_id_1234"
    
    @override
    def on_tick(self):
        return super().on_tick()

    @override
    def get_cmd(self):
        return super().get_cmd()
    
    @override
    def on_restart(self) -> bool:
        logging.info(f"Monitored process {self.pinfo.exe} with PID {self.pid} is restarting.")
        
        self._session_manager.discover_processes_per_session()
        all_process = self._process_manager.find_process_by_exe(self.pinfo.exe)
        old_pid = self.pid

        for proc in all_process:
            if proc.pid != self.pid and proc.is_running() and proc.pinfo.args.__contains__("--agent_id_1234"):
                logging.info(f"Found existing process with same exe: PID {proc.pid}. Not restarting.")
                self.set_pid(proc.pid)
                self._process_manager.rebind_process(old_pid, proc.pid, self)
                return True
            
        self._process_manager.start_process(self)
        self._process_manager.rebind_process(old_pid, self.pid, self)
        return True

    
    @override
    def on_start(self):
        
        super().on_start()
        self._down_time = 0
        self._session_manager.discover_processes_per_session()
        self._find_child_processes()
        logging.info(f"Found child processes for {self.pinfo.exe} with PID {self.pid}: {self.childrens}")


    
    def _find_child_processes(self) -> List[int]:
        self.childrens = []
        all_processes = self._process_manager.find_process_by_ppid(self.pid)
        for proc in all_processes:
            if proc.is_running():
                self.childrens.append(proc.pid)
        return self.childrens

    @override
    def on_stop(self):
        logging.info(f"Monitored process {self.pinfo.exe} with PID {self.pid} has stopped.")

    def save_pids(self, process_name: str) -> None:
        from vm_agent.src.core.process_manager import PIDS_FILE
        import json
        import os

        pids = {}
        if os.path.exists(PIDS_FILE):
            with open(PIDS_FILE, "r") as f:
                pids = json.load(f)
        
        pids[process_name] = self.pid
        
        with open(PIDS_FILE, "w") as f:
            json.dump(pids, f)