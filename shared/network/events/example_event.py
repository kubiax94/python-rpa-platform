from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from shared.protocol.network_event import NetworkEvent
from shared.network.events import register_event

class HandshakeData(BaseModel):
    client_id: str = Field(description="Unique identifier for the client", default="")
    capabilities: List[str] = []

@register_event("handshake")  # zarejestruje pod "handshake"
class HandshakeEvent(NetworkEvent):
    type: Literal["handshake"] = "handshake"
    data: HandshakeData = Field(default_factory=HandshakeData)


class StartProgramData(BaseModel):
    agent_id: str = Field(description="Target agent identifier", default="")
    exe: str = Field(description="Path to the executable to start", default="")
    args: str = Field(description="Arguments for the executable", default="")
    cwd: str = Field(description="Current working directory", default="")
    visible: bool = Field(description="Whether the program window should be visible", default=True)
    session: str = Field(description="Session identifier where the program should run", default="")

@register_event("start_program")
class StartProgramEvent (NetworkEvent):
    _owner= "server"
    type: Literal["start_program"] = "start_program"
    data: StartProgramData = Field(default_factory=StartProgramData)

@register_event("start_monitored_process")
class StartMonitoredProcessEvent(StartProgramEvent):
    _owner= "server"
    type: Literal["start_monitored_process"] = "start_monitored_process"

# Server → Agent: Create session for user
class CreateSessionData(BaseModel):
    agent_id: str = Field(description="Target agent identifier", default="")
    username: str = Field(description="Username (e.g., DOMAIN\\user)",default="")
    password: str = Field(description="Password for the user", default="")
    domain: str = Field(description="Domain of the user", default="")

@register_event("create_session")
class CreateSessionEvent(NetworkEvent):
    _owner = "server"
    type: Literal["create_session"] = "create_session"
    data: CreateSessionData = Field(default_factory=CreateSessionData)


# Agent → Server: Session created successfully
class SessionCreatedData(BaseModel):
    username: str
    session_id: int
    session_name: str = Field(default="Unknown")

@register_event("session_created")
class SessionCreatedEvent(NetworkEvent):
    _owner = "client"
    type: Literal["session_created"] = "session_created"
    data: SessionCreatedData

# Agent → Server: Session creation failed
class SessionCreationFailedData(BaseModel):
    username: str
    reason: str = Field(description="Reason for failure")
    

@register_event("session_creation_failed")
class SessionCreationFailedEvent(NetworkEvent):
    _owner = "client"
    type: Literal["session_creation_failed"] = "session_creation_failed"
    data: SessionCreationFailedData

# Agent → Server: List of active sessions
class ActiveSessionsData(BaseModel):
    sessions: List[SessionCreatedData] = Field(default_factory=list)

@register_event("active_sessions")
class ActiveSessionsEvent(NetworkEvent):
    _owner = "client"
    type: Literal["active_sessions"] = "active_sessions"
    data: ActiveSessionsData

# Server → Agent: Close user session
class CloseSessionData(BaseModel):
    username: str

@register_event("close_session")
class CloseSessionEvent(NetworkEvent):
    _owner = "server"
    type: Literal["close_session"] = "close_session"
    data: CloseSessionData

# Agent → Server: User session closed
class SessionClosedData(BaseModel):
    username: str

@register_event("session_closed")
class SessionClosedEvent(NetworkEvent):
    _owner = "client"
    type: Literal["session_closed"] = "session_closed"
    data: SessionClosedData

class HeartbeatData(BaseModel):
    agent_status: Optional[dict] = Field(default=None, description="Optional status info about the agent")
    system_metrics: Optional[dict] = Field(default=None, description="Optional system-wide telemetry for the agent host")
    sync: bool = Field(default=False, description="If true, server expects immediate response")
    client_id: str = Field(default="", description="Unique identifier for the client")

@register_event("heartbeat")
class HeartbeatEvent(NetworkEvent):
    _owner = "client"
    type: Literal["heartbeat"] = "heartbeat"
    data: HeartbeatData


class AuthResultData(BaseModel):
    status: Literal["ok", "error"] = Field(default="ok")
    agent_id: str = Field(default="", description="Resolved agent identifier")
    secret: str = Field(default="", description="Issued long-lived secret after bootstrap exchange")
    secret_issued: bool = Field(default=False, description="Whether the server exchanged the bootstrap token for a new secret")
    reason: str = Field(default="", description="Error detail when authentication fails")


@register_event("auth_result")
class AuthResultEvent(NetworkEvent):
    _owner = "server"
    type: Literal["auth_result"] = "auth_result"
    data: AuthResultData = Field(default_factory=AuthResultData)


# ── Task System Events ──────────────────────────────────────────────

# Server → Agent: Execute a task (PowerShell script)
class ExecuteTaskData(BaseModel):
    task_id: str = Field(default="", description="Unique task identifier (UUID)")
    script: str = Field(default="", description="PowerShell script content to execute")
    cwd: str = Field(default="", description="Working directory for the script")
    timeout_sec: int = Field(default=300, description="Max execution time in seconds")
    session: str = Field(default="", description="Target user session username")
    env: dict = Field(default_factory=dict, description="Extra environment variables")

@register_event("execute_task")
class ExecuteTaskEvent(NetworkEvent):
    _owner = "server"
    type: Literal["execute_task"] = "execute_task"
    data: ExecuteTaskData = Field(default_factory=ExecuteTaskData)

# Server → Agent: Cancel a running task
class CancelTaskData(BaseModel):
    task_id: str = Field(default="", description="Task to cancel")

@register_event("cancel_task")
class CancelTaskEvent(NetworkEvent):
    _owner = "server"
    type: Literal["cancel_task"] = "cancel_task"
    data: CancelTaskData = Field(default_factory=CancelTaskData)

# Agent → Server: Streaming output lines
class TaskOutputData(BaseModel):
    task_id: str = ""
    stream: str = Field(default="stdout", description="stdout or stderr")
    data: str = Field(default="", description="Output line/chunk")
    seq: int = Field(default=0, description="Sequence number for ordering")

@register_event("task_output")
class TaskOutputEvent(NetworkEvent):
    _owner = "client"
    type: Literal["task_output"] = "task_output"
    data: TaskOutputData = Field(default_factory=TaskOutputData)

# Agent → Server: Task status change
class TaskStatusData(BaseModel):
    task_id: str = ""
    status: str = Field(default="queued", description="queued/running/completed/failed/cancelled/timeout")
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    error: Optional[str] = None

@register_event("task_status")
class TaskStatusEvent(NetworkEvent):
    _owner = "client"
    type: Literal["task_status"] = "task_status"
    data: TaskStatusData = Field(default_factory=TaskStatusData)


# Server → Agent: Capture screenshot for a process window
class CaptureProcessScreenshotData(BaseModel):
    agent_id: str = Field(default="", description="Target agent identifier")
    target_type: Literal["process", "desktop"] = Field(default="process", description="Capture target kind")
    pid: Optional[int] = Field(default=None, description="Target process id")
    hwnd: Optional[int] = Field(default=None, description="Specific target window handle")
    session_id: Optional[int] = Field(default=None, description="Target session id for desktop capture")
    request_id: str = Field(default="", description="Client-generated request identifier")


@register_event("capture_process_screenshot")
class CaptureProcessScreenshotEvent(NetworkEvent):
    _owner = "server"
    type: Literal["capture_process_screenshot"] = "capture_process_screenshot"
    data: CaptureProcessScreenshotData = Field(default_factory=CaptureProcessScreenshotData)


# Agent → Server: Screenshot capture result
class ProcessScreenshotData(BaseModel):
    agent_id: str = Field(default="", description="Agent that produced the screenshot")
    target_type: Literal["process", "desktop"] = Field(default="process", description="Capture target kind")
    pid: Optional[int] = Field(default=None, description="Target process id")
    hwnd: Optional[int] = Field(default=None, description="Captured window handle")
    session_id: Optional[int] = Field(default=None, description="Target session id for desktop capture")
    request_id: str = Field(default="", description="Request identifier from the caller")
    status: Literal["completed", "failed"] = Field(default="completed")
    image_base64: Optional[str] = Field(default=None, description="PNG image encoded as base64")
    image_format: str = Field(default="png", description="Image format")
    window_title: Optional[str] = Field(default=None, description="Resolved top-level window title")
    error: Optional[str] = Field(default=None, description="Failure reason when capture fails")
    captured_at: Optional[int] = Field(default=None, description="Unix timestamp when image was captured")


@register_event("process_screenshot")
class ProcessScreenshotEvent(NetworkEvent):
    _owner = "client"
    type: Literal["process_screenshot"] = "process_screenshot"
    data: ProcessScreenshotData = Field(default_factory=ProcessScreenshotData)


class SetWindowTrackingData(BaseModel):
    agent_id: str = Field(default="", description="Target agent identifier")
    enabled: bool = Field(default=False, description="Whether periodic window tracking should be enabled")


@register_event("set_window_tracking")
class SetWindowTrackingEvent(NetworkEvent):
    _owner = "server"
    type: Literal["set_window_tracking"] = "set_window_tracking"
    data: SetWindowTrackingData = Field(default_factory=SetWindowTrackingData)


class WatchProcessManagerData(BaseModel):
    agent_id: str = Field(default="", description="Target agent identifier")


@register_event("watch_process_manager")
class WatchProcessManagerEvent(NetworkEvent):
    _owner = "server"
    type: Literal["watch_process_manager"] = "watch_process_manager"
    data: WatchProcessManagerData = Field(default_factory=WatchProcessManagerData)


@register_event("unwatch_process_manager")
class UnwatchProcessManagerEvent(NetworkEvent):
    _owner = "server"
    type: Literal["unwatch_process_manager"] = "unwatch_process_manager"
    data: WatchProcessManagerData = Field(default_factory=WatchProcessManagerData)