"use client";

import { useState } from "react";
import { API_BASE, fetchJSON, sendJSON } from "@/lib/auth";
import type { Task } from "@/hooks/useTaskAPI";
import { getAgentMetrics, isAgentOnline, type AgentsMap } from "@/types/agent";
import { ActiveTaskNotifications } from "./ActiveTaskNotifications";
import { AgentCard } from "./AgentCard";
import { DeployAgentDialog } from "./DeployAgentDialog";

interface AgentListProps {
  agents: AgentsMap;
  connected: boolean;
  tasks: Task[];
  canPrepareDeployment: boolean;
  canManageAgents: boolean;
  onSelectAgent: (agentId: string) => void;
  onOpenTaskTracker: () => void;
  onAgentsChanged?: () => Promise<void> | void;
}

export function AgentList({ agents, connected, tasks, canPrepareDeployment, canManageAgents, onSelectAgent, onOpenTaskTracker, onAgentsChanged }: AgentListProps) {
  const agentIds = Object.keys(agents);
  const onlineCount = agentIds.filter((id) => isAgentOnline(agents[id])).length;
  const [deployState, setDeployState] = useState<{ agentId?: string | null; hostname?: string | null; displayName?: string | null } | null>(null);

  const handleEditAgent = async (agentId: string) => {
    const currentHostname = getAgentMetrics(agents[agentId])?.hostname || agentId;
    const nextHostname = window.prompt("Agent hostname / FQDN", currentHostname)?.trim();
    if (!nextHostname) {
      return;
    }

    const nextDisplayName = window.prompt("Agent display name", currentHostname)?.trim() || nextHostname;
    await sendJSON(`${API_BASE}/api/agent-registry/${encodeURIComponent(agentId)}`, "PATCH", {
      hostname: nextHostname,
      display_name: nextDisplayName,
    });
    await onAgentsChanged?.();
  };

  const handleDeleteAgent = async (agentId: string) => {
    const confirmed = window.confirm(`Delete agent ${agentId}?`);
    if (!confirmed) {
      return;
    }

    await fetchJSON(`${API_BASE}/api/agent-registry/${encodeURIComponent(agentId)}`, { method: "DELETE" });
    await onAgentsChanged?.();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-slate-100">Agents</h1>
        <div className="flex items-center gap-3">
          {canPrepareDeployment && (
            <button
              type="button"
              onClick={() => setDeployState({})}
              className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-sm text-cyan-100 transition-colors hover:bg-cyan-500/20"
            >
              Prepare Deploy
            </button>
          )}
          <ActiveTaskNotifications tasks={tasks} onOpenTasks={onOpenTaskTracker} />
          <span className="text-sm text-slate-500">
            {connected ? `${onlineCount}/${agentIds.length} online` : `${agentIds.length} cached`}
          </span>
        </div>
      </div>

      {agentIds.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-slate-500">
          <svg className="w-12 h-12 mb-3 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-13.5 0a3 3 0 0 1-3-3m3 3h13.5m-13.5-6a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0-6h13.5a3 3 0 1 0 0 6m-13.5 0h13.5m-13.5 0a3 3 0 0 1-3 3" />
          </svg>
          <p className="text-sm">{connected ? "Waiting for agents to connect..." : "Not connected to server"}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agentIds.map((id) => (
            <AgentCard
              key={id}
              agentId={id}
              state={agents[id]}
              connected={connected}
              selected={false}
              onClick={() => onSelectAgent(id)}
              onEdit={canManageAgents ? () => { void handleEditAgent(id); } : undefined}
              onDelete={canManageAgents ? () => { void handleDeleteAgent(id); } : undefined}
              onDeploy={canPrepareDeployment ? () => {
                const metrics = getAgentMetrics(agents[id]);
                setDeployState({
                  agentId: id,
                  hostname: metrics?.hostname || id,
                  displayName: metrics?.hostname || id,
                });
              } : undefined}
            />
          ))}
        </div>
      )}

      <DeployAgentDialog
        open={deployState !== null}
        canPrepareDeployment={canPrepareDeployment}
        initialAgentId={deployState?.agentId}
        initialHostname={deployState?.hostname}
        initialDisplayName={deployState?.displayName}
        onClose={() => setDeployState(null)}
      />
    </div>
  );
}
