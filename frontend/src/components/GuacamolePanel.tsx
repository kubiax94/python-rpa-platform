"use client";

import { useGuacamoleSession } from "@/hooks/useGuacamole";
import { useGuacamoleWorkspace } from "@/components/GuacamoleWorkspace";

interface GuacamolePanelProps {
  agentId: string;
  active?: boolean;
}

function InfoRow({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono text-slate-200 text-right break-all">{value || "-"}</span>
    </div>
  );
}

export function GuacamolePanel({ agentId, active = false }: GuacamolePanelProps) {
  const { data, loading, sessionLoading } = useGuacamoleSession(agentId);
  const {
    session,
    openSession,
    resumeSession,
    minimizeSession,
    fullscreenSession,
    closeSession,
    isCurrentAgentSession,
  } = useGuacamoleWorkspace();

  if (!active) {
    return null;
  }

  const hasGlobalSession = Boolean(session);
  const isCurrentAgent = isCurrentAgentSession(agentId);
  const currentStatus = isCurrentAgent ? session?.status : null;
  const currentError = isCurrentAgent ? session?.error : null;
  const currentConnected = Boolean(isCurrentAgent && session?.connected);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-slate-700/70 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">Remote Desktop Workspace</h2>
            <p className="text-xs text-slate-500 mt-1">
              One global Guacamole session per user. Minimizing keeps the connection alive so you can move through tasks, deployments, and agent views without reconnecting.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              onClick={() => openSession(agentId, data?.connection_label || "Remote Desktop")}
              disabled={!data?.connection_id || sessionLoading}
              className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:border-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sessionLoading ? "Connecting..." : isCurrentAgent ? "Open Workspace" : hasGlobalSession ? "Switch Session" : "Connect"}
            </button>
            {isCurrentAgent && (
              <>
                <button
                  onClick={resumeSession}
                  className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                >
                  Resume
                </button>
                <button
                  onClick={fullscreenSession}
                  className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                >
                  Fullscreen
                </button>
                <button
                  onClick={minimizeSession}
                  className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                >
                  Minimize
                </button>
                <button
                  onClick={closeSession}
                  className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-200 hover:border-rose-400"
                >
                  Close
                </button>
              </>
            )}
          </div>
        </div>

        <div className="grid gap-4 p-4 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Available Connection</span>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                  data?.connection_id ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"
                }`}>
                  {loading ? "Loading" : data?.connection_id ? "Ready" : "Unavailable"}
                </span>
              </div>
              <InfoRow label="Connection" value={data?.connection_label} />
              <InfoRow label="Source" value={data?.source} />
              <InfoRow
                label="Display"
                value={data?.display?.mode === "fixed"
                  ? `${data.display.width}x${data.display.height} @ ${data.display.dpi} DPI`
                  : `Dynamic @ ${data?.display?.dpi ?? 96} DPI`}
              />
              <InfoRow label="Hostname" value={data?.resolved_fields?.hostname} />
              <InfoRow label="WebSocket tunnel" value={data?.tunnels?.websocket} />
              <InfoRow label="HTTP tunnel" value={data?.tunnels?.http} />
            </div>

            <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Global Session</span>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                  currentConnected
                    ? "bg-emerald-500/15 text-emerald-300"
                    : isCurrentAgent
                      ? "bg-blue-500/15 text-blue-300"
                      : hasGlobalSession
                        ? "bg-amber-500/15 text-amber-300"
                        : "bg-slate-700 text-slate-300"
                }`}>
                  {currentConnected ? "Connected" : isCurrentAgent ? currentStatus || "Starting" : hasGlobalSession ? "In Use" : "Idle"}
                </span>
              </div>
              <InfoRow label="Current agent" value={session?.agentId} />
              <InfoRow label="Window" value={session?.fullscreen ? "Fullscreen" : session?.minimized ? "Minimized" : session ? "Workspace" : "Closed"} />
              <InfoRow label="Opened" value={session?.launchedAt ? new Date(session.launchedAt).toLocaleTimeString("pl-PL") : "-"} />
              {isCurrentAgent && currentError && <p className="text-xs text-rose-300">{currentError}</p>}
              {!isCurrentAgent && hasGlobalSession && (
                <p className="text-xs text-amber-200/90">
                  The active global session currently belongs to another agent. Use &quot;Switch Session&quot; if you want this single workspace to move to the current agent.
                </p>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-700/80 bg-slate-950/95 min-h-[22rem] overflow-hidden p-6">
            <div className="flex h-full flex-col justify-between gap-6">
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-slate-100">Global workspace viewer</h3>
                <p className="text-sm text-slate-400">
                  The Guacamole viewer is hosted globally at the dashboard level. That keeps the RDP session alive while you move into tasks, overview pages, or other agents, and minimizing only hides the window.
                </p>
                <p className="text-sm text-slate-400">
                  Keyboard input is now attached to the focused Guacamole viewport instead of the whole document, so app shortcuts and normal typing keep working when the workspace is minimized or inactive.
                </p>
                <p className="text-sm text-slate-400">
                  Yes, you can keep a fixed remote desktop resolution such as 1920x1080 and still use a responsive docked window. When the server display mode is fixed, the workspace scales that remote surface to the current panel size instead of forcing reconnects on resize.
                </p>
              </div>

              <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/60 p-4 text-sm text-slate-400">
                {isCurrentAgent
                  ? "Use Resume or Fullscreen to return to the same live session without reconnecting."
                  : hasGlobalSession
                    ? "The active Guacamole workspace is still available from the global docked window on the dashboard."
                    : "Select Connect to open a single global RDP workspace for the current app user."}
              </div>
            </div>
          </div>
        </div>
      </div>

      {!!data?.warnings?.length && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4">
          <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-300">Warnings</h3>
          <div className="mt-3 space-y-2 text-sm text-amber-100/90">
            {data.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
