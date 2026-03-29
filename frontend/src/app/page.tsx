"use client";

import { useEffect, useMemo, useState } from "react";
import { useGuacamoleWorkspace } from "@/components/GuacamoleWorkspace";
import { useAgentSocket } from "@/hooks/useAgentSocket";
import { useAgentState } from "@/hooks/useAgentStateAPI";
import { useTasks } from "@/hooks/useTaskAPI";
import { Sidebar, type MenuPage } from "@/components/Sidebar";
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
    <main className="flex min-h-screen items-center justify-center bg-[radial-gradient(circle_at_top,#164e63_0%,#0f172a_38%,#020617_100%)] px-6 py-10">
      <div className="grid w-full max-w-5xl gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="rounded-[32px] border border-cyan-500/15 bg-slate-950/75 p-8 shadow-[0_32px_120px_rgba(2,6,23,0.48)]">
          <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-300">Identity</p>
          <h1 className="mt-4 text-4xl font-semibold text-slate-50">My Orciestra Access</h1>
          <p className="mt-4 max-w-xl text-sm leading-6 text-slate-400">
            Serwer teraz używa warstwy użytkownika. Na pierwszym uruchomieniu możesz wejść lokalnym adminem z ENV i skonfigurować Azure SSO. Po aktywacji Microsoft Entra lokalny bootstrap przestaje działać.
          </p>
          <div className="mt-8 grid gap-4 md:grid-cols-3">
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Bootstrap</p>
              <p className="mt-3 text-lg font-semibold text-slate-100">ENV only</p>
              <p className="mt-2 text-xs text-slate-400">Lokalny admin nie trafia do bazy. Jest odczytywany wyłącznie z procesu serwera.</p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">SSO Lock</p>
              <p className="mt-3 text-lg font-semibold text-slate-100">One-way</p>
              <p className="mt-2 text-xs text-slate-400">Po aktywacji provider jest blokowany i nie da się wrócić do lokalnego modelu.</p>
            </div>
            <div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
              <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Role Mapping</p>
              <p className="mt-3 text-lg font-semibold text-slate-100">Azure Groups</p>
              <p className="mt-2 text-xs text-slate-400">Role aplikacji będą nadawane automatycznie na podstawie mapowania grup Entra do ról appki.</p>
            </div>
          </div>
        </section>

        <section className="rounded-[32px] border border-slate-800 bg-slate-950/85 p-8 shadow-[0_28px_90px_rgba(2,6,23,0.4)]">
          <h2 className="text-xl font-semibold text-slate-100">Sign in</h2>
          <p className="mt-2 text-sm text-slate-500">Wybierz dostępny tryb logowania dla aktualnego stanu serwera.</p>

          {backendAvailability === "offline" && (
            <div className="mt-5 rounded-2xl border border-rose-500/25 bg-rose-500/10 p-4 text-sm text-rose-100">
              <p className="font-semibold">Control server unavailable</p>
              <p className="mt-2 text-rose-100/80">
                The dashboard lost the backend connection. User sessions on this server live only in memory, so after restart you must sign in again.
              </p>
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

          <div className="mt-6 space-y-6">
            <div className={`rounded-2xl border p-5 ${localLoginEnabled ? "border-cyan-500/25 bg-cyan-500/10" : "border-slate-800 bg-slate-900/50 opacity-60"}`}>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-100">Local bootstrap admin</p>
                  <p className="mt-1 text-xs text-slate-500">Dostępne tylko zanim aktywujesz Microsoft Entra.</p>
                </div>
                <span className="rounded-full border border-slate-700 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                  {localLoginEnabled ? "enabled" : "disabled"}
                </span>
              </div>

              <div className="mt-4 space-y-3">
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="Username"
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-cyan-500"
                  disabled={!localLoginEnabled || busy !== "idle" || backendAvailability === "offline"}
                />
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="Password"
                  type="password"
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-cyan-500"
                  disabled={!localLoginEnabled || busy !== "idle" || backendAvailability === "offline"}
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
                  disabled={!localLoginEnabled || busy !== "idle" || !username || !password || backendAvailability === "offline"}
                  className="w-full rounded-xl bg-cyan-400 px-4 py-2.5 text-sm font-semibold text-slate-950 transition-colors hover:bg-cyan-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                >
                  {busy === "local" ? "Signing in..." : "Sign in with local admin"}
                </button>
              </div>
            </div>

            <div className={`rounded-2xl border p-5 ${microsoftLoginEnabled ? "border-emerald-500/20 bg-emerald-500/10" : "border-slate-800 bg-slate-900/50 opacity-60"}`}>
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-100">Microsoft Entra SSO</p>
                  <p className="mt-1 text-xs text-slate-500">Aktywowany po skonfigurowaniu tenant/client i włączeniu providera w Settings.</p>
                </div>
                <span className="rounded-full border border-slate-700 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-slate-400">
                  {microsoftLoginEnabled ? "active" : "not ready"}
                </span>
              </div>
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
                className="mt-4 w-full rounded-xl border border-emerald-400/40 bg-emerald-400/15 px-4 py-2.5 text-sm font-semibold text-emerald-100 transition-colors hover:bg-emerald-400/25 disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500"
              >
                {busy === "microsoft" ? "Redirecting..." : "Continue with Microsoft"}
              </button>
            </div>
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
  const { agents, connected, sendCommand, latestScreenshotEvent, requestProcessScreenshot, requestDesktopScreenshot, watchProcessManager, unwatchProcessManager } = useAgentSocket(socketEnabled);
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
    if (page === "settings" && !canManageSettings) {
      return;
    }
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
            canOperate={canOperate}
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
  const [dashboardReady, setDashboardReady] = useState(false);

  useEffect(() => {
    if (!session) {
      setDashboardReady(false);
      return;
    }

    setDashboardReady(false);
    const timer = window.setTimeout(() => {
      setDashboardReady(true);
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
