"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { useTasks, useTaskLog, createTask, cancelTask, type Task } from "@/hooks/useTaskAPI";
import { useAgentSocket } from "@/hooks/useAgentSocket";
import { getAgentSessions, type AgentsMap, type SessionReplica } from "@/types/agent";

interface TasksPageProps {
  onOpenTaskProcess: (agentId: string, pid?: number | null, taskId?: string | null) => void;
  entryMode?: "all" | "active";
  agentFilterId?: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  queued: "bg-slate-500",
  running: "bg-amber-500 animate-pulse",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  cancelled: "bg-slate-600",
  timeout: "bg-orange-500",
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium text-white ${STATUS_COLORS[status] || "bg-slate-600"}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current" />
      {status}
    </span>
  );
}

function formatTime(ts: number | null) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatDuration(start: number | null, end: number | null) {
  if (!start) return "—";
  const elapsed = (end || Math.floor(Date.now() / 1000)) - start;
  if (elapsed < 60) return `${elapsed}s`;
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ${elapsed % 60}s`;
  return `${Math.floor(elapsed / 3600)}h ${Math.floor((elapsed % 3600) / 60)}m`;
}

function cleanSessionKey(key: string) {
  return key.replace(/-None$/, "");
}

function resolveSessionLabel(sessionKey: string, sessionData: SessionReplica) {
  if (sessionData.session_name) return cleanSessionKey(sessionData.session_name);
  if (sessionData.username && sessionData.username !== "unknown") return sessionData.username;
  return cleanSessionKey(sessionKey);
}

function resolveSessionValue(sessionData: SessionReplica) {
  if (sessionData.username && sessionData.username !== "unknown") return sessionData.username;
  return "";
}

// ── Task Console ──────────────────────────────────────────────────

function TaskConsole({ taskId, status }: { taskId: string; status: string }) {
  const { log, truncated } = useTaskLog(taskId);
  const consoleRef = useRef<HTMLPreElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    if (autoScroll && consoleRef.current) {
      consoleRef.current.scrollTop = consoleRef.current.scrollHeight;
    }
  }, [log, autoScroll]);

  const isLive = status === "running" || status === "queued";

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 bg-slate-900 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 font-mono">Console Output</span>
          {isLive && (
            <span className="flex items-center gap-1 text-xs text-amber-400">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              LIVE
            </span>
          )}
          {truncated && (
            <span className="text-xs text-slate-500">
              showing latest output only
            </span>
          )}
        </div>
        <label className="flex items-center gap-1.5 text-xs text-slate-500">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            className="rounded border-slate-600"
          />
          Auto-scroll
        </label>
      </div>
      <pre
        ref={consoleRef}
        className="flex-1 overflow-auto p-3 bg-[#0d1117] text-green-400 font-mono text-xs leading-5 whitespace-pre-wrap"
        style={{ minHeight: 200, maxHeight: 500 }}
      >
        {log || (isLive ? "Waiting for output..." : "No output")}
      </pre>
    </div>
  );
}

// ── New Task Form ─────────────────────────────────────────────────

function NewTaskForm({
  agents,
  onSubmit,
}: {
  agents: AgentsMap;
  onSubmit: (task: Task) => void;
}) {
  const CUSTOM_SESSION_VALUE = "__custom__";
  const agentIds = Object.keys(agents);
  const [agentId, setAgentId] = useState(agentIds[0] || "");
  const [name, setName] = useState("");
  const [script, setScript] = useState("");
  const [cwd, setCwd] = useState("");
  const [timeout, setTimeout] = useState(300);
  const [selectedSession, setSelectedSession] = useState("");
  const [customSession, setCustomSession] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const agentState = agentId ? agents[agentId] : undefined;
  const sessionOptions = useMemo(
    () => agentState
      ? getAgentSessions(agentState)
          .map(([sessionKey, sessionData]) => ({
            label: resolveSessionLabel(sessionKey, sessionData),
            value: resolveSessionValue(sessionData),
          }))
          .filter((option, index, values) => option.value && values.findIndex((candidate) => candidate.value === option.value) === index)
      : [],
    [agentState]
  );

  useEffect(() => {
    if (!agentId && agentIds.length > 0) setAgentId(agentIds[0]);
  }, [agentIds, agentId]);

  useEffect(() => {
    if (selectedSession === CUSTOM_SESSION_VALUE) {
      return;
    }
    if (selectedSession && !sessionOptions.some((option) => option.value === selectedSession)) {
      setSelectedSession("");
    }
  }, [agentId, selectedSession, sessionOptions]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agentId || !script.trim()) {
      setError("Agent and script are required");
      return;
    }

    const resolvedSession = selectedSession === CUSTOM_SESSION_VALUE
      ? customSession.trim() || undefined
      : selectedSession || undefined;

    if (selectedSession === CUSTOM_SESSION_VALUE && !resolvedSession) {
      setError("Custom session username is required");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const task = await createTask({
        agent_id: agentId,
        script: script.trim(),
        name: name.trim() || undefined,
        cwd: cwd.trim() || undefined,
        timeout_sec: timeout,
        session: resolvedSession,
      });
      onSubmit(task);
      setScript("");
      setName("");
      setSelectedSession("");
      setCustomSession("");
    } catch (e) {
      setError(String(e));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Agent</label>
          <select
            value={agentId}
            onChange={(e) => setAgentId(e.target.value)}
            className="w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          >
            {agentIds.map((id) => (
              <option key={id} value={id}>
                {id.substring(0, 12)}...
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Task Name (optional)</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Restart IIS"
            className="w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Session (optional)</label>
          <select
            value={selectedSession}
            onChange={(e) => setSelectedSession(e.target.value)}
            className="w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          >
            <option value="">Default / system session</option>
            {sessionOptions.map((sessionOption) => (
              <option key={sessionOption.value} value={sessionOption.value}>
                {sessionOption.label}
              </option>
            ))}
            <option value={CUSTOM_SESSION_VALUE}>Custom...</option>
          </select>
          {selectedSession === CUSTOM_SESSION_VALUE && (
            <input
              type="text"
              value={customSession}
              onChange={(e) => setCustomSession(e.target.value)}
              placeholder="DOMAIN\\user"
              className="mt-2 w-full rounded bg-slate-900 border border-slate-700 px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
            />
          )}
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Working Dir (optional)</label>
          <input
            type="text"
            value={cwd}
            onChange={(e) => setCwd(e.target.value)}
            placeholder="C:\\Scripts"
            className="w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Timeout (sec)</label>
          <input
            type="number"
            value={timeout}
            onChange={(e) => setTimeout(Number(e.target.value))}
            min={10}
            max={86400}
            className="w-full rounded bg-slate-800 border border-slate-700 px-2 py-1.5 text-sm text-slate-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1">PowerShell Script</label>
        <textarea
          value={script}
          onChange={(e) => setScript(e.target.value)}
          rows={8}
          placeholder={"# Write your PowerShell script here\nGet-Process | Sort-Object CPU -Descending | Select-Object -First 10"}
          className="w-full rounded bg-[#0d1117] border border-slate-700 px-3 py-2 text-sm text-green-400 font-mono leading-5 focus:outline-none focus:ring-1 focus:ring-cyan-500 resize-y"
          spellCheck={false}
        />
      </div>

      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded px-3 py-1.5">
          {error}
        </div>
      )}

      <div className="flex justify-end">
        <button
          type="submit"
          disabled={submitting || !script.trim()}
          className="px-4 py-2 rounded bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium text-white transition-colors"
        >
          {submitting ? "Dispatching..." : "Run Task"}
        </button>
      </div>
    </form>
  );
}

// ── Main TasksPage ────────────────────────────────────────────────

export function TasksPage({ onOpenTaskProcess, entryMode = "all", agentFilterId = null }: TasksPageProps) {
  const { agents } = useAgentSocket();
  const { data: tasks, refresh } = useTasks(agentFilterId || undefined);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [showNewTask, setShowNewTask] = useState(false);
  const [detailTab, setDetailTab] = useState<"output" | "input">("output");

  const activeTasks = tasks.filter((task) => task.status === "running" || task.status === "queued");
  const resolvedSelectedTaskId = selectedTaskId && tasks.some((task) => task.id === selectedTaskId)
    ? selectedTaskId
    : entryMode === "active" && activeTasks.length > 0
      ? activeTasks[0].id
      : tasks[0]?.id ?? null;

  const selectedTask = tasks.find((t) => t.id === resolvedSelectedTaskId);

  const handleTaskCreated = (task: Task) => {
    setSelectedTaskId(task.id);
    setDetailTab("output");
    setShowNewTask(false);
    refresh();
  };

  const handleCancel = async (taskId: string) => {
    try {
      await cancelTask(taskId);
      refresh();
    } catch (e) {
      console.error("Cancel failed:", e);
    }
  };

  const canOpenTaskProcess = Boolean(
    selectedTask?.agent_id && (selectedTask?.pid != null || selectedTask?.status === "running" || selectedTask?.status === "queued")
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Tasks</h1>
          {entryMode === "active" && (
            <p className="mt-1 text-xs text-slate-500">
              Tracking command-style tasks that are currently queued or running.
              {agentFilterId ? ` Agent: ${agentFilterId.substring(0, 12)}` : ""}
            </p>
          )}
        </div>
        <button
          onClick={() => setShowNewTask(!showNewTask)}
          className="px-3 py-1.5 rounded bg-cyan-600 hover:bg-cyan-500 text-sm font-medium text-white transition-colors"
        >
          {showNewTask ? "Cancel" : "+ New Task"}
        </button>
      </div>

      {/* New Task Form */}
      {showNewTask && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-4">
          <h2 className="text-sm font-semibold text-slate-300 mb-3">New Task</h2>
          <NewTaskForm agents={agents} onSubmit={handleTaskCreated} />
        </div>
      )}

      {/* Two-column layout: task list + detail/console */}
      <div className="grid grid-cols-5 gap-4" style={{ minHeight: 500 }}>
        {/* Task list */}
        <div className="col-span-2 rounded-lg border border-slate-700 bg-slate-800/30 overflow-hidden flex flex-col">
          <div className="px-3 py-2 border-b border-slate-700 bg-slate-800/50">
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Task History ({tasks.length})
              </span>
              <span className="text-xs text-slate-500">
                Active: <span className={activeTasks.length > 0 ? "text-amber-300" : "text-slate-400"}>{activeTasks.length}</span>
              </span>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {tasks.length === 0 ? (
              <div className="flex items-center justify-center h-full text-sm text-slate-600">
                No tasks yet
              </div>
            ) : (
              tasks.map((task) => (
                <div
                  key={task.id}
                  onClick={() => {
                    setSelectedTaskId(task.id);
                    setDetailTab("output");
                  }}
                  className={`px-3 py-2.5 border-b border-slate-800 cursor-pointer transition-colors hover:bg-slate-700/30 ${
                    resolvedSelectedTaskId === task.id ? "bg-slate-700/50 border-l-2 border-l-cyan-500" : ""
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm text-slate-200 font-medium truncate max-w-[60%]">
                      {task.name || task.id.substring(0, 12)}
                    </span>
                    <StatusBadge status={task.status} />
                  </div>
                  <div className="flex items-center gap-3 text-xs text-slate-500">
                    <span>{formatTime(task.created_at)}</span>
                    <span>{formatDuration(task.started_at, task.completed_at)}</span>
                    <span className="font-mono">{task.agent_id.substring(0, 8)}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Detail + Console */}
        <div className="col-span-3 rounded-lg border border-slate-700 bg-slate-800/30 overflow-hidden flex flex-col">
          {selectedTask ? (
            <>
              {/* Task info header */}
              <div className="px-4 py-3 border-b border-slate-700 bg-slate-800/50 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <h3 className="text-sm font-semibold text-slate-200">
                      {selectedTask.name || selectedTask.id.substring(0, 16)}
                    </h3>
                    <StatusBadge status={selectedTask.status} />
                  </div>
                  <div className="flex items-center gap-2">
                    {canOpenTaskProcess && (
                      <button
                        onClick={() => onOpenTaskProcess(selectedTask.agent_id, selectedTask.pid, selectedTask.id)}
                        className="px-2.5 py-1 rounded bg-cyan-600 hover:bg-cyan-500 text-xs font-medium text-white transition-colors"
                      >
                        Open Live Process
                      </button>
                    )}
                    {(selectedTask.status === "running" || selectedTask.status === "queued") && (
                      <button
                        onClick={() => handleCancel(selectedTask.id)}
                        className="px-2.5 py-1 rounded bg-red-600 hover:bg-red-500 text-xs font-medium text-white transition-colors"
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <div className="inline-flex rounded-lg border border-slate-700 bg-slate-900/60 p-1 text-xs">
                    <button
                      type="button"
                      onClick={() => setDetailTab("input")}
                      className={`rounded-md px-3 py-1.5 transition-colors ${
                        detailTab === "input"
                          ? "bg-cyan-600 text-white"
                          : "text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      Input
                    </button>
                    <button
                      type="button"
                      onClick={() => setDetailTab("output")}
                      className={`rounded-md px-3 py-1.5 transition-colors ${
                        detailTab === "output"
                          ? "bg-cyan-600 text-white"
                          : "text-slate-400 hover:text-slate-200"
                      }`}
                    >
                      Output
                    </button>
                  </div>
                  <div className="text-xs text-slate-500">
                    {detailTab === "output"
                      ? "Live output and task execution log."
                      : "Task input payload and execution parameters."}
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-3 text-xs">
                  <div>
                    <span className="text-slate-500">Agent: </span>
                    <span className="text-slate-300 font-mono">{selectedTask.agent_id.substring(0, 12)}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Created: </span>
                    <span className="text-slate-300">{formatTime(selectedTask.created_at)}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Duration: </span>
                    <span className="text-slate-300">
                      {formatDuration(selectedTask.started_at, selectedTask.completed_at)}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">PID: </span>
                    <span className="text-slate-300 font-mono">{selectedTask.pid ?? "—"}</span>
                  </div>
                  <div>
                    <span className="text-slate-500">Exit: </span>
                    <span className={`font-mono ${selectedTask.exit_code === 0 ? "text-emerald-400" : selectedTask.exit_code !== null ? "text-red-400" : "text-slate-500"}`}>
                      {selectedTask.exit_code ?? "—"}
                    </span>
                  </div>
                </div>
                {selectedTask.error && (
                  <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1">
                    {selectedTask.error}
                  </div>
                )}
                {selectedTask.requested_by && (
                  <div className="text-xs text-slate-600">
                    Requested by: {selectedTask.requested_by}
                    {selectedTask.requested_from ? ` from ${selectedTask.requested_from}` : ""}
                  </div>
                )}
                <div className="text-xs text-slate-500">
                  {canOpenTaskProcess
                    ? "Open Live Process jumps to the agent process view and highlights the matching task process."
                    : "Live process link is available for queued or running tasks with an agent target."}
                </div>
              </div>

              {/* Detail content */}
              <div className="flex-1">
                {detailTab === "output" ? (
                  <TaskConsole taskId={selectedTask.id} status={selectedTask.status} />
                ) : (
                  <div className="flex h-full flex-col overflow-hidden">
                    <div className="flex items-center justify-between px-3 py-2 bg-slate-900 border-b border-slate-700">
                      <span className="text-xs text-slate-400 font-mono">Task Input</span>
                      <span className="text-xs text-slate-500">
                        Script, session and runtime configuration
                      </span>
                    </div>
                    <div className="flex-1 overflow-auto p-4 space-y-4 bg-[#0d1117]">
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="rounded border border-slate-800 bg-slate-900/70 px-3 py-2">
                          <span className="text-slate-500">Session</span>
                          <div className="mt-1 text-slate-200 font-mono">{selectedTask.session || "Default / system session"}</div>
                        </div>
                        <div className="rounded border border-slate-800 bg-slate-900/70 px-3 py-2">
                          <span className="text-slate-500">Working Dir</span>
                          <div className="mt-1 text-slate-200 font-mono break-all">{selectedTask.cwd || "—"}</div>
                        </div>
                        <div className="rounded border border-slate-800 bg-slate-900/70 px-3 py-2">
                          <span className="text-slate-500">Timeout</span>
                          <div className="mt-1 text-slate-200 font-mono">{selectedTask.timeout_sec}s</div>
                        </div>
                        <div className="rounded border border-slate-800 bg-slate-900/70 px-3 py-2">
                          <span className="text-slate-500">Task ID</span>
                          <div className="mt-1 text-slate-200 font-mono break-all">{selectedTask.id}</div>
                        </div>
                      </div>

                      <div>
                        <div className="mb-2 text-xs text-slate-400 uppercase tracking-wider">PowerShell Script</div>
                        <pre
                          className="overflow-auto rounded border border-slate-800 bg-slate-950 px-3 py-3 text-xs text-cyan-100 font-mono whitespace-pre-wrap leading-5"
                          style={{ minHeight: 220 }}
                        >
                          {selectedTask.script || "No script payload stored"}
                        </pre>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-sm text-slate-600">
              Select a task to view details and console output
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
