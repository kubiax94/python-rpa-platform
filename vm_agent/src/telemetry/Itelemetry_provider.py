from typing import Optional, Protocol

from vm_agent.src.telemetry.process_info import CpuHistory, ProcessInfo, ProcessTelemetry

class ITelemetryProvider(Protocol):
    """
    Interface for telemetry providers.
    Components implementing this interface can collect and report telemetry data.
    """

    def get_full_info(self, hProcess: int, cpu_history: CpuHistory) -> tuple[ProcessInfo, ProcessTelemetry]:
        ...

    def get_info(self, hProcess: int) -> Optional[ProcessInfo]:
        """
        Collect current information metrics.
        Args:
            hProcess: Handle to the process for which information is collected.
        Returns:
            ProcessInfo object containing current process information.
        """
        ...
    
    def get_telemetry(self, hProcess: int, cpu_history: Optional[CpuHistory]) -> Optional[ProcessTelemetry]:
        ...

    def get_system_metrics(self) -> dict:
        ...
        
    def report_metrics(self, metrics: dict) -> None:
        """
        Report collected telemetry metrics to the designated endpoint.

        Args:
            metrics: A dictionary containing telemetry metrics to report.
        """
        ...