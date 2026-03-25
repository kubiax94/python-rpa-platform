"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { Task } from "@/hooks/useTaskAPI";

const STATUS_CLASS: Record<string, string> = {
  queued: "bg-slate-500/20 text-slate-200",
  running: "bg-amber-500/20 text-amber-300",
  completed: "bg-emerald-500/20 text-emerald-300",
  failed: "bg-red-500/20 text-red-300",
  cancelled: "bg-slate-600/20 text-slate-300",
  timeout: "bg-orange-500/20 text-orange-300",
};

function relativeTime(ts: number | null) {
  if (!ts) return "now";
  const diff = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

interface ActiveTaskNotificationsProps {
  tasks: Task[];
  onOpenTasks?: () => void;
  label?: string;
}

export function ActiveTaskNotifications({ tasks, onOpenTasks, label = "Command Tracker" }: ActiveTaskNotificationsProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const activeTasks = useMemo(
    () => tasks.filter((task) => task.status === "running" || task.status === "queued"),
    [tasks]
  );

  const visibleTasks = activeTasks.length > 0 ? activeTasks.slice(0, 6) : tasks.slice(0, 6);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="inline-flex items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-sm text-cyan-100 transition-colors hover:border-cyan-400/50 hover:bg-cyan-500/15"
      >
        <span className={`h-2 w-2 rounded-full ${activeTasks.length > 0 ? "bg-amber-400 animate-pulse" : "bg-slate-500"}`} />
        <span>{label}</span>
        <span className="rounded-full bg-slate-900/70 px-2 py-0.5 text-xs font-semibold text-slate-200">
          {activeTasks.length}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-40 mt-2 w-[26rem] overflow-hidden rounded-xl border border-slate-700 bg-slate-900/95 shadow-2xl shadow-black/40 backdrop-blur">
          <div className="flex items-center justify-between border-b border-slate-700 px-4 py-3">
            <div>
              <h3 className="text-sm font-semibold text-slate-100">Task Notifications</h3>
              <p className="text-xs text-slate-500">
                {activeTasks.length > 0
                  ? `${activeTasks.length} command task${activeTasks.length !== 1 ? "s" : ""} still running`
                  : "No active command tasks right now"}
              </p>
            </div>
            {onOpenTasks && (
              <button
                type="button"
                onClick={() => {
                  setOpen(false);
                  onOpenTasks();
                }}
                className="rounded-md bg-slate-800 px-2.5 py-1 text-xs text-slate-200 transition-colors hover:bg-slate-700"
              >
                Open Tasks
              </button>
            )}
          </div>

          <div className="max-h-[24rem] overflow-y-auto p-2">
            {visibleTasks.length === 0 ? (
              <div className="rounded-lg border border-dashed border-slate-700 px-4 py-8 text-center text-sm text-slate-500">
                No task activity to show yet.
              </div>
            ) : (
              visibleTasks.map((task) => (
                <div
                  key={task.id}
                  className="mb-2 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-3 last:mb-0"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-100">
                        {task.name || task.id.substring(0, 12)}
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                        <span className="font-mono text-slate-400">{task.agent_id.substring(0, 12)}</span>
                        <span>{relativeTime(task.started_at ?? task.created_at)}</span>
                      </div>
                    </div>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_CLASS[task.status] || "bg-slate-700 text-slate-200"}`}>
                      {task.status}
                    </span>
                  </div>
                  {(task.error || task.pid != null) && (
                    <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
                      {task.pid != null && <span>PID {task.pid}</span>}
                      {task.error && <span className="truncate text-red-300">{task.error}</span>}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}