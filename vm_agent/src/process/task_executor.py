"""
TaskExecutor — runs PowerShell scripts on the agent and streams output back to server.

Flow:
    1. Receives execute_task event
    2. Writes script to temp file
    3. Creates ManagedTask and starts it through the resolved session
    4. Redirects stdout/stderr to temp files
    5. Tails file growth in timed, size-limited batches
    6. On completion, sends task_status event (completed/failed/timeout)
    7. Handles cancel_task by terminating the task process
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import win32api
import win32con
import win32event
import win32file
import win32process
import win32security

from shared.network.events.example_event import (
    ExecuteTaskData, TaskOutputData, TaskOutputEvent,
    TaskStatusData, TaskStatusEvent,
)
from vm_agent.src.process.managed_task import ManagedTask

if TYPE_CHECKING:
    from vm_agent.src.core.user_session import UserSession
    from vm_agent.src.core.user_session import UserSession

logger = logging.getLogger(__name__)


class TaskExecution:
    """Tracks a single running task."""
    __slots__ = (
        "task_id", "session", "task_process", "stdout_handle", "stderr_handle", "wait_handle", "script_path", "seq", "cancelled",
        "stdout_path", "stderr_path", "stdout_offset", "stderr_offset",
        "stdout_tail_reads", "stderr_tail_reads", "stdout_batches_sent", "stderr_batches_sent",
        "stdout_bytes_read", "stderr_bytes_read", "stdout_bytes_sent", "stderr_bytes_sent",
    )

    def __init__(self, task_id: str, session: UserSession, task_process: ManagedTask,
                 stdout_handle, stderr_handle, wait_handle, stdout_path: str, stderr_path: str, script_path: str):
        self.task_id = task_id
        self.session = session
        self.task_process = task_process
        self.stdout_handle = stdout_handle
        self.stderr_handle = stderr_handle
        self.wait_handle = wait_handle
        self.stdout_path = stdout_path
        self.stderr_path = stderr_path
        self.script_path = script_path
        self.seq = 0
        self.cancelled = False
        self.stdout_offset = 0
        self.stderr_offset = 0
        self.stdout_tail_reads = 0
        self.stderr_tail_reads = 0
        self.stdout_batches_sent = 0
        self.stderr_batches_sent = 0
        self.stdout_bytes_read = 0
        self.stderr_bytes_read = 0
        self.stdout_bytes_sent = 0
        self.stderr_bytes_sent = 0


class TaskExecutor:
    """Manages task execution on the agent. One instance per agent."""

    OUTPUT_FLUSH_INTERVAL_SECONDS = 0.25
    OUTPUT_MAX_BATCH_BYTES = 32 * 1024

    def __init__(self, send_event_fn):
        """
        Args:
            send_event_fn: callable that sends a NetworkEvent to the server.
        """
        self._send = send_event_fn
        self._running: dict[str, TaskExecution] = {}  # task_id → TaskExecution
        self._scripts_dir = Path(tempfile.gettempdir()) / "vm_agent_tasks"
        self._scripts_dir.mkdir(parents=True, exist_ok=True)

    async def execute(self, data: ExecuteTaskData, session: UserSession | None = None):
        """Start executing a task. Called when execute_task event is received."""
        task_id = data.task_id

        if task_id in self._running:
            logger.warning(f"Task {task_id} already running, ignoring")
            return

        if session is None:
            raise RuntimeError("TaskExecutor.execute requires a resolved session")

        # Write script to temp file
        script_path = self._scripts_dir / f"{task_id}.ps1"
        script_path.write_text(data.script, encoding="utf-8")
        logger.info(f"Script exists: {script_path.exists()}")
        
        logger.info(f"Executing task {task_id}: {len(data.script)} chars, timeout={data.timeout_sec}s")

        execution: TaskExecution | None = None
        try:
            execution = self._start_managed_task(data, session, script_path)
            self._running[task_id] = execution
            self._send(TaskStatusEvent(data=TaskStatusData(
                task_id=task_id,
                status="running",
                pid=execution.task_process.pid,
            )))
            await self._run_with_timeout(execution, data.timeout_sec)

        except Exception as e:
            logger.error(f"Task {task_id} launch error: {e}")
            self._send(TaskStatusEvent(data=TaskStatusData(
                task_id=task_id, status="failed", error=str(e)
            )))
        finally:
            self._running.pop(task_id, None)
            if execution is not None:
                for handle in (execution.stdout_handle, execution.stderr_handle, execution.wait_handle):
                    if handle:
                        try:
                            win32api.CloseHandle(handle)
                        except Exception:
                            pass
            if execution is not None and execution.task_process.pid is not None:
                try:
                    execution.session.stop_process(execution.task_process.pid, force=False)
                except Exception as stop_error:
                    logger.debug(f"Task {task_id} stop_process cleanup error: {stop_error}")
            if execution is not None:
                for output_path in (execution.stdout_path, execution.stderr_path):
                    try:
                        Path(output_path).unlink(missing_ok=True)
                    except OSError:
                        pass
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

    async def cancel(self, task_id: str):
        """Cancel a running task."""
        execution = self._running.get(task_id)
        if not execution:
            logger.warning(f"Cannot cancel task {task_id}: not running")
            return

        execution.cancelled = True
        try:
            if execution.task_process.hProcess:
                win32process.TerminateProcess(execution.task_process.hProcess, 1)
        except Exception as e:
            logger.warning(f"Error terminating task {task_id}: {e}")

        logger.info(f"Task {task_id} cancelled")
        self._log_output_stats(execution, "cancelled")
        self._send(TaskStatusEvent(data=TaskStatusData(
            task_id=task_id, status="cancelled", pid=execution.task_process.pid
        )))

    def _start_managed_task(self, data: ExecuteTaskData, session: UserSession, script_path: Path) -> TaskExecution:
        stdout_w = stderr_w = wait_handle = None
        stdout_path = self._scripts_dir / f"{data.task_id}.stdout.log"
        stderr_path = self._scripts_dir / f"{data.task_id}.stderr.log"

        try:
            sa = win32security.SECURITY_ATTRIBUTES()
            sa.bInheritHandle = True

            stdout_w = win32file.CreateFile(
                str(stdout_path),
                win32con.GENERIC_WRITE,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                sa,
                win32con.CREATE_ALWAYS,
                win32con.FILE_ATTRIBUTE_NORMAL,
                None,
            )
            stderr_w = win32file.CreateFile(
                str(stderr_path),
                win32con.GENERIC_WRITE,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
                sa,
                win32con.CREATE_ALWAYS,
                win32con.FILE_ATTRIBUTE_NORMAL,
                None,
            )

            task_process = ManagedTask(
                task_id=data.task_id,
                script_path=str(script_path),
                cwd=data.cwd or "",
                telemetry_provider=session.telemetry,
            )
            task_process.attach_output_handles(stdout_w, stderr_w)
            session.start_process(task_process)
            wait_handle = win32api.OpenProcess(
                win32con.SYNCHRONIZE | getattr(win32con, "PROCESS_QUERY_LIMITED_INFORMATION", 0x1000),
                False,
                task_process.pid,
            )

            logger.info(
                f"Task {data.task_id} launched in session {session.get_session_name()} (PID={task_process.pid})"
            )

            return TaskExecution(
                data.task_id,
                session,
                task_process,
                stdout_w,
                stderr_w,
                wait_handle,
                str(stdout_path),
                str(stderr_path),
                str(script_path),
            )
        except Exception:
            for handle_name in ("stdout_w", "stderr_w", "wait_handle"):
                handle = locals().get(handle_name)
                if handle:
                    win32api.CloseHandle(handle)
            raise

    async def _run_with_timeout(self, execution: TaskExecution, timeout_sec: int):
        """Run the process, stream output, enforce timeout."""
        task_id = execution.task_id
        wait_handle = execution.wait_handle

        stdout_task = asyncio.create_task(self._tail_output_file(execution, "stdout"))
        stderr_task = asyncio.create_task(self._tail_output_file(execution, "stderr"))
        loop = asyncio.get_event_loop()

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    loop.run_in_executor(None, win32event.WaitForSingleObject,
                                         wait_handle, win32event.INFINITE),
                    stdout_task,
                    stderr_task,
                ),
                timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            logger.warning(f"Task {task_id} timed out after {timeout_sec}s")
            try:
                if execution.task_process.hProcess:
                    win32process.TerminateProcess(execution.task_process.hProcess, 1)
            except Exception:
                pass
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            await self._flush_all_outputs(execution)
            self._log_output_stats(execution, "timeout")
            self._send(TaskStatusEvent(data=TaskStatusData(
                task_id=task_id, status="timeout", pid=execution.task_process.pid
            )))
            return

        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        await self._flush_all_outputs(execution)

        if execution.cancelled:
            return  # Already reported cancelled

        exit_code = win32process.GetExitCodeProcess(wait_handle)
        status = "completed" if exit_code == 0 else "failed"
        logger.info(f"Task {task_id} finished: {status} (exit_code={exit_code})")
        self._log_output_stats(execution, status)

        self._send(TaskStatusEvent(data=TaskStatusData(
            task_id=task_id, status=status, pid=execution.task_process.pid, exit_code=exit_code
        )))

    async def _tail_output_file(self, execution: TaskExecution, stream: str):
        while True:
            drained = await self._flush_output_stream(execution, stream)

            wait_result = await asyncio.get_event_loop().run_in_executor(
                None,
                win32event.WaitForSingleObject,
                execution.wait_handle,
                int(self.OUTPUT_FLUSH_INTERVAL_SECONDS * 1000),
            )
            if wait_result == win32con.WAIT_OBJECT_0:
                if not drained:
                    break

    async def _flush_all_outputs(self, execution: TaskExecution):
        while await self._flush_output_stream(execution, "stdout"):
            pass
        while await self._flush_output_stream(execution, "stderr"):
            pass

    async def _flush_output_stream(self, execution: TaskExecution, stream: str):
        if stream == "stdout":
            file_path = execution.stdout_path
            offset = execution.stdout_offset
        else:
            file_path = execution.stderr_path
            offset = execution.stderr_offset

        try:
            with open(file_path, "rb") as log_file:
                log_file.seek(offset)
                chunk = log_file.read(self.OUTPUT_MAX_BATCH_BYTES)
                new_offset = log_file.tell()
        except OSError:
            return False

        if not chunk:
            return False

        data_bytes = len(chunk)
        data = chunk.decode("utf-8", errors="replace")

        if stream == "stdout":
            execution.stdout_offset = new_offset
            execution.stdout_tail_reads += 1
            execution.stdout_bytes_read += data_bytes
        else:
            execution.stderr_offset = new_offset
            execution.stderr_tail_reads += 1
            execution.stderr_bytes_read += data_bytes

        if stream == "stdout":
            execution.stdout_batches_sent += 1
            execution.stdout_bytes_sent += data_bytes
        else:
            execution.stderr_batches_sent += 1
            execution.stderr_bytes_sent += data_bytes

        execution.seq += 1
        self._send(TaskOutputEvent(data=TaskOutputData(
            task_id=execution.task_id,
            stream=stream,
            data=data,
            seq=execution.seq
        )))
        return True

    def _log_output_stats(self, execution: TaskExecution, reason: str):
        logger.info(
            "Task %s output stats after %s: stdout tail_reads=%s batches=%s read_bytes=%s sent_bytes=%s; stderr tail_reads=%s batches=%s read_bytes=%s sent_bytes=%s",
            execution.task_id,
            reason,
            execution.stdout_tail_reads,
            execution.stdout_batches_sent,
            execution.stdout_bytes_read,
            execution.stdout_bytes_sent,
            execution.stderr_tail_reads,
            execution.stderr_batches_sent,
            execution.stderr_bytes_read,
            execution.stderr_bytes_sent,
        )
