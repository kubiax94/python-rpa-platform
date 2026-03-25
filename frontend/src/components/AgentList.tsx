"use client";

import type { Task } from "@/hooks/useTaskAPI";
import { isAgentOnline, type AgentsMap } from "@/types/agent";
import { ActiveTaskNotifications } from "./ActiveTaskNotifications";
import { AgentCard } from "./AgentCard";

interface AgentListProps {
  agents: AgentsMap;
  connected: boolean;
  tasks: Task[];
  onSelectAgent: (agentId: string) => void;
  onOpenTaskTracker: () => void;
}

export function AgentList({ agents, connected, tasks, onSelectAgent, onOpenTaskTracker }: AgentListProps) {
  const agentIds = Object.keys(agents);
  const onlineCount = agentIds.filter((id) => isAgentOnline(agents[id])).length;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold text-slate-100">Agents</h1>
        <div className="flex items-center gap-3">
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
            />
          ))}
        </div>
      )}
    </div>
  );
}
