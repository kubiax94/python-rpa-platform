"use client";

import Image from "next/image";
import { useEffect, useMemo, useState } from "react";
import type { ProcessScreenshotState } from "@/hooks/useAgentSocket";
import { getAgentSessions, getSessionProcessCount, type AgentState, type ProcessReplica, type ProcessWindowReplica, type SessionReplica } from "@/types/agent";
import { ProcessTable } from "./ProcessTable";
import { ProcessTree } from "./ProcessTree";

interface SessionPanelProps {
  agentId: string;
  state: AgentState;
  focusedProcess?: {
    pid?: number | null;
    taskId?: string | null;
  } | null;
  latestScreenshotEvent: ProcessScreenshotState | null;
  onCaptureProcessScreenshot: (agentId: string, pid: number, hwnd?: number) => { agentId: string; targetType: "process"; pid: number; hwnd?: number; requestId: string };
  onCaptureDesktopScreenshot: (agentId: string, sessionId: number) => { agentId: string; targetType: "desktop"; sessionId: number; requestId: string };
  onWatchProcessManager: (agentId: string) => void;
  onUnwatchProcessManager: (agentId: string) => void;
}

interface ScreenshotHistoryEntry extends ProcessScreenshotState {
  id: string;
  title: string;
  subtitle: string;
  sessionLabel?: string;
  username?: string;
  startedAt: number;
}

function normalizeFilterValue(value: string): string {
  return value.trim().toLocaleLowerCase("pl-PL");
}

function matchesProcessFilter(proc: ProcessReplica, search: string, onlyWithWindow: boolean): boolean {
  if (onlyWithWindow && !proc.has_window) {
    return false;
  }

  if (!search) {
    return true;
  }

  const haystack = [
    proc.exe,
    proc.exe_path,
    proc.args,
    proc.cmd,
    proc.cwd,
    proc.user,
    proc.window_title,
    proc.task_id,
    proc.pid != null ? String(proc.pid) : "",
    ...(proc.windows || []).flatMap((windowEntry) => [
      windowEntry.window_title,
      windowEntry.window_class,
      windowEntry.window_kind,
      windowEntry.hwnd != null ? String(windowEntry.hwnd) : "",
    ]),
  ]
    .filter(Boolean)
    .join("\n")
    .toLocaleLowerCase("pl-PL");

  return haystack.includes(search);
}

function formatCaptureTime(timestamp?: number) {
  if (!timestamp) {
    return "pending";
  }

  return new Date(timestamp * 1000).toLocaleTimeString("pl-PL", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function getSessionLabel(sessionKey: string, sessionData: SessionReplica) {
  if (sessionData.session_name) return sessionData.session_name;
  if (sessionData.username && sessionData.username !== "unknown") return sessionData.username;
  return sessionKey;
}

export function SessionPanel({ agentId, state, focusedProcess, latestScreenshotEvent, onCaptureProcessScreenshot, onCaptureDesktopScreenshot, onWatchProcessManager, onUnwatchProcessManager }: SessionPanelProps) {
  const sessions = getAgentSessions(state);
  const [viewMode, setViewMode] = useState<"table" | "tree">("table");
  const [history, setHistory] = useState<ScreenshotHistoryEntry[]>([]);
  const [selectedEntryId, setSelectedEntryId] = useState<string | null>(null);
  const [globalSearch, setGlobalSearch] = useState("");
  const [showOnlyWindowProcesses, setShowOnlyWindowProcesses] = useState(false);
  const [hideEmptySessions, setHideEmptySessions] = useState(false);
  const [collapsedSessions, setCollapsedSessions] = useState<Record<string, boolean>>({});
  const [sessionSearch, setSessionSearch] = useState<Record<string, string>>({});
  const [sessionOnlyWindow, setSessionOnlyWindow] = useState<Record<string, boolean>>({});

  useEffect(() => {
    onWatchProcessManager(agentId);
    return () => {
      onUnwatchProcessManager(agentId);
    };
  }, [agentId, onWatchProcessManager, onUnwatchProcessManager]);

  const matchedSessionKey = focusedProcess
    ? sessions.find(([, sessionData]) =>
        Object.values(sessionData.processes || {}).some(
          (proc) =>
            (focusedProcess.taskId && proc.task_id === focusedProcess.taskId) ||
            (focusedProcess.pid != null && proc.pid === focusedProcess.pid)
        )
      )?.[0]
    : undefined;

  const resolveProcessContext = (pid: number) => {
    for (const [sessionKey, sessionData] of sessions) {
      for (const proc of Object.values(sessionData.processes || {})) {
        if (proc.pid === pid) {
          return {
            proc,
            sessionId: sessionData.session_id,
            sessionLabel: getSessionLabel(sessionKey, sessionData),
            username: sessionData.username,
          };
        }
      }
    }

    return null;
  };

  const resolveSessionContext = (sessionId?: number) => {
    for (const [sessionKey, sessionData] of sessions) {
      if (sessionData.session_id === sessionId) {
        return {
          sessionLabel: getSessionLabel(sessionKey, sessionData),
          username: sessionData.username,
        };
      }
    }

    return {
      sessionLabel: sessionId != null ? `Session ${sessionId}` : "Unknown session",
      username: undefined,
    };
  };

  const buildHistoryEntry = (payload: ProcessScreenshotState): ScreenshotHistoryEntry => {
    if (payload.targetType === "desktop") {
      const sessionContext = resolveSessionContext(payload.sessionId);
      return {
        ...payload,
        id: payload.requestId,
        title: `Desktop • ${sessionContext.sessionLabel}`,
        subtitle: sessionContext.username ? `User: ${sessionContext.username}` : "Full session desktop",
        sessionLabel: sessionContext.sessionLabel,
        username: sessionContext.username,
        startedAt: Date.now(),
      };
    }

    const processContext = payload.pid != null ? resolveProcessContext(payload.pid) : null;
    const matchedWindow = payload.hwnd != null
      ? processContext?.proc.windows?.find((windowEntry) => windowEntry.hwnd === payload.hwnd)
      : undefined;
    return {
      ...payload,
      id: payload.requestId,
      title: processContext?.proc.exe || (payload.pid != null ? `PID ${payload.pid}` : "Process"),
      subtitle: processContext
        ? `PID ${processContext.proc.pid} • ${processContext.sessionLabel}`
        : payload.pid != null
          ? `PID ${payload.pid}`
          : "Process screenshot",
      sessionLabel: processContext?.sessionLabel,
      sessionId: payload.sessionId ?? processContext?.sessionId,
      username: processContext?.username,
      windowTitle: payload.windowTitle ?? matchedWindow?.window_title,
      startedAt: Date.now(),
    };
  };

  useEffect(() => {
    if (!latestScreenshotEvent || latestScreenshotEvent.agentId !== agentId) {
      return;
    }

    setHistory((current) => {
      const existingIndex = current.findIndex((entry) => entry.requestId === latestScreenshotEvent.requestId);
      if (existingIndex >= 0) {
        const next = [...current];
        next[existingIndex] = {
          ...next[existingIndex],
          ...latestScreenshotEvent,
        };
        return next;
      }

      return [...current, buildHistoryEntry(latestScreenshotEvent)];
    });
    setSelectedEntryId(latestScreenshotEvent.requestId);
  }, [agentId, latestScreenshotEvent]);

  const selectedEntry = useMemo(() => {
    if (history.length === 0) {
      return null;
    }

    if (selectedEntryId) {
      const matched = history.find((entry) => entry.id === selectedEntryId);
      if (matched) {
        return matched;
      }
    }

    return history[history.length - 1];
  }, [history, selectedEntryId]);

  const visibleHistory = useMemo(() => [...history].reverse(), [history]);

  const sessionViews = useMemo(() => {
    const normalizedGlobalSearch = normalizeFilterValue(globalSearch);

    return sessions.map(([sessionKey, sessionData]) => {
      const normalizedSessionSearch = normalizeFilterValue(sessionSearch[sessionKey] || "");
      const filteredProcesses = Object.fromEntries(
        Object.entries(sessionData.processes || {}).filter(([, proc]) => (
          matchesProcessFilter(proc, normalizedGlobalSearch, showOnlyWindowProcesses) &&
          matchesProcessFilter(proc, normalizedSessionSearch, sessionOnlyWindow[sessionKey] === true)
        ))
      );

      return {
        sessionKey,
        sessionData,
        sessionLabel: getSessionLabel(sessionKey, sessionData),
        totalProcessCount: getSessionProcessCount(sessionData),
        filteredProcessCount: Object.keys(filteredProcesses).length,
        filteredProcesses,
        localOnlyWindow: sessionOnlyWindow[sessionKey] === true,
        isCollapsed: collapsedSessions[sessionKey] === true,
      };
    });
  }, [sessions, globalSearch, showOnlyWindowProcesses, sessionSearch, sessionOnlyWindow, collapsedSessions]);

  const visibleSessionViews = useMemo(() => {
    if (!hideEmptySessions) {
      return sessionViews;
    }
    return sessionViews.filter((sessionView) => sessionView.filteredProcessCount > 0);
  }, [hideEmptySessions, sessionViews]);

  const visibleProcessTotal = useMemo(
    () => visibleSessionViews.reduce((sum, sessionView) => sum + sessionView.filteredProcessCount, 0),
    [visibleSessionViews]
  );

  const appendPendingEntry = (entry: ScreenshotHistoryEntry) => {
    setHistory((current) => [...current, entry]);
    setSelectedEntryId(entry.id);
  };

  const handleCaptureProcess = (proc: ProcessReplica, windowEntry?: ProcessWindowReplica) => {
    const request = onCaptureProcessScreenshot(agentId, proc.pid, windowEntry?.hwnd);
    const context = resolveProcessContext(proc.pid);
    const selectedWindowTitle = windowEntry?.window_title || proc.window_title;

    appendPendingEntry({
      agentId,
      id: request.requestId,
      requestId: request.requestId,
      targetType: "process",
      pid: proc.pid,
      hwnd: request.hwnd,
      sessionId: context?.sessionId,
      status: "pending",
      imageBase64: undefined,
      imageFormat: "png",
      windowTitle: selectedWindowTitle,
      error: undefined,
      capturedAt: undefined,
      title: proc.exe || `PID ${proc.pid}`,
      subtitle: `${windowEntry ? "Window" : "PID"} ${windowEntry?.hwnd ?? proc.pid} • ${context?.sessionLabel || "Unknown session"}`,
      sessionLabel: context?.sessionLabel,
      username: context?.username,
      startedAt: Date.now(),
    });
  };

  const handleCaptureDesktop = (sessionData: SessionReplica, sessionKey: string) => {
    if (sessionData.session_id == null) {
      return;
    }

    const request = onCaptureDesktopScreenshot(agentId, sessionData.session_id);
    appendPendingEntry({
      agentId,
      id: request.requestId,
      requestId: request.requestId,
      targetType: "desktop",
      sessionId: sessionData.session_id,
      status: "pending",
      imageBase64: undefined,
      imageFormat: "png",
      windowTitle: "Desktop",
      error: undefined,
      capturedAt: undefined,
      title: `Desktop • ${getSessionLabel(sessionKey, sessionData)}`,
      subtitle: sessionData.username ? `User: ${sessionData.username}` : "Full session desktop",
      sessionLabel: getSessionLabel(sessionKey, sessionData),
      username: sessionData.username,
      startedAt: Date.now(),
    });
  };

  const handleRefreshSelected = (entry: ScreenshotHistoryEntry) => {
    if (entry.targetType === "desktop") {
      if (entry.sessionId != null) {
        const request = onCaptureDesktopScreenshot(agentId, entry.sessionId);
        appendPendingEntry({
          ...entry,
          id: request.requestId,
          requestId: request.requestId,
          status: "pending",
          imageBase64: undefined,
          error: undefined,
          capturedAt: undefined,
          startedAt: Date.now(),
        });
      }
      return;
    }

    if (entry.pid != null) {
      const context = resolveProcessContext(entry.pid);
      const request = onCaptureProcessScreenshot(agentId, entry.pid, entry.hwnd);
      appendPendingEntry({
        ...entry,
        id: request.requestId,
        requestId: request.requestId,
        hwnd: request.hwnd,
        sessionId: context?.sessionId ?? entry.sessionId,
        sessionLabel: context?.sessionLabel ?? entry.sessionLabel,
        username: context?.username ?? entry.username,
        status: "pending",
        imageBase64: undefined,
        error: undefined,
        capturedAt: undefined,
        startedAt: Date.now(),
      });
    }
  };

  if (sessions.length === 0) {
    return (
      <div className="text-slate-500 text-sm italic p-4">
        No sessions reported by this agent
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-cyan-500/20 bg-slate-900/60 overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-cyan-500/15 px-4 py-3">
          <div>
            <h3 className="text-sm font-semibold text-cyan-100">Screenshot Workspace</h3>
            <p className="text-xs text-slate-400">History lives only in this panel and is cleared when you close it.</p>
          </div>
          {history.length > 0 && (
            <button
              type="button"
              onClick={() => {
                setHistory([]);
                setSelectedEntryId(null);
              }}
              className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-600 hover:bg-slate-800"
            >
              Clear History
            </button>
          )}
        </div>

        <div className="grid gap-0 xl:grid-cols-[minmax(0,1fr)_19rem]">
          <div className="min-h-[24rem] border-b border-slate-800/80 p-4 xl:border-b-0 xl:border-r">
            {!selectedEntry ? (
              <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-slate-800 bg-slate-950/50 px-4 text-center text-sm text-slate-500">
                Capture a process window or a full session desktop to start building local history.
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-semibold text-slate-100">{selectedEntry.title}</h4>
                    <p className="text-xs text-slate-400">{selectedEntry.subtitle}</p>
                    {selectedEntry.windowTitle && (
                      <p className="mt-1 text-xs text-slate-500">Window: {selectedEntry.windowTitle}</p>
                    )}
                    <p className="mt-1 text-xs text-slate-600">
                      {selectedEntry.status === "completed" ? `Captured at ${formatCaptureTime(selectedEntry.capturedAt)}` : "Waiting for agent response"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {selectedEntry.imageBase64 && (
                      <a
                        href={`data:image/${selectedEntry.imageFormat || "png"};base64,${selectedEntry.imageBase64}`}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-600 hover:bg-slate-800"
                      >
                        Open Full
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={() => handleRefreshSelected(selectedEntry)}
                      disabled={(selectedEntry.targetType === "desktop" && selectedEntry.sessionId == null) || (selectedEntry.targetType === "process" && selectedEntry.pid == null)}
                      className="rounded-md bg-cyan-500 px-3 py-1.5 text-xs font-medium text-slate-950 hover:bg-cyan-400 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {selectedEntry.status === "pending" ? "Capturing..." : "Refresh"}
                    </button>
                  </div>
                </div>

                {selectedEntry.status === "failed" && (
                  <div className="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-200">
                    {selectedEntry.error || "Screenshot capture failed."}
                  </div>
                )}

                {selectedEntry.status === "pending" && (
                  <div className="rounded-lg border border-cyan-500/15 bg-cyan-500/5 px-3 py-2 text-xs text-cyan-100">
                    Capturing current content from the agent...
                  </div>
                )}

                {selectedEntry.imageBase64 ? (
                  <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
                    <Image
                      src={`data:image/${selectedEntry.imageFormat || "png"};base64,${selectedEntry.imageBase64}`}
                      alt={selectedEntry.title}
                      width={1600}
                      height={900}
                      unoptimized
                      sizes="100vw"
                      className="max-h-[34rem] w-full object-contain"
                    />
                  </div>
                ) : selectedEntry.status !== "failed" ? (
                  <div className="flex min-h-[18rem] items-center justify-center rounded-lg border border-slate-800 bg-slate-950/50 px-4 text-center text-sm text-slate-500">
                    Preview will appear here when the agent returns the screenshot.
                  </div>
                ) : null}
              </div>
            )}
          </div>

          <aside className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500">History</h4>
              <span className="text-xs text-slate-600">{history.length}</span>
            </div>
            <div className="space-y-2">
              {visibleHistory.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-xs text-slate-600">
                  No screenshots yet.
                </div>
              ) : (
                visibleHistory.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    onClick={() => setSelectedEntryId(entry.id)}
                    className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                      selectedEntry?.id === entry.id
                        ? "border-cyan-500/50 bg-cyan-500/10"
                        : "border-slate-800 bg-slate-950/50 hover:border-slate-700 hover:bg-slate-900"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-slate-100">{entry.title}</div>
                        <div className="mt-1 truncate text-[11px] text-slate-500">{entry.subtitle}</div>
                      </div>
                      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${
                        entry.status === "completed"
                          ? "bg-emerald-500/20 text-emerald-300"
                          : entry.status === "failed"
                            ? "bg-red-500/20 text-red-300"
                            : "bg-cyan-500/20 text-cyan-200"
                      }`}>
                        {entry.status}
                      </span>
                    </div>
                    <div className="mt-2 text-[11px] text-slate-600">
                      {entry.status === "completed" ? formatCaptureTime(entry.capturedAt) : "pending"}
                    </div>
                  </button>
                ))
              )}
            </div>
          </aside>
        </div>
      </section>

      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-slate-200">
          Agent <span className="font-mono text-blue-400">{agentId.substring(0, 12)}</span>
        </h2>
        <div className="flex items-center gap-3">
          <div className="text-right text-xs text-slate-500">
            <div>{visibleProcessTotal} visible process{visibleProcessTotal !== 1 ? "es" : ""}</div>
            <div>{visibleSessionViews.length} session{visibleSessionViews.length !== 1 ? "s" : ""}</div>
          </div>
          <div className="inline-flex rounded-lg border border-slate-700 bg-slate-800/50 p-1 text-xs">
            <button
              type="button"
              onClick={() => setViewMode("table")}
              className={`rounded-md px-3 py-1.5 transition-colors ${
                viewMode === "table"
                  ? "bg-blue-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Table
            </button>
            <button
              type="button"
              onClick={() => setViewMode("tree")}
              className={`rounded-md px-3 py-1.5 transition-colors ${
                viewMode === "tree"
                  ? "bg-blue-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              Tree
            </button>
          </div>
        </div>
      </div>

      <section className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.4fr)_repeat(2,minmax(0,0.9fr))]">
          <label className="block">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wider text-slate-500">Global Filter</span>
            <input
              type="text"
              value={globalSearch}
              onChange={(event) => setGlobalSearch(event.target.value)}
              placeholder="Search exe, pid, args, title..."
              className="w-full rounded-md border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition-colors placeholder:text-slate-600 focus:border-cyan-500/50"
            />
          </label>
          <label className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950/50 px-3 py-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={showOnlyWindowProcesses}
              onChange={(event) => setShowOnlyWindowProcesses(event.target.checked)}
              className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-500"
            />
            Show only processes with window
          </label>
          <label className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950/50 px-3 py-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={hideEmptySessions}
              onChange={(event) => setHideEmptySessions(event.target.checked)}
              className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-500"
            />
            Hide sessions with no matches
          </label>
        </div>
      </section>

      {visibleSessionViews.length === 0 && (
        <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/20 px-4 py-8 text-center text-sm text-slate-500">
          No sessions match the current filters.
        </div>
      )}

      {visibleSessionViews.map(({ sessionKey, sessionData, totalProcessCount, filteredProcessCount, filteredProcesses, sessionLabel, localOnlyWindow, isCollapsed }) => (
        <div
          key={sessionKey}
          className="rounded-lg border border-slate-700 bg-slate-800/30 overflow-hidden"
        >
          <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between gap-3">
            <div>
              <h3 className="font-medium text-slate-200">
                Session: <span className="font-mono">{sessionLabel}</span>
                {sessionData.session_id != null && (
                  <span className="text-xs text-slate-500 ml-2">ID: {sessionData.session_id}</span>
                )}
              </h3>
              {sessionData.username && sessionData.username !== sessionLabel && (
                <p className="text-xs text-slate-400 mt-0.5">
                  User: {sessionData.username}
                </p>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-slate-400">
              {sessionData.status && (
                <span className={`px-2 py-0.5 rounded-full ${
                  sessionData.status === "Active"
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "bg-slate-600/30 text-slate-400"
                }`}>
                  {sessionData.status}
                </span>
              )}
              <span>{filteredProcessCount} / {totalProcessCount} process{totalProcessCount !== 1 ? "es" : ""}</span>
              <button
                type="button"
                onClick={() => handleCaptureDesktop(sessionData, sessionKey)}
                disabled={sessionData.session_id == null}
                className="rounded-md border border-cyan-500/30 px-3 py-1.5 text-xs text-cyan-100 transition-colors hover:border-cyan-400 hover:bg-cyan-500/10 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Desktop
              </button>
              <button
                type="button"
                onClick={() => setCollapsedSessions((current) => ({ ...current, [sessionKey]: !current[sessionKey] }))}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 transition-colors hover:border-slate-600 hover:bg-slate-800"
              >
                {isCollapsed ? "Show" : "Hide"}
              </button>
            </div>
          </div>
          {!isCollapsed && (
            <div className="p-4">
              <div className="mb-3 grid gap-3 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,0.85fr)]">
                <label className="block">
                  <span className="mb-1 block text-[11px] font-medium uppercase tracking-wider text-slate-500">Session Filter</span>
                  <input
                    type="text"
                    value={sessionSearch[sessionKey] || ""}
                    onChange={(event) => setSessionSearch((current) => ({ ...current, [sessionKey]: event.target.value }))}
                    placeholder={`Filter inside ${sessionLabel}`}
                    className="w-full rounded-md border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none transition-colors placeholder:text-slate-600 focus:border-cyan-500/50"
                  />
                </label>
                <label className="mt-5 flex items-center gap-2 rounded-md border border-slate-700 bg-slate-950/50 px-3 py-2 text-sm text-slate-300 xl:mt-0">
                  <input
                    type="checkbox"
                    checked={localOnlyWindow}
                    onChange={(event) => setSessionOnlyWindow((current) => ({ ...current, [sessionKey]: event.target.checked }))}
                    className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-500"
                  />
                  Only windowed processes in this session
                </label>
              </div>
              {matchedSessionKey === sessionKey && focusedProcess && (
                <div className="mb-3 rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-200">
                  Highlighting task process
                  {focusedProcess.taskId ? ` ${focusedProcess.taskId.substring(0, 12)}` : ""}
                  {focusedProcess.pid != null ? ` (PID ${focusedProcess.pid})` : ""}
                </div>
              )}
              {filteredProcessCount === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-700 bg-slate-950/40 px-4 py-6 text-center text-sm text-slate-500">
                  No processes in this session match the current filters.
                </div>
              ) : viewMode === "table" ? (
                <ProcessTable
                  processes={filteredProcesses}
                  highlightedPid={focusedProcess?.pid}
                  highlightedTaskId={focusedProcess?.taskId}
                  onCaptureScreenshot={handleCaptureProcess}
                />
              ) : (
                <ProcessTree
                  processes={filteredProcesses}
                  highlightedPid={focusedProcess?.pid}
                  highlightedTaskId={focusedProcess?.taskId}
                  onCaptureScreenshot={handleCaptureProcess}
                />
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}