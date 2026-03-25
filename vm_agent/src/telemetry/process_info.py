
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass(slots=True)
class CpuHistory:
    last_cpu_time: int = 0
    last_timestamp: float = 0.0
    last_io_read_bytes: int = 0
    last_io_write_bytes: int = 0
    last_io_other_bytes: int = 0


@dataclass(slots=True)
class ProcessTelemetry:
    pid: int
    cpu_usage: float
    working_set: int
    private_bytes: int
    handle_count: int
    exit_code: Optional[int] = None
    io_counters: Optional[Dict[str, float | int]] = None
    net_usage: Optional[float] = None


@dataclass(slots=True)
class ProcessInfo:
    pid: Optional[int] = None
    ppid: Optional[int] = None

    exe: str = ""
    exe_path: str = ""
    image_path: str = ""
    cmd: str = ""
    args: str = ""
    cwd: str = ""
    user: str = ""

    sessionid: int = -1
    creation_time: float = 0.0
    status: str = ""
    has_window: Optional[bool] = None
    window_title: str = ""
    window_hwnd: Optional[int] = None
    windows: list[dict[str, str | int | bool | None]] = field(default_factory=list)
    capture_target_pid: Optional[int] = None
    capture_target_kind: str = ""


