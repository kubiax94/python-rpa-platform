"use client";

import { useState } from "react";
import { useAgentSocket } from "@/hooks/useAgentSocket";
import { useAgentState } from "@/hooks/useAgentStateAPI";
import { useTasks } from "@/hooks/useTaskAPI";
import { Sidebar, type MenuPage } from "@/components/Sidebar";
import { AgentList } from "@/components/AgentList";
import { AgentDetail } from "@/components/AgentDetail";
import { DeploymentsPage } from "@/components/DeploymentsPage";
import { TasksPage } from "@/components/TasksPage";
import { SettingsPage } from "@/components/SettingsPage";

type ProcessFocusTarget = {
  pid?: number | null;
  taskId?: string | null;
};

export default function Dashboard() {
  const { agents, connected, sendCommand, latestScreenshotEvent, requestProcessScreenshot, requestDesktopScreenshot, watchProcessManager, unwatchProcessManager } = useAgentSocket();
  const agentIds = Object.keys(agents);
  const { data: taskRows } = useTasks();

  const [activePage, setActivePage] = useState<MenuPage>("agents");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [processFocus, setProcessFocus] = useState<ProcessFocusTarget | null>(null);
  const [tasksEntryMode, setTasksEntryMode] = useState<"all" | "active">("all");
  const [taskAgentFilter, setTaskAgentFilter] = useState<string | null>(null);
  const { data: selectedAgentState, loading: selectedAgentLoading } = useAgentState(selectedAgent);
  const activeTaskCount = taskRows.filter((task) => task.status === "running" || task.status === "queued").length;

  const handleSelectAgent = (agentId: string) => {
    setSelectedAgent(agentId);
    setProcessFocus(null);
  };

  const handleBack = () => {
    setSelectedAgent(null);
    setProcessFocus(null);
  };

  const handleNavigate = (page: MenuPage) => {
    setActivePage(page);
    setTasksEntryMode("all");
    setTaskAgentFilter(null);
    if (page !== "agents") {
      setSelectedAgent(null);
      setProcessFocus(null);
    }
  };

  const handleOpenTaskTracker = (agentId?: string | null) => {
    setActivePage("tasks");
    setSelectedAgent(null);
    setProcessFocus(null);
    setTasksEntryMode("active");
    setTaskAgentFilter(agentId ?? null);
  };

  const handleOpenTaskProcess = (agentId: string, pid?: number | null, taskId?: string | null) => {
    setActivePage("agents");
    setSelectedAgent(agentId);
    setProcessFocus({ pid: pid ?? null, taskId: taskId ?? null });
  };

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        activePage={activePage}
        onNavigate={handleNavigate}
        connected={connected}
        agentCount={agentIds.length}
        activeTaskCount={activeTaskCount}
      />

      <main className="flex-1 overflow-y-auto p-6">
        {activePage === "agents" && !selectedAgent && (
          <AgentList
            agents={agents}
            connected={connected}
            tasks={taskRows}
            onSelectAgent={handleSelectAgent}
            onOpenTaskTracker={() => handleOpenTaskTracker()}
          />
        )}

        {activePage === "agents" && selectedAgent && agents[selectedAgent] && (
          <AgentDetail
            key={`${selectedAgent}:${processFocus?.taskId ?? ""}:${processFocus?.pid ?? ""}`}
            agentId={selectedAgent}
            state={selectedAgentState ?? agents[selectedAgent]}
            tasks={taskRows.filter((task) => task.agent_id === selectedAgent)}
            sendCommand={sendCommand}
            latestScreenshotEvent={latestScreenshotEvent}
            onCaptureProcessScreenshot={requestProcessScreenshot}
            onCaptureDesktopScreenshot={requestDesktopScreenshot}
            onWatchProcessManager={watchProcessManager}
            onUnwatchProcessManager={unwatchProcessManager}
            onBack={handleBack}
            onOpenTaskTracker={() => handleOpenTaskTracker(selectedAgent)}
            preferredTab={processFocus ? "processes" : undefined}
            focusedProcess={processFocus}
          />
        )}

        {activePage === "agents" && selectedAgent && selectedAgentLoading && (
          <div className="mt-3 text-xs text-slate-500">Refreshing full agent snapshot...</div>
        )}

        {activePage === "tasks" && (
          <TasksPage onOpenTaskProcess={handleOpenTaskProcess} entryMode={tasksEntryMode} agentFilterId={taskAgentFilter} />
        )}
        {activePage === "deployments" && <DeploymentsPage />}
        {activePage === "settings" && <SettingsPage />}
      </main>
    </div>
  );
}
