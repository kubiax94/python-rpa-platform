from __future__ import annotations

import win32con
import win32process
from typing import override

from vm_agent.src.core.abstract_proces import AbstractProcess
from vm_agent.src.telemetry.Itelemetry_provider import ITelemetryProvider


class ManagedTask(AbstractProcess):
    def __init__(self, task_id: str, script_path: str, cwd: str, telemetry_provider: ITelemetryProvider):
        super().__init__(
            exe="powershell.exe",
            args=f'-ExecutionPolicy Bypass -NoProfile -NonInteractive -File "{script_path}"',
            cwd=cwd,
            visible=False,
            telemetry_provider=telemetry_provider,
        )

        self.task_id = task_id
        self.script_path = script_path
        self.hStdOutput = None
        self.hStdError = None

    def attach_output_handles(self, stdout_handle, stderr_handle) -> None:
        self.hStdOutput = stdout_handle
        self.hStdError = stderr_handle

    @override
    def to_json_only_change(self, sync: bool = False):
        payload = super().to_json_only_change(sync=sync)
        if payload is None:
            return None
        payload["task_id"] = self.task_id
        return payload

    @override
    def requires_handle_inheritance(self) -> bool:
        return self.hStdOutput is not None or self.hStdError is not None

    @override
    def get_startupinfo(self) -> win32process.STARTUPINFO:
        startup_info = super().get_startupinfo()

        if self.hStdOutput and self.hStdError:
            startup_info.dwFlags |= win32con.STARTF_USESTDHANDLES
            startup_info.hStdOutput = self.hStdOutput
            startup_info.hStdError = self.hStdError

        return startup_info

