#VM agent should use http connection or websocket mechanic

import json
import os
import sys
import uuid
from json import JSONDecodeError
from enum import Enum
from time import sleep
from typing import List
import asyncio
import subprocess
from time import time
import win32con
import win32event
import win32ts

from shared.network.events.example_event import AuthResultData, AuthResultEvent, CancelTaskData, CreateSessionData, CreateSessionEvent, ExecuteTaskData, ExecuteTaskEvent, CancelTaskEvent, CaptureProcessScreenshotData, CaptureProcessScreenshotEvent, HandshakeData, HandshakeEvent, HeartbeatData, HeartbeatEvent, ProcessScreenshotData, ProcessScreenshotEvent, SessionCreatedData, SessionCreatedEvent, SessionCreationFailedData, SessionCreationFailedEvent, SetWindowTrackingData, SetWindowTrackingEvent, StartMonitoredProcessEvent, StartProgramData, StartProgramEvent, TaskStatusData, TaskStatusEvent
from vm_agent.src.core.abstract_proces import AbstractProcess
#from vm_agent.src.core.agent_context import AgentContext
from vm_agent.src.core.agent_bus import AgentBus
from vm_agent.src.core.clock import Clock
from vm_agent.src.core.ilifecycle import ILifeCycle
from vm_agent.src.core.life_cycle_manager import LifecycleManager
from vm_agent.src.core.listener_registration import bind_registered_listeners, register_listener
from vm_agent.src.core.monitored_proces import MonitoredProcess
from vm_agent.src.core.session_manager import SessionManager
from vm_agent.src.core.user_session import SessionState, UserSession
from vm_agent.src.eventsview.event_view import EventLogScanner
from vm_agent.src.network.agent_client import AgentClient
from vm_agent.src.process.task_executor import TaskExecutor

import pyee

import logging

from vm_agent.src.config.bootstrap_config import load_agent_runtime_config, persist_agent_runtime_config
from vm_agent.src.telemetry.Itelemetry_provider import ITelemetryProvider
from vm_agent.src.telemetry.windows_telemetry_provider import WindowsTelemetryProvider
from vm_agent.src.utils.named_pipe_test import send_logon_command
from vm_agent.src.utils.process_screenshot import capture_desktop, capture_process_window, capture_window_handle

logging.basicConfig(
    filename=r"C:\VmAgent\agent.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

class AgentSatus(Enum):
    INITIALIZING = 1
    RUNNING = 2
    PAUSED = 3
    STOPPED = 4
    ERROR = 5

class VmAgent(AgentBus):
    def __init__(self):
        super().__init__()
        self._status: AgentSatus = AgentSatus.INITIALIZING
        self.enable = True
        self._runtime_config = load_agent_runtime_config()
        #self._context: AgentContext = AgentContext()
        self._client: AgentClient = AgentClient()
        self._lifecycle: LifecycleManager = LifecycleManager(1)
        Clock.start(self._lifecycle.tick_interval)
        self._event_viewer = EventLogScanner()
        self._sm: SessionManager = SessionManager()    
        self._telemetry_provider: ITelemetryProvider = WindowsTelemetryProvider()
        self._lifecycle.register(self._sm)
        self._task_executor: TaskExecutor = None  # initialized after client start
        self._window_refresh_interval_sec: float = 60.0
        self._event_scan_interval_sec: float = 60.0
        self._last_event_scan_time: float = 0.0
        self._window_tracking_enabled: bool = False
        self._sync_sent_for_current_connection: bool = False

    def _validate_runtime_host(self):
        expected_hostname = str(self._runtime_config.get("hostname") or "").strip()
        if not expected_hostname:
            return

        local_hostname = str(os.getenv("COMPUTERNAME") or "").strip()
        if not local_hostname:
            return

        if expected_hostname.lower() != local_hostname.lower():
            raise RuntimeError(
                f"Bootstrap package is bound to host '{expected_hostname}', but the agent is running on '{local_hostname}'."
            )

    def run(self):
        logging.info("VmAgent.run() START")
        bind_registered_listeners(self, self)
        self._status = AgentSatus.INITIALIZING
        asyncio.run(self._async_run())

    async def _async_run(self):
        try:
            self._validate_runtime_host()
            connection_config = {
                "url": self._runtime_config.get("server_url", "ws://192.168.1.10:8765/ws"),
                "access_token": self._runtime_config.get("access_token"),
                "bootstrap_token": self._runtime_config.get("bootstrap_token"),
                "client_id": self._runtime_config.get("agent_id"),
            }

            self._client.start(self, connection_config)
            self._task_executor = TaskExecutor(self._client.send_event)
            await self._lifecycle.start()

            self._status = AgentSatus.RUNNING
            logging.info("VmAgent started and running")

            while self._status == AgentSatus.RUNNING:
                fatal_error_reason = self._client.get_fatal_error_reason()
                if fatal_error_reason:
                    self._status = AgentSatus.ERROR
                    logging.error(f"Stopping agent main loop due to fatal connection error: {fatal_error_reason}")
                    break
 
                if not self._client.init:
                    self._sync_sent_for_current_connection = False

                if self._client.init:
                    pending_sync = self._consume_pending_sync()
                    self._scan_event_logs_if_needed(force=pending_sync)
                    self.heartbeat(sync=pending_sync)

                else:
                    logging.debug("Skipping heartbeat until agent session is initialized")

                await asyncio.sleep(1)


        except Exception as e:
            self._status = AgentSatus.ERROR
            logging.exception(f"Agent error: {e}")

        finally:
            await self._lifecycle.stop()
            #await self._client.stop()
            logging.info("VmAgent stopped")

        await self._lifecycle.stop()

    def stop(self):
        self.enable = False
        self._status = AgentSatus.STOPPED
        
    def pause(self):
        raise  Exception("Not implemented")

    def heartbeat(self, sync: bool = False):
        payload = {"client_id": "test_agent"}
        if self._window_tracking_enabled:
            self._refresh_window_metadata_if_needed(force=False)
        system_metrics = self._telemetry_provider.get_system_metrics()
        if sync:
            data = HeartbeatData(agent_status=self._sm.get_status(sync=True), system_metrics=system_metrics)
            data.client_id = self._client.client_id
            data.sync = True
            self._client.send_event(HeartbeatEvent(data=data))
        else:
            data = HeartbeatData(agent_status=self._sm.get_status(), system_metrics=system_metrics)
            data.client_id = self._client.client_id
            data.sync = False
            self._client.send_event(HeartbeatEvent(data=data))

    def _consume_pending_sync(self) -> bool:
        if not self._client.init:
            return False
        if self._sync_sent_for_current_connection:
            return False

        self._sync_sent_for_current_connection = True
        logging.info("Sending one-time sync heartbeat for current connection")
        return True

    def _scan_event_logs_if_needed(self, force: bool = False):
        now = time()
        if not force and (now - self._last_event_scan_time) < self._event_scan_interval_sec:
            return

        new_events = self._event_viewer.scan()
        self._last_event_scan_time = now

        if not new_events:
            return

        logging.info("Event log scan captured %s new events", len(new_events))
        for event in new_events:
            logging.debug(
                "%s - %s - %s - %s",
                event.SourceName,
                event.EventID,
                event.TimeGenerated,
                event.StringInserts,
            )

    @register_listener(SetWindowTrackingEvent, once=False)
    def _set_window_tracking(self, eventData: SetWindowTrackingData):
        enabled = bool(eventData.enabled)
        if self._window_tracking_enabled == enabled:
            return

        self._window_tracking_enabled = enabled
        logging.info("Window tracking %s", "enabled" if enabled else "disabled")

        if enabled:
            try:
                self._refresh_window_metadata_if_needed(force=True)
                self.heartbeat(sync=True)
            except Exception as exc:
                logging.debug(f"Failed to perform initial window refresh after enabling tracking: {exc}")

    @register_listener(AuthResultEvent, once=False)
    def _handle_auth_result(self, eventData: AuthResultData):
        if eventData.status != "ok":
            reason = eventData.reason or "unknown error"
            logging.error(f"Agent authentication failed: {reason}")
            if reason in ("bootstrap token expired", "bootstrap token already used", "invalid bearer token", "missing bearer token"):
                logging.error("Deployment bootstrap credentials are no longer valid. Prepare a new deployment package for this agent.")
            self._client.stop(reason)
            self._status = AgentSatus.ERROR
            return

        if not eventData.access_token:
            return

        self._runtime_config["access_token"] = eventData.access_token
        self._runtime_config.pop("bootstrap_token", None)
        self._runtime_config.pop("secret", None)
        persist_agent_runtime_config(self._runtime_config)
        self._client.update_credentials(access_token=eventData.access_token, bootstrap_token=None)
        logging.info("Persisted issued agent access token for %s", eventData.agent_id or self._client.client_id)
    
    @register_listener(StartProgramEvent, once=False)
    def _start_process(self, eventData: StartProgramData):
        logging.info(f"Starting process with event data: {eventData}")
        logging.info(f"All sessions: {self._sm._sessions}")
        
        proc = AbstractProcess(eventData.exe, eventData.args, eventData.cwd, eventData.visible, self._telemetry_provider)

        session = self._sm.get_session_by_username(eventData.session)

        if (session is None or not session.is_healthy()):
            logging.error(f"No session found for user '{eventData.session}'")
            self._client.send_event(SessionCreationFailedEvent(data=SessionCreationFailedData(
                username=eventData.session,
                reason="No such user session or session is not active"
            )))
            return
        
        session.start_process(proc)
        logging.info(f"Process started: {proc}")
        self._client.send_event(SessionCreatedEvent(data=SessionCreatedData(
            username=eventData.session,
            session_id=session.session_id,
            session_name=session.get_session_name()
        )))

        #self._client.send_event(SessionCreatedEvent(data=SessionCreatedData(username="asdasd", session_id=123, session_name="TestSession")))

    @register_listener(StartMonitoredProcessEvent, once=False)
    def _start_monitored_process(self, eventData: StartProgramData):
        logging.info(f"Starting monitored process with event data: {eventData}")
        logging.info(f"All sessions: {self._sm._sessions}")
        

        session = self._sm.get_session_by_username(eventData.session)

        if (session is None or not session.is_healthy()):
            logging.error(f"No session found for user '{eventData.session}'")
            self._client.send_event(SessionCreationFailedEvent(data=SessionCreationFailedData(
                username=eventData.session,
                reason="No such user session or session is not active"
            )))
            return
        
        proc = MonitoredProcess(eventData.exe, eventData.args, eventData.cwd, eventData.visible, self._sm, session, self._telemetry_provider)
        
        session.start_process(proc)

        logging.info(f"Monitored process started: {proc}")
        self._client.send_event(SessionCreatedEvent(data=SessionCreatedData(
            username=eventData.session,
            session_id=session.session_id,
            session_name=session.get_session_name()
        )))
    
    @register_listener(CreateSessionEvent, once=False)
    def _login_user_session(self, eventData: CreateSessionData):
        logging.info(f"Logging in user session with event data: {eventData.username}")
        logon_process = AbstractProcess("c:\\windows\\system32\\rundll32.exe", "user32.dll,LockWorkStation", "", True, self._telemetry_provider)
        sessions = self._sm.get_all_sessions()

        for sess in sessions:
            if sess.get_state() == SessionState.Active:
                sess.start_process(logon_process)

        sleep(2)  # Wait for session to be ready

        send_logon_command(eventData.username, eventData.password, eventData.domain)

    @register_listener(ExecuteTaskEvent, once=False)
    def _execute_task(self, eventData: ExecuteTaskData):
        logging.info(f"Executing task {eventData.task_id}")
        if eventData.session:
            session = self._sm.get_session_by_username(eventData.session)
            if session is None or not session.is_healthy():
                reason = f"No active session found for user '{eventData.session}'"
                logging.error(f"Task {eventData.task_id}: {reason}")
                self._client.send_event(TaskStatusEvent(data=TaskStatusData(
                    task_id=eventData.task_id,
                    status="failed",
                    error=reason,
                )))
                return
        else:
            session = self._sm.get_system_session()

        asyncio.create_task(self._task_executor.execute(eventData, session))

    @register_listener(CancelTaskEvent, once=False)
    def _cancel_task(self, eventData: CancelTaskData):
        logging.info(f"Cancelling task {eventData.task_id}")
        asyncio.create_task(self._task_executor.cancel(eventData.task_id))

    def _find_session_for_pid(self, pid: int) -> UserSession | None:
        try:
            session_id = win32ts.ProcessIdToSessionId(pid)
        except Exception as exc:
            logging.error(f"Unable to resolve session for PID {pid}: {exc}")
            return None

        if session_id == 0:
            return self._sm.get_system_session()

        for session in self._sm.get_all_sessions():
            if session.session_id == session_id:
                return session

        logging.warning(f"No tracked user session found for PID {pid} in session {session_id}")
        return None

    def _find_session_by_id(self, session_id: int) -> UserSession | None:
        if session_id == 0:
            return self._sm.get_system_session()

        for session in self._sm.get_all_sessions():
            if session.session_id == session_id:
                return session

        logging.warning(f"No tracked user session found for session id {session_id}")
        return None

    def _build_screenshot_helper_process(self, output_path: str, pid: int) -> AbstractProcess:
        return self._build_session_helper_process(
            command_name="capture-screenshot",
            command_args=f'--target process --pid {pid} --out "{output_path}"'
        )

    def _build_session_helper_process(self, command_name: str, command_args: str) -> AbstractProcess:
        if getattr(sys, "frozen", False):
            exe = sys.executable
            args = f'{command_name} {command_args}'
            cwd = os.path.dirname(exe)
        else:
            service_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "service", "agent_service.py"))
            exe = sys.executable
            args = f'"{service_script}" {command_name} {command_args}'
            cwd = os.path.dirname(service_script)

        return AbstractProcess(exe, args, cwd, False, self._telemetry_provider)

    def _run_session_json_helper(self, session: UserSession, command_name: str, command_args: str, timeout_ms: int = 30000) -> dict:
        shared_temp_dir = os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "VmAgent")
        os.makedirs(shared_temp_dir, exist_ok=True)
        output_path = os.path.join(shared_temp_dir, f"vm-agent-{command_name}-{uuid.uuid4().hex}.json")
        helper = None

        try:
            helper = self._build_session_helper_process(command_name, f'{command_args} --out "{output_path}"')
            session.start_transient_process(helper)
            wait_result = win32event.WaitForSingleObject(helper.hProcess, timeout_ms)
            if wait_result != win32con.WAIT_OBJECT_0:
                raise TimeoutError(f"Timed out waiting for helper '{command_name}'")

            if not os.path.exists(output_path):
                exit_code = helper.get_exit_code()
                raise RuntimeError(f"Helper '{command_name}' did not produce an output file (exit code {exit_code})")

            with open(output_path, "r", encoding="utf-8") as handle:
                raw_payload = handle.read()

            if not raw_payload.strip():
                exit_code = helper.get_exit_code()
                raise RuntimeError(f"Helper '{command_name}' produced an empty result file (exit code {exit_code})")
            logging.info(f"Helper '{command_name}' produced output: {raw_payload}")
            try:
                payload = json.loads(raw_payload)
            except JSONDecodeError as exc:
                raise RuntimeError(f"Helper '{command_name}' produced invalid JSON: {exc}") from exc

            exit_code = helper.get_exit_code()
            if payload.get("status") != "completed":
                error = payload.get("error") or f"Helper '{command_name}' failed"
                if exit_code not in (0, None):
                    error = f"{error} [helper exit code {exit_code}]"
                raise RuntimeError(error)

            return payload
        finally:
            if helper is not None:
                helper.close()
            try:
                os.remove(output_path)
            except OSError:
                pass

    def _refresh_window_metadata_if_needed(self, force: bool = False):
        for session in self._sm.get_all_sessions():
            if session.session_id <= 0:
                continue
            if not force and not session.should_refresh_windows(self._window_refresh_interval_sec):
                continue
            if session.get_state() == SessionState.Down:
                continue

            try:
                payload = self._run_session_json_helper(session, "resolve-windows", "", timeout_ms=15000)
                session.apply_window_snapshot(payload.get("windows", {}))
                session.mark_windows_refreshed()
            except Exception as exc:
                session.mark_windows_refreshed()
                logging.debug(f"Failed to refresh window metadata for session {session.session_id}: {exc}")

    def _capture_process_screenshot_in_session(self, session: UserSession, pid: int, hwnd: int | None = None) -> dict:
        command_args = ["--target process"]
        if hwnd is not None:
            command_args.append(f"--hwnd {hwnd}")
        else:
            command_args.append(f"--pid {pid}")
        return self._run_session_json_helper(session, "capture-screenshot", " ".join(command_args))

    def _capture_desktop_screenshot_in_session(self, session: UserSession) -> dict:
        return self._run_session_json_helper(session, "capture-screenshot", "--target desktop")

    @register_listener(CaptureProcessScreenshotEvent, once=False)
    def _capture_process_screenshot(self, eventData: CaptureProcessScreenshotData):
        logging.info(
            "Capturing %s screenshot (pid=%s hwnd=%s session_id=%s request=%s)",
            eventData.target_type,
            eventData.pid,
            eventData.hwnd,
            eventData.session_id,
            eventData.request_id,
        )

        try:
            if eventData.target_type == "desktop":
                if eventData.session_id is None:
                    raise RuntimeError("Session id is required for desktop screenshot capture")

                session = self._find_session_by_id(eventData.session_id)
                if session is None:
                    raise RuntimeError("Unable to resolve target session for desktop screenshot")

                if session.session_id == 0:
                    capture = capture_desktop()
                    payload = {
                        "image_base64": capture.image_base64,
                        "image_format": capture.image_format,
                        "window_title": capture.window_title,
                    }
                else:
                    payload = self._capture_desktop_screenshot_in_session(session)
            else:
                if eventData.pid is None:
                    raise RuntimeError("PID is required for process screenshot capture")

                session = self._find_session_for_pid(eventData.pid)
                if session is None:
                    raise RuntimeError("Unable to resolve interactive session for this process")

                target_pid = eventData.pid
                target_hwnd = eventData.hwnd
                managed_process = session.get_process(eventData.pid)
                if session.session_id != 0 and (
                    managed_process is None or
                    managed_process.pinfo.capture_target_pid is None
                ):
                    try:
                        payload = self._run_session_json_helper(session, "resolve-windows", "", timeout_ms=15000)
                        session.apply_window_snapshot(payload.get("windows", {}))
                        session.mark_windows_refreshed()
                        managed_process = session.get_process(eventData.pid)
                    except Exception as refresh_exc:
                        logging.debug(
                            "On-demand window refresh failed for session %s before screenshot of PID %s: %s",
                            session.session_id,
                            eventData.pid,
                            refresh_exc,
                        )

                if managed_process and managed_process.pinfo.capture_target_pid:
                    target_pid = managed_process.pinfo.capture_target_pid
                    if target_hwnd is None and managed_process.pinfo.window_hwnd:
                        target_hwnd = managed_process.pinfo.window_hwnd

                if session.session_id == 0:
                    if target_hwnd is not None:
                        capture = capture_window_handle(target_hwnd)
                    else:
                        capture = capture_process_window(target_pid)
                    payload = {
                        "image_base64": capture.image_base64,
                        "image_format": capture.image_format,
                        "window_title": capture.window_title,
                        "hwnd": target_hwnd,
                    }
                else:
                    payload = self._capture_process_screenshot_in_session(session, target_pid, target_hwnd)
                    if target_hwnd is not None and payload.get("hwnd") is None:
                        payload["hwnd"] = target_hwnd

            self._client.send_event(ProcessScreenshotEvent(data=ProcessScreenshotData(
                agent_id=self._client.client_id,
                target_type=eventData.target_type,
                pid=eventData.pid,
                hwnd=payload.get("hwnd") if eventData.target_type == "process" else None,
                session_id=eventData.session_id,
                request_id=eventData.request_id,
                status="completed",
                image_base64=payload.get("image_base64"),
                image_format=payload.get("image_format", "png"),
                window_title=payload.get("window_title"),
                captured_at=int(time()),
            )))
        except Exception as exc:
            logging.exception(
                "Failed to capture %s screenshot (pid=%s hwnd=%s session_id=%s)",
                eventData.target_type,
                eventData.pid,
                eventData.hwnd,
                eventData.session_id,
            )
            self._client.send_event(ProcessScreenshotEvent(data=ProcessScreenshotData(
                agent_id=self._client.client_id,
                target_type=eventData.target_type,
                pid=eventData.pid,
                hwnd=eventData.hwnd,
                session_id=eventData.session_id,
                request_id=eventData.request_id,
                status="failed",
                error=str(exc),
                captured_at=int(time()),
            )))