"use client";

import { useState, type ReactNode } from "react";
import type { Task } from "@/hooks/useTaskAPI";
import type { ProcessScreenshotState } from "@/hooks/useAgentSocket";
import { getAgentConnection, getAgentSessions, getSessionProcessCount, isAgentOnline, type AgentState } from "@/types/agent";
import { ActiveTaskNotifications } from "./ActiveTaskNotifications";
import { SessionPanel } from "@/components/SessionPanel";
import { CommandPanel } from "./CommandPanel";
import { GuacamolePanel } from "@/components/GuacamolePanel";
import { MonitoredView } from "./MonitoredView";
import { OverviewPanel } from "./OverviewPanel";

type AgentTab = "overview" | "processes" | "monitored" | "remote" | "commands";

interface AgentDetailProps {
  agentId: string;
  state: AgentState;
  tasks: Task[];
  sendCommand: (type: string, data: Record<string, unknown>) => void;
  latestScreenshotEvent: ProcessScreenshotState | null;
  onCaptureProcessScreenshot: (agentId: string, pid: number, hwnd?: number) => { agentId: string; targetType: "process"; pid: number; hwnd?: number; requestId: string };
  onCaptureDesktopScreenshot: (agentId: string, sessionId: number) => { agentId: string; targetType: "desktop"; sessionId: number; requestId: string };
  onWatchProcessManager: (agentId: string) => void;
  onUnwatchProcessManager: (agentId: string) => void;
  onBack: () => void;
  onOpenTaskTracker: () => void;
  preferredTab?: AgentTab;
  focusedProcess?: {
    pid?: number | null;
    taskId?: string | null;
  } | null;
}

export function AgentDetail({ agentId, state, tasks, sendCommand, latestScreenshotEvent, onCaptureProcessScreenshot, onCaptureDesktopScreenshot, onWatchProcessManager, onUnwatchProcessManager, onBack, onOpenTaskTracker, preferredTab, focusedProcess }: AgentDetailProps) {
  const [activeTab, setActiveTab] = useState<AgentTab>(preferredTab ?? "overview");

  const sessions = getAgentSessions(state);
  const agentOnline = isAgentOnline(state);
  const connectionMeta = getAgentConnection(state);
  const totalProcesses = sessions.reduce(
    (sum, [, s]) => sum + getSessionProcessCount(s),
    0
  );
  const activeSessions = sessions.filter(
    ([, s]) => s.status === "Active" || s.status === undefined
  ).length;

  // Count monitored processes
  const monitoredCount = sessions.reduce((sum, [, s]) => {
    return sum + Object.values(s.processes || {}).filter(
      (p) => p.is_monitored || p.args?.includes("--agent_id_1234")
    ).length;
  }, 0);

  const tiles: {
    label: string;
    value: number | null;
    sub: string;
    color: string;
    tab: AgentTab;
    icon: ReactNode;
  }[] = [
    {
      label: "Overview",
      value: sessions.length,
      sub: `${activeSessions} active session${activeSessions !== 1 ? "s" : ""}`,
      color: "blue",
      tab: "overview",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z" />
        </svg>
      ),
    },
    {
      label: "Process Manager",
      value: totalProcesses,
      sub: "all processes",
      color: "emerald",
      tab: "processes",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 0 0 2.25-2.25V6.75a2.25 2.25 0 0 0-2.25-2.25H6.75A2.25 2.25 0 0 0 4.5 6.75v10.5a2.25 2.25 0 0 0 2.25 2.25Z" />
        </svg>
      ),
    },
    {
      label: "Monitored",
      value: monitoredCount,
      sub: monitoredCount > 0 ? "auto-restart" : "none active",
      color: "purple",
      tab: "monitored",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z" />
        </svg>
      ),
    },
    {
      label: "Remote",
      value: null,
      sub: "guacamole bridge",
      color: "cyan",
      tab: "remote",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 6.75A2.25 2.25 0 0 1 4.5 4.5h15A2.25 2.25 0 0 1 21.75 6.75v8.25a2.25 2.25 0 0 1-2.25 2.25h-4.19l.97 1.94a.75.75 0 0 1-.67 1.09H8.4a.75.75 0 0 1-.67-1.09l.97-1.94H4.5A2.25 2.25 0 0 1 2.25 15V6.75Z" />
        </svg>
      ),
    },
    {
      label: "Commands",
      value: null,
      sub: "send commands",
      color: "amber",
      tab: "commands",
      icon: (
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="m6.75 7.5 3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z" />
        </svg>
      ),
    },
  ];

  const colorMap: Record<string, { bg: string; text: string; border: string }> = {
    blue: { bg: "bg-blue-500/10", text: "text-blue-400", border: "border-blue-500/30" },
    emerald: { bg: "bg-emerald-500/10", text: "text-emerald-400", border: "border-emerald-500/30" },
    purple: { bg: "bg-purple-500/10", text: "text-purple-400", border: "border-purple-500/30" },
    cyan: { bg: "bg-cyan-500/10", text: "text-cyan-300", border: "border-cyan-500/30" },
    amber: { bg: "bg-amber-500/10", text: "text-amber-400", border: "border-amber-500/30" },
  };

  return (
    <div>
      {/* Header with back button */}
      <div className="flex items-center gap-3 mb-6">
        <button
          onClick={onBack}
          className="p-1.5 rounded-md text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18" />
          </svg>
        </button>
        <div>
          <h1 className="text-xl font-semibold text-slate-100">
            Agent <span className="font-mono text-blue-400">{agentId.substring(0, 12)}</span>
          </h1>
          <p className="text-xs text-slate-500 font-mono mt-0.5">{agentId}</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <ActiveTaskNotifications tasks={tasks} onOpenTasks={onOpenTaskTracker} label="Agent Tasks" />
          <div className={`w-2 h-2 rounded-full ${agentOnline ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]" : "bg-slate-500"}`} />
          <span className="text-sm text-slate-400">{agentOnline ? "Online" : "Offline"}</span>
          {!agentOnline && connectionMeta?.last_seen && (
            <span className="text-xs text-slate-500">
              last seen {new Date(connectionMeta.last_seen * 1000).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          )}
        </div>
      </div>

      {/* Tile navigation */}
      <div className="grid grid-cols-4 gap-3 mb-6">
        {tiles.map((tile) => {
          const c = colorMap[tile.color];
          const isActive = activeTab === tile.tab;
          return (
            <button
              key={tile.tab}
              onClick={() => setActiveTab(tile.tab)}
              disabled={!agentOnline && tile.tab === "commands"}
              className={`p-4 rounded-lg border transition-all text-left ${
                isActive
                  ? `${c.bg} ${c.border}`
                  : "border-slate-700 bg-slate-800/30 hover:border-slate-600"
              } ${!agentOnline && tile.tab === "commands" ? "opacity-50 cursor-not-allowed hover:border-slate-700" : ""}`}
            >
              <div className="flex items-center gap-2 mb-2">
                <span className={isActive ? c.text : "text-slate-500"}>{tile.icon}</span>
                <p className={`text-xs uppercase tracking-wider ${isActive ? c.text : "text-slate-500"}`}>
                  {tile.label}
                </p>
              </div>
              {tile.value !== null ? (
                <p className={`text-2xl font-bold ${c.text}`}>{tile.value}</p>
              ) : (
                <p className={`text-lg font-semibold ${c.text}`}>&#9654;</p>
              )}
              <p className="text-xs text-slate-500 mt-1">{tile.sub}</p>
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      {activeTab === "overview" && (
        <OverviewPanel agentId={agentId} state={state} />
      )}

      {activeTab === "processes" && (
        <SessionPanel
          agentId={agentId}
          state={state}
          focusedProcess={focusedProcess}
          latestScreenshotEvent={latestScreenshotEvent}
          onCaptureProcessScreenshot={onCaptureProcessScreenshot}
          onCaptureDesktopScreenshot={onCaptureDesktopScreenshot}
          onWatchProcessManager={onWatchProcessManager}
          onUnwatchProcessManager={onUnwatchProcessManager}
        />
      )}

      {activeTab === "monitored" && (
        <MonitoredView agentId={agentId} state={state} />
      )}

      {activeTab === "commands" && (
        <div>
          {agentOnline ? (
            <CommandPanel agentId={agentId} state={state} sendCommand={sendCommand} />
          ) : (
            <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4 text-sm text-slate-400">
              Agent jest offline. Komendy są zablokowane do czasu ponownego połączenia.
            </div>
          )}
        </div>
      )}

      <GuacamolePanel agentId={agentId} active={activeTab === "remote"} />
    </div>
  );
}
