"use client";

import { getAgentConnection, getAgentMetrics, getAgentSessions, getSessionProcessCount, isAgentOnline, type AgentState } from "@/types/agent";

interface AgentCardProps {
  agentId: string;
  state: AgentState;
  connected: boolean;
  selected: boolean;
  onClick: () => void;
  onDeploy?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}

export function AgentCard({ agentId, state, connected, selected, onClick, onDeploy, onEdit, onDelete }: AgentCardProps) {
  const sessions = getAgentSessions(state);
  const agentOnline = isAgentOnline(state);
  const metrics = getAgentMetrics(state);
  const connection = getAgentConnection(state);
  const sessionCount = sessions.length;
  const processCount = sessions.reduce(
    (sum, [, session]) => sum + getSessionProcessCount(session),
    0
  );
  const isPrepared = !agentOnline && connection?.source === "registry";
  const statusLabel = agentOnline ? "online" : isPrepared ? "prepared" : connected ? "offline" : "cached";
  const statusBadgeClass = agentOnline
    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
    : isPrepared
      ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
      : "border-slate-600 bg-slate-700/50 text-slate-300";

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onClick();
        }
      }}
      className={`w-full cursor-pointer text-left p-4 rounded-lg border transition-all focus:outline-none focus:ring-2 focus:ring-cyan-500/60 ${
        selected
          ? "border-blue-500 bg-blue-500/10"
          : "border-slate-700 bg-slate-800/50 hover:border-slate-600"
      }`}
    >
      <div className="flex items-start justify-between mb-2 gap-3">
        <h3 className="font-mono text-sm font-medium text-slate-200 truncate" title={agentId}>
          {agentId.substring(0, 12)}...
        </h3>
        <div className="flex items-center gap-2">
          {(onEdit || onDelete) && (
            <div className="flex items-center gap-1">
              {onEdit && (
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onEdit();
                  }}
                  className="rounded-md border border-slate-600 px-2 py-1 text-[11px] font-medium text-slate-200 hover:border-slate-500 hover:bg-slate-700/60"
                >
                  Edit
                </button>
              )}
              {onDelete && (
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onDelete();
                  }}
                  className="rounded-md border border-red-500/30 px-2 py-1 text-[11px] font-medium text-red-200 hover:bg-red-500/10"
                >
                  Delete
                </button>
              )}
            </div>
          )}
          <div className={`w-2 h-2 rounded-full ${agentOnline ? "bg-emerald-400" : isPrepared ? "bg-amber-300" : "bg-slate-500"}`} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span className={`rounded-full border px-2 py-0.5 font-medium uppercase tracking-wide ${statusBadgeClass}`}>{statusLabel}</span>
        {isPrepared && <span className="text-amber-200">not connected yet</span>}
        <span>{sessionCount} session{sessionCount !== 1 ? "s" : ""}</span>
        <span>{processCount} process{processCount !== 1 ? "es" : ""}</span>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 border-t border-slate-700/70 pt-3">
        <span className="truncate text-xs text-slate-500" title={metrics?.hostname || undefined}>
          {metrics?.hostname || "hostname unknown"}
        </span>
        {onDeploy && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onDeploy();
            }}
            className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1 text-xs font-medium text-cyan-200 hover:bg-cyan-500/20"
          >
            Deploy
          </button>
        )}
      </div>
    </div>
  );
}
