"use client";

import Image from "next/image";
import { useEffect, useMemo, useState } from "react";
import { useGuacamoleWorkspace } from "@/components/GuacamoleWorkspace";
import { useAgentSocket } from "@/hooks/useAgentSocket";
import { useAgentState } from "@/hooks/useAgentStateAPI";
import { useTasks } from "@/hooks/useTaskAPI";
import { Sidebar, type MenuPage } from "@/components/Sidebar";
import type { AgentTab } from "@/components/agent-tabs";
import { AgentList } from "@/components/AgentList";
import { AgentDetail } from "@/components/AgentDetail";
import { DeploymentsPage } from "@/components/DeploymentsPage";
import { GuacamoleWorkspaceProvider } from "@/components/GuacamoleWorkspace";
import { TasksPage } from "@/components/TasksPage";
import { SettingsPage } from "@/components/SettingsPage";
import type { AuthSession } from "@/lib/auth";
import { hasMinimumRole } from "@/lib/rbac";
import { useUserAuth } from "@/hooks/useUserAuth";

function AuthScreen({
  localLoginEnabled,
  microsoftLoginEnabled,
  backendAvailability,
  authNotice,
  onRetry,
  onLocalLogin,
  onMicrosoftLogin,
}: {
  localLoginEnabled: boolean;
  microsoftLoginEnabled: boolean;
  backendAvailability: "unknown" | "online" | "offline";
  authNotice: string | null;
  onRetry: () => Promise<void>;
  onLocalLogin: (username: string, password: string) => Promise<void>;
  onMicrosoftLogin: () => Promise<void>;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState<"idle" | "local" | "microsoft">("idle");
  const [error, setError] = useState<string | null>(null);

  return (
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,#155e75_0%,#0f172a_42%,#020617_100%)] px-6 py-10">
      <div className="grid w-full max-w-6xl gap-8 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="relative overflow-hidden rounded-[36px] border border-cyan-500/15 bg-slate-950/70 p-8 shadow-[0_32px_120px_rgba(2,6,23,0.48)]">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(34,211,238,0.18),transparent_32%),radial-gradient(circle_at_80%_30%,rgba(14,165,233,0.16),transparent_28%),radial-gradient(circle_at_50%_85%,rgba(56,189,248,0.14),transparent_30%)]" />
          <div className="relative flex h-full flex-col justify-between gap-10">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-300">My Orciestra</p>
              <h1 className="mt-4 max-w-xl text-4xl font-semibold leading-tight text-slate-50 xl:text-5xl">
                Control your VM fleet from one clean workspace.
              </h1>
              <p className="mt-4 max-w-lg text-sm leading-6 text-slate-300/80">
                Sign in to access agents, deployments, remote sessions, and operator tooling.
              </p>
            </div>

            <div className="grid gap-5 lg:grid-cols-[minmax(0,1.05fr)_minmax(260px,0.95fr)] lg:items-end">
              <div className="relative overflow-hidden rounded-[28px] border border-white/10 bg-slate-900/60 p-5 backdrop-blur-sm">
                <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/60 to-transparent" />
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Agents</p>
                    <p className="mt-3 text-2xl font-semibold text-slate-100">Live</p>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Deployments</p>
                    <p className="mt-3 text-2xl font-semibold text-slate-100">Release</p>
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Remote</p>
                    <p className="mt-3 text-2xl font-semibold text-slate-100">RDP</p>
                  </div>
                </div>
              </div>

              <div className="relative mx-auto flex aspect-[4/5] w-full max-w-sm items-center justify-center overflow-hidden rounded-[32px] border border-cyan-400/20 bg-gradient-to-b from-slate-900 via-slate-950 to-cyan-950/40 p-8">
                <div className="absolute -left-10 top-10 h-28 w-28 rounded-full bg-cyan-400/20 blur-3xl" />
                <div className="absolute -right-6 bottom-8 h-36 w-36 rounded-full bg-sky-400/20 blur-3xl" />
                <div className="relative w-full rounded-[28px] border border-white/10 bg-slate-950/75 p-6 shadow-[0_24px_80px_rgba(8,47,73,0.45)] backdrop-blur-sm">
                  <div className="mb-5 flex items-center justify-between">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-cyan-300">Workspace</p>
                      <p className="mt-2 text-lg font-semibold text-slate-100">Operator Console</p>
                    </div>
                    <Image src="/globe.svg" alt="Decorative login illustration" width={46} height={46} className="opacity-90" />
                  </div>
                  <div className="space-y-3">
                    <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-3">
                      <div className="h-2.5 w-20 rounded-full bg-cyan-300/75" />
                      <div className="mt-3 h-2 w-full rounded-full bg-slate-800" />
                      <div className="mt-2 h-2 w-4/5 rounded-full bg-slate-800" />
                    </div>
                    <div className="grid grid-cols-[0.9fr_1.1fr] gap-3">
                      <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-3">
                        <div className="h-16 rounded-xl bg-gradient-to-br from-cyan-400/20 to-transparent" />
                      </div>
                      <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-3">
                        <div className="h-2.5 w-16 rounded-full bg-slate-700" />
                        <div className="mt-3 space-y-2">
                          <div className="h-2 rounded-full bg-slate-800" />
                          <div className="h-2 rounded-full bg-slate-800" />
                          <div className="h-2 w-2/3 rounded-full bg-slate-800" />
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-[32px] border border-slate-800 bg-slate-950/88 p-8 shadow-[0_28px_90px_rgba(2,6,23,0.4)]">
          <h2 className="text-xl font-semibold text-slate-100">Sign in</h2>
          <p className="mt-2 text-sm text-slate-500">Use an available account method to continue.</p>

          {backendAvailability === "offline" && (
            <div className="mt-5 rounded-2xl border border-rose-500/25 bg-rose-500/10 p-4 text-sm text-rose-100">
              <p className="font-semibold">Control server unavailable</p>
              <p className="mt-2 text-rose-100/80">Reconnect to the backend and try again.</p>
              <button
                onClick={async () => {
                  setError(null);
                  try {
                    await onRetry();
                  } catch (retryError) {
                    setError(retryError instanceof Error ? retryError.message : "Retry failed");
                  }
                }}
                className="mt-4 rounded-xl border border-rose-300/30 bg-slate-950/40 px-4 py-2 text-xs font-semibold text-rose-100 hover:bg-slate-900"
              >
                Retry Server Check
              </button>
            </div>
          )}

          {authNotice && backendAvailability !== "offline" && (
            <div className="mt-5 rounded-2xl border border-amber-500/25 bg-amber-500/10 p-4 text-sm text-amber-100">
              <p className="font-semibold">Re-login required</p>
              <p className="mt-2 text-amber-100/80">{authNotice}</p>
            </div>
          )}

          <div className="mt-6 rounded-[28px] border border-slate-800 bg-slate-900/55 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-100">Account access</p>
                <p className="mt-1 text-xs text-slate-500">Choose a sign-in method that is currently enabled on the server.</p>
              </div>
              <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                <span className={`rounded-full border px-2 py-1 ${localLoginEnabled ? "border-cyan-400/30 text-cyan-200" : "border-slate-700 text-slate-500"}`}>Local</span>
                <span className={`rounded-full border px-2 py-1 ${microsoftLoginEnabled ? "border-emerald-400/30 text-emerald-200" : "border-slate-700 text-slate-500"}`}>Microsoft</span>
              </div>
            </div>

            {localLoginEnabled && (
              <div className="mt-5 space-y-3">
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Username"
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-cyan-500"
                  disabled={busy !== "idle" || backendAvailability === "offline"}
                />
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Password"
                  type="password"
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-cyan-500"
                  disabled={busy !== "idle" || backendAvailability === "offline"}
                />
                <button
                  onClick={async () => {
                    setBusy("local");
                    setError(null);
                    try {
                      await onLocalLogin(username, password);
                    } catch (loginError) {
                      setError(loginError instanceof Error ? loginError.message : "Local login failed");
                    } finally {
                      setBusy("idle");
                    }
                  }}
                  disabled={busy !== "idle" || !username || !password || backendAvailability === "offline"}
                  className="w-full rounded-xl bg-cyan-400 px-4 py-2.5 text-sm font-semibold text-slate-950 transition-colors hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                >
                  {busy === "local" ? "Signing in..." : "Sign in"}
                </button>
              </div>
            )}

            {localLoginEnabled && microsoftLoginEnabled && (
              <div className="my-5 flex items-center gap-3 text-xs uppercase tracking-[0.2em] text-slate-600">
                <div className="h-px flex-1 bg-slate-800" />
                <span>or</span>
                <div className="h-px flex-1 bg-slate-800" />
              </div>
            )}

            <button
              onClick={async () => {
                setBusy("microsoft");
                setError(null);
                try {
                  await onMicrosoftLogin();
                } catch (loginError) {
                  setError(loginError instanceof Error ? loginError.message : "Microsoft login failed");
                  setBusy("idle");
                }
              }}
              disabled={!microsoftLoginEnabled || busy !== "idle" || backendAvailability === "offline"}
              className="w-full rounded-xl border border-emerald-400/40 bg-emerald-400/15 px-4 py-2.5 text-sm font-semibold text-emerald-100 transition-colors hover:bg-emerald-400/25 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500"
            >
              {busy === "microsoft" ? "Redirecting..." : "Continue with Microsoft"}
            </button>
          </div>

          {error && <p className="mt-4 text-sm text-rose-300">{error}</p>}
        </section>
      </div>
    </main>
  );
}

type ProcessFocusTarget = {
  pid?: number | null;
  taskId?: string | null;
};

function DashboardShell({ session, onLogout, socketEnabled }: { session: AuthSession; onLogout: () => Promise<void>; socketEnabled: boolean }) {
  const { agents, connected, sendCommand, latestScreenshotEvent, requestProcessScreenshot, requestDesktopScreenshot, watchProcessManager, unwatchProcessManager, refreshAgents } = useAgentSocket(socketEnabled);
  const agentIds = Object.keys(agents);
  const { data: taskRows } = useTasks();
  const { session: guacamoleSession } = useGuacamoleWorkspace();
  const canOperate = useMemo(() => hasMinimumRole(session.user.roles, "operator"), [session.user.roles]);
  const canManageSettings = useMemo(() => hasMinimumRole(session.user.roles, "admin"), [session.user.roles]);
  const availablePages = useMemo<MenuPage[]>(() => {
    const pages: MenuPage[] = ["agents", "tasks", "deployments"];
    if (canManageSettings) {
      pages.push("settings");
    }
    return pages;
  }, [canManageSettings]);

  const [activePage, setActivePage] = useState<MenuPage>("agents");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [preferredAgentTab, setPreferredAgentTab] = useState<AgentTab | undefined>(undefined);
  const [processFocus, setProcessFocus] = useState<ProcessFocusTarget | null>(null);
  const [tasksEntryMode, setTasksEntryMode] = useState<"all" | "active">("all");
  const [taskAgentFilter, setTaskAgentFilter] = useState<string | null>(null);
  const { data: selectedAgentState, loading: selectedAgentLoading } = useAgentState(selectedAgent);
  const activeTaskCount = taskRows.filter((task) => task.status === "running" || task.status === "queued").length;

  const handleSelectAgent = (agentId: string, preferredTab?: AgentTab) => {
    setSelectedAgent(agentId);
    setPreferredAgentTab(preferredTab);
    setProcessFocus(null);
  };

  const handleBack = () => {
    setSelectedAgent(null);
    setPreferredAgentTab(undefined);
    setProcessFocus(null);
  };

  const handleNavigate = (page: MenuPage) => {
    if (page === "settings" && !canManageSettings) {
      return;
    }
    setActivePage(page);
    setTasksEntryMode("all");
    setTaskAgentFilter(null);
    if (page !== "agents") {
      setSelectedAgent(null);
      setPreferredAgentTab(undefined);
      setProcessFocus(null);
    }
  };

  const handleOpenTaskTracker = (agentId?: string | null) => {
    setActivePage("tasks");
    setSelectedAgent(null);
    setPreferredAgentTab(undefined);
    setProcessFocus(null);
    setTasksEntryMode("active");
    setTaskAgentFilter(agentId ?? null);
  };

  const handleOpenTaskProcess = (agentId: string, pid?: number | null, taskId?: string | null) => {
    setActivePage("agents");
    setSelectedAgent(agentId);
    setPreferredAgentTab("processes");
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
        currentUser={session.user}
        onLogout={onLogout}
        availablePages={availablePages}
        guacamoleSession={guacamoleSession ? {
          agentId: guacamoleSession.agentId,
          connected: guacamoleSession.connected,
          minimized: guacamoleSession.minimized,
          fullscreen: guacamoleSession.fullscreen,
        } : null}
      />

      <main className="flex-1 overflow-y-auto p-6">
        {activePage === "agents" && !selectedAgent && (
          <AgentList
            agents={agents}
            connected={connected}
            tasks={taskRows}
            canPrepareDeployment={canOperate}
            canManageAgents={canManageSettings}
            onSelectAgent={handleSelectAgent}
            onOpenTaskTracker={() => handleOpenTaskTracker()}
            onAgentsChanged={refreshAgents}
          />
        )}

        {activePage === "agents" && selectedAgent && agents[selectedAgent] && (
          <AgentDetail
            key={`${selectedAgent}:${preferredAgentTab ?? "overview"}:${processFocus?.taskId ?? ""}:${processFocus?.pid ?? ""}`}
            agentId={selectedAgent}
            state={selectedAgentState ?? agents[selectedAgent]}
            tasks={taskRows.filter((task) => task.agent_id === selectedAgent)}
            canOperate={canOperate}
            canManageAccess={canManageSettings}
            sendCommand={sendCommand}
            latestScreenshotEvent={latestScreenshotEvent}
            onCaptureProcessScreenshot={requestProcessScreenshot}
            onCaptureDesktopScreenshot={requestDesktopScreenshot}
            onWatchProcessManager={watchProcessManager}
            onUnwatchProcessManager={unwatchProcessManager}
            onBack={handleBack}
            onOpenTaskTracker={() => handleOpenTaskTracker(selectedAgent)}
            preferredTab={processFocus ? "processes" : preferredAgentTab}
            focusedProcess={processFocus}
          />
        )}

        {activePage === "agents" && selectedAgent && selectedAgentLoading && (
          <div className="mt-3 text-xs text-slate-500">Refreshing full agent snapshot...</div>
        )}

        {activePage === "tasks" && (
          <TasksPage agents={agents} onOpenTaskProcess={handleOpenTaskProcess} entryMode={tasksEntryMode} agentFilterId={taskAgentFilter} canManageTasks={canOperate} />
        )}
        {activePage === "deployments" && <DeploymentsPage canOperate={canOperate} />}
        {activePage === "settings" && (canManageSettings ? <SettingsPage /> : <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-6 text-sm text-slate-400">Settings require admin role.</div>)}
      </main>
    </div>
  );
}

function DashboardLoadingScreen({
  stage,
}: {
  stage: "auth" | "workspace";
}) {
  const isAuthStage = stage === "auth";
  const progressClassName = isAuthStage ? "w-[38%]" : "w-[78%]";

  return (
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,#0f766e_0%,#0f172a_34%,#020617_100%)] px-6 py-10">
      <div className="w-full max-w-xl rounded-[32px] border border-cyan-500/15 bg-slate-950/78 p-8 shadow-[0_32px_120px_rgba(2,6,23,0.48)]">
        <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-300">Workspace</p>
        <h1 className="mt-4 text-3xl font-semibold text-slate-50">{isAuthStage ? "Checking authentication status" : "Preparing dashboard"}</h1>
        <p className="mt-3 text-sm leading-6 text-slate-400">
          {isAuthStage
            ? "Verifying the active session and reading the access configuration before the workspace boot sequence begins."
            : "Finalizing session state and establishing the control channel before the main workspace is rendered."}
        </p>
        <div className="mt-8 h-2 overflow-hidden rounded-full bg-slate-800">
          <div className={`h-full animate-pulse rounded-full bg-cyan-400 transition-[width] duration-500 ${progressClassName}`} />
        </div>
      </div>
    </main>
  );
}

export default function Dashboard() {
  const { session, authConfig, loading, backendAvailability, authNotice, refresh, loginLocal, beginMicrosoftLogin, logout } = useUserAuth();
  const localLoginEnabled = useMemo(() => Boolean(authConfig?.local_bootstrap_available), [authConfig?.local_bootstrap_available]);
  const microsoftLoginEnabled = useMemo(() => Boolean(authConfig?.microsoft_login_available), [authConfig?.microsoft_login_available]);
  const [dashboardReadySessionKey, setDashboardReadySessionKey] = useState<string>("");
  const dashboardReady = Boolean(session && dashboardReadySessionKey === (session.access_token || session.user.subject));

  useEffect(() => {
    if (!session) {
      return;
    }

    const sessionKey = session.access_token || session.user.subject;
    const timer = window.setTimeout(() => {
      setDashboardReadySessionKey(sessionKey);
    }, 700);

    return () => {
      window.clearTimeout(timer);
    };
  }, [session]);

  if (loading) {
    return <DashboardLoadingScreen stage="auth" />;
  }

  if (!session) {
    return (
      <AuthScreen
        localLoginEnabled={localLoginEnabled}
        microsoftLoginEnabled={microsoftLoginEnabled}
        backendAvailability={backendAvailability}
        authNotice={authNotice}
        onRetry={refresh}
        onLocalLogin={loginLocal}
        onMicrosoftLogin={beginMicrosoftLogin}
      />
    );
  }

  if (!dashboardReady) {
    return <DashboardLoadingScreen stage="workspace" />;
  }

  return (
    <GuacamoleWorkspaceProvider>
      <DashboardShell session={session} onLogout={logout} socketEnabled={dashboardReady} />
    </GuacamoleWorkspaceProvider>
  );
}
