"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ProcessReplica, ProcessWindowReplica } from "@/types/agent";

interface ProcessTreeProps {
  processes: Record<string, ProcessReplica>;
  highlightedPid?: number | null;
  highlightedTaskId?: string | null;
  onCaptureScreenshot?: (proc: ProcessReplica, windowEntry?: ProcessWindowReplica) => void;
}

interface ProcessTreeNode {
  pid: string;
  proc: ProcessReplica;
  children: ProcessTreeNode[];
}

const TREE_GRID_CLASS = "grid grid-cols-[minmax(0,_1fr)_110px_72px_96px_80px_56px_110px] gap-3";

function formatBytes(bytes?: number): string {
  if (bytes == null || bytes === 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
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
  if ((proc.windows?.length || 0) > 1) {
    return { text: `${proc.windows?.length || 0} windows detected`, cls: "text-cyan-300" };
  }
  if (proc.capture_target_kind === "child-window" && proc.window_title) {
    return { text: `Child window: ${proc.window_title}`, cls: "text-sky-300" };
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

function sortNodes(nodes: ProcessTreeNode[]) {
  nodes.sort((left, right) => {
    const exeCompare = (left.proc.exe || "").localeCompare(right.proc.exe || "");
    if (exeCompare !== 0) return exeCompare;
    return Number(left.pid) - Number(right.pid);
  });

  for (const node of nodes) {
    sortNodes(node.children);
  }
}

function buildProcessForest(processes: Record<string, ProcessReplica>): ProcessTreeNode[] {
  const nodes = new Map<string, ProcessTreeNode>();

  for (const [pid, proc] of Object.entries(processes)) {
    nodes.set(pid, { pid, proc, children: [] });
  }

  const roots: ProcessTreeNode[] = [];
  for (const node of nodes.values()) {
    const parentPid = node.proc.ppid != null ? String(node.proc.ppid) : null;
    if (parentPid && parentPid !== node.pid && nodes.has(parentPid)) {
      nodes.get(parentPid)!.children.push(node);
      continue;
    }
    roots.push(node);
  }

  sortNodes(roots);
  return roots;
}

function ProcessTreeRow({
  node,
  depth,
  highlightedPid,
  highlightedTaskId,
  onCaptureScreenshot,
}: {
  node: ProcessTreeNode;
  depth: number;
  highlightedPid?: number | null;
  highlightedTaskId?: string | null;
  onCaptureScreenshot?: (proc: ProcessReplica, windowEntry?: ProcessWindowReplica) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const status = resolveStatus(node.proc);
  const commandLine = node.proc.cmd || node.proc.args || "";
  const isMonitored = node.proc.is_monitored || commandLine.includes("--agent_id_1234");
  const hasChildren = node.children.length > 0;
  const rowRef = useRef<HTMLDivElement | null>(null);
  const isHighlighted =
    (highlightedTaskId != null && node.proc.task_id === highlightedTaskId) ||
    (highlightedPid != null && node.proc.pid === highlightedPid);
  const windowHint = resolveWindowHint(node.proc);

  useEffect(() => {
    if (isHighlighted && rowRef.current) {
      rowRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [isHighlighted]);

  return (
    <>
      <div
        ref={rowRef}
        className={`${TREE_GRID_CLASS} items-center border-b border-slate-800 px-3 py-2 text-sm hover:bg-slate-800/40 ${
          isMonitored ? "bg-purple-500/5" : ""
        } ${
          isHighlighted ? "bg-cyan-500/10 ring-1 ring-inset ring-cyan-400/40" : ""
        }`}
      >
        <div className="flex items-center gap-2 overflow-hidden" style={{ paddingLeft: `${depth * 18}px` }}>
          {hasChildren ? (
            <button
              type="button"
              onClick={() => setExpanded((current) => !current)}
              className="flex h-5 w-5 items-center justify-center rounded text-slate-500 transition-colors hover:bg-slate-700 hover:text-slate-300"
              title={expanded ? "Collapse children" : "Expand children"}
            >
              <svg
                className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-90" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="m9 5 7 7-7 7" />
              </svg>
            </button>
          ) : (
            <span className="inline-block h-5 w-5 shrink-0" />
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2 overflow-hidden">
              <span className="truncate text-slate-200" title={node.proc.exe_path || node.proc.exe}>
                {node.proc.exe || "—"}
              </span>
              {node.proc.task_id && (
                <span className="shrink-0 rounded-full bg-cyan-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-cyan-300">
                  Task
                </span>
              )}
              {isHighlighted && (
                <span className="shrink-0 rounded-full bg-cyan-400/20 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-cyan-200">
                  Focused
                </span>
              )}
              <span className="shrink-0 font-mono text-xs text-slate-500">PID {node.pid}</span>
              {node.proc.ppid != null && (
                <span className="shrink-0 font-mono text-xs text-slate-600">PPID {node.proc.ppid}</span>
              )}
            </div>
            {commandLine && (
              <p className="truncate font-mono text-[11px] text-slate-500" title={commandLine}>
                {commandLine}
              </p>
            )}
            {windowHint && (
              <p className={`truncate text-[11px] ${windowHint.cls}`} title={windowHint.text}>
                {windowHint.text}
              </p>
            )}
          </div>
        </div>
        <div className={`font-medium ${status.cls}`}>{status.text}</div>
        <div className="text-right font-mono text-slate-300">
          {node.proc.cpu_usage != null ? formatPercent(node.proc.cpu_usage) : "—"}
        </div>
        <div className="text-right font-mono text-slate-300">
          {formatBytes(node.proc.memory_usage?.working_set_size)}
        </div>
        <div className="text-right font-mono text-slate-300">{node.proc.handle_count ?? "—"}</div>
        <div className="text-center">
          {isMonitored && (
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-purple-500/20" title="Monitored (auto-restart)">
              <svg className="h-3 w-3 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75" />
              </svg>
            </span>
          )}
        </div>
        <div className="text-right">
          {onCaptureScreenshot && (
            <button
              type="button"
              onClick={() => onCaptureScreenshot(node.proc)}
              disabled={node.proc.has_window === false}
              className="rounded-md border border-slate-700 px-2.5 py-1 text-xs text-slate-300 transition-colors hover:border-cyan-500/60 hover:bg-cyan-500/10 hover:text-cyan-100"
            >
              Best
            </button>
          )}
          {node.proc.windows && node.proc.windows.length > 0 && onCaptureScreenshot && (
            <div className="mt-2 space-y-1">
              {node.proc.windows.map((windowEntry) => (
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
                    onClick={() => onCaptureScreenshot(node.proc, windowEntry)}
                    className="shrink-0 rounded-md border border-cyan-500/30 px-2 py-1 text-[11px] text-cyan-100 transition-colors hover:border-cyan-400 hover:bg-cyan-500/10"
                  >
                    Shot
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {expanded && node.children.map((child) => (
        <ProcessTreeRow
          key={child.pid}
          node={child}
          depth={depth + 1}
          highlightedPid={highlightedPid}
          highlightedTaskId={highlightedTaskId}
          onCaptureScreenshot={onCaptureScreenshot}
        />
      ))}
    </>
  );
}

export function ProcessTree({ processes, highlightedPid, highlightedTaskId, onCaptureScreenshot }: ProcessTreeProps) {
  const entries = Object.entries(processes);
  const roots = useMemo(() => buildProcessForest(processes), [processes]);

  if (entries.length === 0) {
    return <p className="text-sm italic text-slate-500">No processes</p>;
  }

  return (
    <div className="overflow-hidden rounded-lg border border-slate-700/70 bg-slate-900/30">
      <div className={`${TREE_GRID_CLASS} border-b border-slate-700 px-3 py-2 text-left text-xs uppercase tracking-wider text-slate-500`}>
        <div>Process Tree</div>
        <div>Status</div>
        <div className="text-right">CPU %</div>
        <div className="text-right">Memory</div>
        <div className="text-right">Handles</div>
        <div className="text-center">Mon.</div>
        <div className="text-right">Actions</div>
      </div>
      <div>
        {roots.map((node) => (
          <ProcessTreeRow
            key={node.pid}
            node={node}
            depth={0}
            highlightedPid={highlightedPid}
            highlightedTaskId={highlightedTaskId}
            onCaptureScreenshot={onCaptureScreenshot}
          />
        ))}
      </div>
    </div>
  );
}