"use client";

import { useMemo, useState } from "react";
import { createTask } from "@/hooks/useTaskAPI";
import { EventLog } from "./EventLog";
import { getAgentSessions, type AgentState, type SessionReplica } from "@/types/agent";

interface CommandPanelProps {
  agentId: string;
  state: AgentState;
  canOperate: boolean;
  sendCommand: (type: string, data: Record<string, unknown>) => void;
}

type CommandView = "start-process" | "restart" | "console" | "login-session";

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

function toPowerShellString(value: string) {
  return `'${value.replace(/'/g, "''")}'`;
}

function inferExecutableName(exe: string) {
  const trimmed = exe.trim();
  if (!trimmed) return "Process";
  return trimmed.split(/[\\/]/).pop() || trimmed;
}

export function CommandPanel({ agentId, state, canOperate, sendCommand }: CommandPanelProps) {
  const [activeView, setActiveView] = useState<CommandView>("start-process");
  const [exe, setExe] = useState("");
  const [args, setArgs] = useState("");
  const [cwd, setCwd] = useState("");
  const [session, setSession] = useState("");
  const [monitored, setMonitored] = useState(false);
  const [busy, setBusy] = useState<null | "process" | "restart" | "session">(null);
  const [feedback, setFeedback] = useState<string>("");
  const [restartSession, setRestartSession] = useState("");

  // create session
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [domain, setDomain] = useState("");

  const sessions = useMemo(
    () => getAgentSessions(state).map(([sessionKey, sessionData]) => ({
      key: sessionKey,
      label: resolveSessionLabel(sessionKey, sessionData),
      value: resolveSessionValue(sessionData),
      sessionId: sessionData.session_id,
      status: sessionData.status,
      username: sessionData.username,
      processCount: Object.keys(sessionData.processes || {}).length,
    })),
    [state]
  );

  const selectableSessions = sessions.filter((sessionEntry) => Boolean(sessionEntry.value));

  const activeConsoleSession = sessions.find((sessionEntry) => sessionEntry.label.toLowerCase().includes("console"));

  const menuItems: Array<{ id: CommandView; label: string; hint: string }> = [
    { id: "start-process", label: "Start Process", hint: "queue command tasks" },
    { id: "restart", label: "Restart", hint: "common restart actions" },
    { id: "console", label: "Console", hint: "interactive session state" },
    { id: "login-session", label: "Login Session", hint: "create user session" },
  ];

  const handleStartProcess = async () => {
    if (!exe.trim()) return;

    setBusy("process");
    setFeedback("");

    try {
      if (monitored) {
        sendCommand("start_monitored_process", {
          agent_id: agentId,
          exe: exe.trim(),
          args: args.trim(),
          cwd: cwd.trim(),
          visible: true,
          session: session.trim(),
        });
        setFeedback("Monitored process sent directly to the agent. This action does not create a task yet.");
      } else {
        const scriptLines = [
          `$exe = ${toPowerShellString(exe.trim())}`,
          `$arguments = ${toPowerShellString(args.trim())}`,
          `$workingDir = ${toPowerShellString(cwd.trim())}`,
          "$startParams = @{ FilePath = $exe }",
          'if ($arguments.Length -gt 0) { $startParams.ArgumentList = $arguments }',
          'if ($workingDir.Length -gt 0) { $startParams.WorkingDirectory = $workingDir }',
          "$process = Start-Process @startParams -PassThru",
          'Write-Output ("Started process PID={0} Name={1}" -f $process.Id, $process.ProcessName)',
        ];

        await createTask({
          agent_id: agentId,
          name: `Start ${inferExecutableName(exe)}`,
          script: scriptLines.join("\n"),
          cwd: cwd.trim() || undefined,
          session: session.trim() || undefined,
        });
        setFeedback("Start Process queued as a task and will appear in the tracker.");
      }
    } catch (error) {
      setFeedback(String(error));
    } finally {
      setBusy(null);
    }
  };

  const handleCreateSession = async () => {
    if (!username.trim()) return;
    setBusy("session");
    setFeedback("");
    try {
      sendCommand("create_session", {
        agent_id: agentId,
        username: username.trim(),
        password,
        domain: domain.trim(),
      });
      setFeedback("Login Session request sent to the agent.");
    } finally {
      setBusy(null);
    }
  };

  const handleQueueRestartTask = async (taskName: string, script: string, targetSession?: string) => {
    setBusy("restart");
    setFeedback("");
    try {
      await createTask({
        agent_id: agentId,
        name: taskName,
        script,
        session: targetSession || undefined,
      });
      setFeedback(`${taskName} queued as a task.`);
    } catch (error) {
      setFeedback(String(error));
    } finally {
      setBusy(null);
    }
  };

  const inputClass =
    "w-full px-3 py-2 rounded-md bg-slate-800 border border-slate-600 text-slate-200 text-sm placeholder:text-slate-500 focus:outline-none focus:border-blue-500 transition-colors";

  return (
    <div className="grid min-h-[34rem] grid-cols-[15rem_minmax(0,1fr)] gap-4">
      <aside className="rounded-xl border border-slate-700 bg-slate-900/60 p-3">
        <div className="mb-3 px-2">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Commands</div>
          <div className="mt-1 text-xs text-slate-600 font-mono">{agentId}</div>
        </div>
        <div className="space-y-1">
          {menuItems.map((item) => {
            const active = activeView === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveView(item.id)}
                className={`w-full rounded-lg border px-3 py-3 text-left transition-colors ${
                  active
                    ? "border-blue-500/40 bg-blue-500/10"
                    : "border-slate-800 bg-slate-950/40 hover:border-slate-700 hover:bg-slate-900"
                }`}
              >
                <div className={`text-sm font-medium ${active ? "text-blue-300" : "text-slate-200"}`}>{item.label}</div>
                <div className="mt-1 text-xs text-slate-500">{item.hint}</div>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800/30">
        <div className="flex items-start justify-between border-b border-slate-700 bg-slate-900/60 px-5 py-4">
          <div>
            <h3 className="text-base font-semibold text-slate-100">
              {menuItems.find((item) => item.id === activeView)?.label}
            </h3>
            <p className="mt-1 text-sm text-slate-500">
              {activeView === "start-process" && "Use tasks for standard launches so operators can track progress from the notification panel."}
              {activeView === "restart" && "Queue restart-oriented tasks or bounce an interactive shell without leaving the agent workspace."}
              {activeView === "console" && "Session and console state for this agent, similar to an operator workspace."}
              {activeView === "login-session" && "Create a new user session directly on the selected agent."}
            </p>
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-right text-xs text-slate-500">
            <div>Workspace</div>
            <div className="mt-1 font-mono text-slate-300">{agentId.substring(0, 12)}</div>
          </div>
        </div>

        <div className="p-5">
          {feedback && (
            <div className="mb-4 rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-3 py-2 text-sm text-cyan-100">
              {feedback}
            </div>
          )}

          {activeView === "start-process" && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
              <div className="space-y-4">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="md:col-span-2">
                    <label className="mb-1 block text-xs text-slate-400">Executable</label>
                    <input
                      className={inputClass}
                      placeholder="e.g. notepad.exe or C:\app\robot.exe"
                      value={exe}
                      onChange={(e) => setExe(e.target.value)}
                      disabled={!canOperate}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-400">Arguments</label>
                    <input
                      className={inputClass}
                      placeholder="--flag value"
                      value={args}
                      onChange={(e) => setArgs(e.target.value)}
                      disabled={!canOperate}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-400">Session</label>
                    <select
                      className={inputClass}
                      value={session}
                      onChange={(e) => setSession(e.target.value)}
                      disabled={!canOperate}
                    >
                      <option value="">Default / best available</option>
                      {selectableSessions.map((sessionEntry) => (
                        <option key={sessionEntry.key} value={sessionEntry.value}>
                          {sessionEntry.label}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="md:col-span-2">
                    <label className="mb-1 block text-xs text-slate-400">Working Directory</label>
                    <input
                      className={inputClass}
                      placeholder="C:\app"
                      value={cwd}
                      onChange={(e) => setCwd(e.target.value)}
                      disabled={!canOperate}
                    />
                  </div>
                </div>

                <label className="flex items-center gap-2 text-sm text-slate-400">
                  <input
                    type="checkbox"
                    checked={monitored}
                    onChange={(e) => setMonitored(e.target.checked)}
                    disabled={!canOperate}
                    className="rounded border-slate-600 bg-slate-800 text-blue-500 focus:ring-blue-500"
                  />
                  Monitored (uses direct agent command)
                </label>

                <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm text-slate-400">
                  <div>
                    {monitored
                      ? "Monitored launches go straight to the agent. They are not task-backed yet."
                      : "Standard launches are queued as tasks so the operator can track them from notifications."}
                  </div>
                  <button
                    type="button"
                    onClick={handleStartProcess}
                    disabled={!canOperate || !exe.trim() || busy === "process"}
                    className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {busy === "process" ? "Dispatching..." : monitored ? "Start Monitored" : "Queue Start Task"}
                  </button>
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Execution preview</div>
                <div className="mt-3 space-y-2 text-sm text-slate-300">
                  <div><span className="text-slate-500">Target:</span> <span className="font-mono">{agentId.substring(0, 12)}</span></div>
                  <div><span className="text-slate-500">Executable:</span> <span className="font-mono break-all">{exe || "—"}</span></div>
                  <div><span className="text-slate-500">Session:</span> <span className="font-mono">{session || "Default"}</span></div>
                  <div><span className="text-slate-500">Mode:</span> {monitored ? "Direct monitored command" : "Tracked task"}</div>
                </div>
              </div>
            </div>
          )}

          {activeView === "restart" && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
                  <div className="text-sm font-semibold text-slate-100">Restart Explorer</div>
                  <p className="mt-2 text-sm text-slate-500">
                    Queue a task to restart the interactive shell in a selected user session.
                  </p>
                  <select
                    className={`mt-4 ${inputClass}`}
                    value={restartSession}
                    onChange={(e) => setRestartSession(e.target.value)}
                    disabled={!canOperate}
                  >
                    <option value="">Default session</option>
                    {selectableSessions.map((sessionEntry) => (
                      <option key={sessionEntry.key} value={sessionEntry.value}>
                        {sessionEntry.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => handleQueueRestartTask(
                      "Restart Explorer",
                      [
                        'Stop-Process -Name explorer -Force -ErrorAction SilentlyContinue',
                        'Start-Sleep -Seconds 2',
                        'Start-Process explorer.exe',
                        'Write-Output "Explorer restarted"',
                      ].join("\n"),
                      restartSession || undefined
                    )}
                    disabled={!canOperate || busy === "restart"}
                    className="mt-4 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Queue Explorer Restart
                  </button>
                </div>

                <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
                  <div className="text-sm font-semibold text-slate-100">Restart Host</div>
                  <p className="mt-2 text-sm text-slate-500">
                    Queue a full machine reboot as a tracked task. Use carefully.
                  </p>
                  <button
                    type="button"
                    onClick={() => handleQueueRestartTask(
                      "Restart Host",
                      ['Write-Output "Restarting host..."', 'Restart-Computer -Force'].join("\n")
                    )}
                    disabled={!canOperate || busy === "restart"}
                    className="mt-4 rounded-md bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Queue Host Restart
                  </button>
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 text-sm text-slate-400">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Why tasks</div>
                <p className="mt-3">
                  Restart actions are task-backed so the operator can see queued/running/completed state from the notification panel and the task page.
                </p>
              </div>
            </div>
          )}

          {activeView === "console" && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-semibold text-slate-100">Interactive Sessions</div>
                    <div className="mt-1 text-sm text-slate-500">Console and user sessions reported by the agent.</div>
                  </div>
                  {activeConsoleSession && (
                    <div className="rounded-full bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300">
                      Console: {activeConsoleSession.label}
                    </div>
                  )}
                </div>
                <div className="space-y-3">
                  {sessions.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-slate-800 px-4 py-8 text-center text-sm text-slate-500">
                      No interactive sessions reported yet.
                    </div>
                  ) : (
                    sessions.map((sessionEntry) => (
                      <div key={sessionEntry.key} className="rounded-lg border border-slate-800 bg-slate-900/70 px-4 py-3">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <div className="text-sm font-medium text-slate-100">{sessionEntry.label}</div>
                            <div className="mt-1 text-xs text-slate-500">
                              {sessionEntry.username || "Unknown user"}
                              {sessionEntry.sessionId != null ? ` · Session ID ${sessionEntry.sessionId}` : ""}
                            </div>
                          </div>
                          <div className="text-right text-xs text-slate-500">
                            <div>{sessionEntry.status || "Unknown"}</div>
                            <div className="mt-1">{sessionEntry.processCount} processes</div>
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <EventLog agentId={agentId} />
            </div>
          )}

          {activeView === "login-session" && (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
              <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="md:col-span-2">
                    <label className="mb-1 block text-xs text-slate-400">Username</label>
                    <input
                      className={inputClass}
                      placeholder="DOMAIN\user"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      disabled={!canOperate}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-400">Password</label>
                    <input
                      type="password"
                      className={inputClass}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      disabled={!canOperate}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-slate-400">Domain</label>
                    <input
                      className={inputClass}
                      placeholder="MYDOMAIN"
                      value={domain}
                      onChange={(e) => setDomain(e.target.value)}
                      disabled={!canOperate}
                    />
                  </div>
                </div>
                <div className="mt-4 flex justify-end">
                  <button
                    type="button"
                    onClick={handleCreateSession}
                    disabled={!canOperate || !username.trim() || busy === "session"}
                    className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {busy === "session" ? "Sending..." : "Create Session"}
                  </button>
                </div>
              </div>

              <div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 text-sm text-slate-400">
                <div className="text-xs font-semibold uppercase tracking-wider text-slate-500">Operator note</div>
                <p className="mt-3">
                  Login Session currently uses a direct agent command. It does not create a task notification yet.
                </p>
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
