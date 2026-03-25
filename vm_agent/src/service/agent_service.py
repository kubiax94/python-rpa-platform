from __future__ import annotations

import argparse
import json
import os
import sys
import traceback


def _run_capture_screenshot_helper(argv: list[str]) -> int:
    from vm_agent.src.utils.process_screenshot import capture_desktop, capture_process_window, capture_window_handle

    parser = argparse.ArgumentParser(prog="agent_service capture-screenshot")
    parser.add_argument("--target", choices=["process", "desktop"], default="process")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--hwnd", type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    result = {
        "status": "failed",
        "target_type": args.target,
        "pid": args.pid,
        "hwnd": args.hwnd,
        "image_format": "png",
        "image_base64": None,
        "window_title": None,
        "error": None,
    }

    try:
        if args.target == "desktop":
            capture = capture_desktop()
        else:
            if args.hwnd is not None:
                capture = capture_window_handle(args.hwnd)
            else:
                if args.pid is None:
                    raise ValueError("--pid or --hwnd is required for process screenshot capture")
                capture = capture_process_window(args.pid)
        result.update({
            "status": "completed",
            "image_base64": capture.image_base64,
            "image_format": capture.image_format,
            "window_title": capture.window_title,
        })
    except Exception as exc:
        result["error"] = f"{exc}\n{traceback.format_exc()}"

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle)

    return 0


def _run_resolve_windows_helper(argv: list[str]) -> int:
    from vm_agent.src.utils.process_screenshot import build_window_snapshot

    parser = argparse.ArgumentParser(prog="agent_service resolve-windows")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    result = {
        "status": "failed",
        "windows": {},
        "error": None,
    }

    try:
        result["windows"] = build_window_snapshot()
        result["status"] = "completed"
    except Exception as exc:
        result["error"] = f"{exc}\n{traceback.format_exc()}"

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(result, handle)

    return 0


def _run_service(argv: list[str]) -> int:
    import threading
    import win32event
    import win32service
    import win32serviceutil
    import servicemanager

    from vm_agent.src.core.agent import VmAgent

    class VmAgentService(win32serviceutil.ServiceFramework):
        _svc_name_ = "VmAgent"
        _svc_display_name_ = "VM Agent"
        _svc_description_ = "VM Agent service (LocalSystem) with process management."

        def __init__(self, args):
            super().__init__(args)
            self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)
            self._agent: VmAgent | None = None
            self._stop_flag = threading.Event()
            self._thread: threading.Thread | None = None

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self._stop_flag.set()
            self._agent.stop()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=10)
            win32event.SetEvent(self.hWaitStop)

        def SvcDoRun(self):
            servicemanager.LogInfoMsg("VmAgent service starting...")
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            try:
                self._main()
            except Exception as e:
                servicemanager.LogErrorMsg(f"VmAgent crashed: {e!r}")
                raise

        def _main(self):
            try:
                print("Starting VmAgent service main loop")
                self._agent = VmAgent()
                self._thread = threading.Thread(target=self._agent.run, daemon=True)
                self._thread.start()

                win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)
                servicemanager.LogInfoMsg("VmAgent service stopped")
            except Exception as e:
                servicemanager.LogErrorMsg(f"VmAgent crashed: {e!r}")
                raise

    if len(argv) == 0:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(VmAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(VmAgentService)

    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "capture-screenshot":
        raise SystemExit(_run_capture_screenshot_helper(sys.argv[2:]))

    if len(sys.argv) > 1 and sys.argv[1] == "resolve-windows":
        raise SystemExit(_run_resolve_windows_helper(sys.argv[2:]))

    raise SystemExit(_run_service(sys.argv[1:]))