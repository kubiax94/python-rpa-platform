"use client";

import { useEffect, useRef } from "react";
import type { ProcessReplica, ProcessWindowReplica } from "@/types/agent";

interface ProcessTableProps {
  processes: Record<string, ProcessReplica>;
  highlightedPid?: number | null;
  highlightedTaskId?: string | null;
  onCaptureScreenshot?: (proc: ProcessReplica, windowEntry?: ProcessWindowReplica) => void;
}

function formatBytes(bytes?: number): string {
  if (bytes == null || bytes === 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatIoRate(proc: ProcessReplica): string {
  const read = proc.io_counters?.read_bps;
  const write = proc.io_counters?.write_bps;
  if ((read == null || read === 0) && (write == null || write === 0)) return "—";
  return `R ${formatBytes(read)} / W ${formatBytes(write)}`;
}

function resolveStatus(proc: ProcessReplica): { text: string; cls: string } {
  if (proc.is_running === true) return { text: "Running", cls: "text-emerald-400" };
  if (proc.exit_code === 259) return { text: "Running", cls: "text-emerald-400" };
  if (proc.exit_code === 5) return { text: "Access Denied", cls: "text-amber-400" };
  if (proc.exit_code === 0) return { text: "Exited (0)", cls: "text-slate-400" };
  if (proc.exit_code != null) return { text: `Exited (${proc.exit_code})`, cls: "text-red-400" };
  return { text: "Unknown", cls: "text-slate-500" };
}

function resolveWindowHint(proc: ProcessReplica): { text: string; cls: string } | null {
  if (proc.capture_target_kind === "console-host" && proc.capture_target_pid != null) {
    return { text: `Console host PID ${proc.capture_target_pid}`, cls: "text-amber-300" };
  }
  if (proc.capture_target_kind === "child-window" && proc.window_title) {
    return { text: `Child window: ${proc.window_title}`, cls: "text-sky-300" };
  }
  if ((proc.windows?.length || 0) > 1) {
    return { text: `${proc.windows?.length || 0} windows detected`, cls: "text-cyan-300" };
  }
  if (proc.capture_target_kind === "child-window") {
    return { text: "Child window detected", cls: "text-sky-300" };
  }
  if (proc.has_window && proc.window_title) {
    return { text: proc.window_title, cls: "text-slate-500" };
  }
  if (proc.has_window) {
    return { text: "Window detected", cls: "text-emerald-300" };
  }
  return { text: "No window detected", cls: "text-slate-600" };
}

function formatWindowLabel(windowEntry: ProcessWindowReplica): string {
  const title = windowEntry.window_title?.trim() || "Untitled window";
  const kind = windowEntry.window_kind === "child-window" ? "child" : "top";
  return `${title} • HWND ${windowEntry.hwnd} • ${kind}`;
}

export function ProcessTable({ processes, highlightedPid, highlightedTaskId, onCaptureScreenshot }: ProcessTableProps) {
  const entries = Object.entries(processes);
  const highlightRef = useRef<HTMLTableRowElement | null>(null);

  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [highlightedPid, highlightedTaskId, processes]);

  if (entries.length === 0) {
    return <p className="text-slate-500 text-sm italic">No processes</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-700">
            <th className="pb-2 pr-4">PID</th>
            <th className="pb-2 pr-4">Executable</th>
            <th className="pb-2 pr-4">Status</th>
            <th className="pb-2 pr-4 text-right">CPU %</th>
            <th className="pb-2 pr-4 text-right">Memory</th>
            <th className="pb-2 pr-4 text-right">I/O</th>
            <th className="pb-2 pr-4 text-right">Handles</th>
            <th className="pb-2 text-center">Mon.</th>
            {onCaptureScreenshot && <th className="pb-2 pl-4 text-right">Actions</th>}
          </tr>
        </thead>
        <tbody>
          {entries.map(([pid, proc]) => {
            const isMonitored = proc.is_monitored || proc.args?.includes("--agent_id_1234");
            const status = resolveStatus(proc);
            const memory = proc.memory_usage?.working_set_size;
            const isHighlighted =
              (highlightedTaskId != null && proc.task_id === highlightedTaskId) ||
              (highlightedPid != null && proc.pid === highlightedPid);
            const windowHint = resolveWindowHint(proc);
            return (
              <tr
                key={pid}
                ref={isHighlighted ? highlightRef : null}
                className={`border-b border-slate-800 hover:bg-slate-800/50 transition-colors ${
                  isMonitored ? "bg-purple-500/5" : ""
                } ${
                  isHighlighted ? "bg-cyan-500/10 ring-1 ring-inset ring-cyan-400/40" : ""
                }`}
              >
                <td className="py-2 pr-4 font-mono text-slate-400">{pid}</td>
                <td className="py-2 pr-4 text-slate-200" title={proc.exe_path}>
                  <div>
                    <div className="flex items-center gap-2">
                      <span>{proc.exe || "—"}</span>
                      {proc.task_id && (
                        <span className="rounded-full bg-cyan-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-cyan-300">
                          Task
                        </span>
                      )}
                      {isHighlighted && (
                        <span className="rounded-full bg-cyan-400/20 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-cyan-200">
                          Focused
                        </span>
                      )}
                    </div>
                    {windowHint && (
                      <p className={`mt-0.5 text-[11px] ${windowHint.cls}`} title={windowHint.text}>
                        {windowHint.text}
                      </p>
                    )}
                    {proc.windows && proc.windows.length > 0 && onCaptureScreenshot && (
                      <div className="mt-2 space-y-1">
                        {proc.windows.map((windowEntry) => (
                          <div key={windowEntry.hwnd} className="flex items-center justify-between gap-2 rounded-md border border-slate-800/80 bg-slate-950/40 px-2 py-1">
                            <div className="min-w-0">
                              <p className="truncate text-[11px] text-slate-300" title={formatWindowLabel(windowEntry)}>
                                {windowEntry.window_title || "Untitled window"}
                              </p>
                              <p className="truncate text-[10px] uppercase tracking-wider text-slate-600">
                                HWND {windowEntry.hwnd}
                                {windowEntry.window_kind === "child-window" ? " • child" : " • top"}
                                {windowEntry.is_primary ? " • primary" : ""}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => onCaptureScreenshot(proc, windowEntry)}
                              className="shrink-0 rounded-md border border-cyan-500/30 px-2 py-1 text-[11px] text-cyan-100 transition-colors hover:border-cyan-400 hover:bg-cyan-500/10"
                            >
                              Shot
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </td>
                <td className={`py-2 pr-4 font-medium ${status.cls}`}>
                  {status.text}
                </td>
                <td className="py-2 pr-4 text-right font-mono text-slate-300">
                  {proc.cpu_usage != null ? formatPercent(proc.cpu_usage) : "—"}
                </td>
                <td className="py-2 pr-4 text-right font-mono text-slate-300">
                  {formatBytes(memory)}
                </td>
                <td className="py-2 pr-4 text-right font-mono text-slate-300">
                  {formatIoRate(proc)}
                </td>
                <td className="py-2 pr-4 text-right font-mono text-slate-300">
                  {proc.handle_count ?? "—"}
                </td>
                <td className="py-2 text-center">
                  {isMonitored && (
                    <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-purple-500/20" title="Monitored (auto-restart)">
                      <svg className="w-3 h-3 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75" />
                      </svg>
                    </span>
                  )}
                </td>
                {onCaptureScreenshot && (
                  <td className="py-2 pl-4 text-right">
                    <button
                      type="button"
                      onClick={() => onCaptureScreenshot(proc)}
                      disabled={proc.has_window === false}
                      className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 transition-colors hover:border-cyan-500/60 hover:bg-cyan-500/10 hover:text-cyan-100"
                    >
                      Best
                    </button>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
