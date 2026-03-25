"use client";

import { getAgentSessions, type AgentState, type ProcessReplica } from "@/types/agent";

interface MonitoredViewProps {
  agentId: string;
  state: AgentState;
}

function statusBadge(proc: ProcessReplica) {
  if (proc.is_running === true)
    return { text: "Running", cls: "bg-emerald-500/20 text-emerald-400" };
  if (proc.exit_code === 5)
    return { text: "Access Denied", cls: "bg-amber-500/20 text-amber-400" };
  if (proc.exit_code === 0)
    return { text: "Exited (0)", cls: "bg-slate-600/30 text-slate-400" };
  if (proc.exit_code != null)
    return { text: `Exited (${proc.exit_code})`, cls: "bg-red-500/20 text-red-400" };
  return { text: "Unknown", cls: "bg-slate-600/30 text-slate-400" };
}

function formatBytes(bytes?: number): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

interface MonitoredEntry {
  sessionKey: string;
  username?: string;
  pid: string;
  proc: ProcessReplica;
}

export function MonitoredView({ state }: MonitoredViewProps) {
  // Collect all monitored processes across sessions
  const monitored: MonitoredEntry[] = [];

  for (const [sessionKey, session] of getAgentSessions(state)) {
    for (const [pid, proc] of Object.entries(session.processes || {})) {
      if (proc.is_monitored || proc.args?.includes("--agent_id_1234")) {
        monitored.push({
          sessionKey,
          username: session.username,
          pid,
          proc,
        });
      }
    }
  }

  if (monitored.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-slate-500">
        <svg className="w-10 h-10 mb-3 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
        </svg>
        <p className="text-sm">No monitored processes</p>
        <p className="text-xs text-slate-600 mt-1">Start a monitored process to see it here</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
          Monitored Processes
        </h2>
        <span className="text-xs text-slate-500">
          {monitored.length} process{monitored.length !== 1 ? "es" : ""}
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {monitored.map((entry) => {
          const badge = statusBadge(entry.proc);
          return (
            <div
              key={`${entry.sessionKey}-${entry.pid}`}
              className="rounded-lg border border-purple-500/30 bg-purple-500/5 p-4"
            >
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-medium text-slate-200 text-sm">
                    {entry.proc.exe || "unknown"}
                  </h3>
                  <p className="text-xs text-slate-500 font-mono mt-0.5">
                    PID: {entry.pid}
                  </p>
                </div>
                <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${badge.cls}`}>
                  {badge.text}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-3 text-xs">
                <div>
                  <p className="text-slate-500">CPU</p>
                  <p className="font-mono text-slate-300">
                    {entry.proc.cpu_usage != null ? formatPercent(entry.proc.cpu_usage) : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-slate-500">Memory</p>
                  <p className="font-mono text-slate-300">
                    {formatBytes(entry.proc.memory_usage?.working_set_size)}
                  </p>
                </div>
                <div>
                  <p className="text-slate-500">Handles</p>
                  <p className="font-mono text-slate-300">
                    {entry.proc.handle_count ?? "—"}
                  </p>
                </div>
              </div>

              <div className="mt-3 pt-3 border-t border-slate-700/50 flex items-center justify-between text-xs">
                <span className="text-slate-500">
                  Session: <span className="text-slate-400">{entry.sessionKey}</span>
                  {entry.username && (
                    <span className="text-slate-400"> ({entry.username})</span>
                  )}
                </span>
                <div className="flex items-center gap-1.5">
                  <svg className="w-3.5 h-3.5 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
                  </svg>
                  <span className="text-purple-400">Auto-restart</span>
                </div>
              </div>

              {entry.proc.args && (
                <p className="mt-2 text-xs text-slate-600 font-mono truncate" title={entry.proc.args}>
                  {entry.proc.args}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
