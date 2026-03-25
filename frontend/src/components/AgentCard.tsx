"use client";

import { getAgentMetrics, getAgentSessions, getSessionProcessCount, isAgentOnline, type AgentState } from "@/types/agent";

interface AgentCardProps {
  agentId: string;
  state: AgentState;
  connected: boolean;
  selected: boolean;
  onClick: () => void;
  onDeploy: () => void;
}

export function AgentCard({ agentId, state, connected, selected, onClick, onDeploy }: AgentCardProps) {
  const sessions = getAgentSessions(state);
  const agentOnline = isAgentOnline(state);
  const metrics = getAgentMetrics(state);
  const sessionCount = sessions.length;
  const processCount = sessions.reduce(
    (sum, [, session]) => sum + getSessionProcessCount(session),
    0
  );

  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-4 rounded-lg border transition-all ${
        selected
          ? "border-blue-500 bg-blue-500/10"
          : "border-slate-700 bg-slate-800/50 hover:border-slate-600"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <h3 className="font-mono text-sm font-medium text-slate-200 truncate" title={agentId}>
          {agentId.substring(0, 12)}...
        </h3>
        <div className={`w-2 h-2 rounded-full ${agentOnline ? "bg-emerald-400" : "bg-slate-500"}`} />
      </div>
      <div className="flex gap-4 text-xs text-slate-400">
        <span>{agentOnline ? "online" : connected ? "offline" : "cached"}</span>
        <span>{sessionCount} session{sessionCount !== 1 ? "s" : ""}</span>
        <span>{processCount} process{processCount !== 1 ? "es" : ""}</span>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3 border-t border-slate-700/70 pt-3">
        <span className="truncate text-xs text-slate-500" title={metrics?.hostname || undefined}>
          {metrics?.hostname || "hostname unknown"}
        </span>
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
      </div>
    </button>
  );
}
