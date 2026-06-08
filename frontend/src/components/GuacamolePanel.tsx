"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import {
  kickGuacamoleOwnerSession,
  useGuacamoleSession,
  useGuacamoleVmUserSessions,
  type GuacamoleVmUserSession,
} from "@/hooks/useGuacamole";
import { useGuacamoleWorkspace } from "@/components/GuacamoleWorkspace";
import type { WorkspaceConnection } from "@/components/guacamole/types";
import { loadAuthSession } from "@/lib/auth";
import { formatRoleLabel, hasMinimumRole } from "@/lib/rbac";

interface GuacamolePanelProps {
  agentId: string;
  active?: boolean;
  canOperate?: boolean;
}

function InfoRow({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono text-slate-200 text-right break-all">{value || "-"}</span>
    </div>
  );
}

function formatWorkspaceTime(timestamp?: number) {
  if (!timestamp) {
    return "Not started";
  }

  return new Date(timestamp).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTransferState(enabled: boolean): string {
  return enabled ? "Enabled" : "Disabled";
}

function buildAvatarLabel(session: GuacamoleVmUserSession) {
  const initials = session.identity?.avatar_initials?.trim();
  if (initials) {
    return initials.slice(0, 2).toUpperCase();
  }

  const fallback = (session.identity?.display_name || session.username || "U").trim();
  const tokens = fallback.replace("\\", " ").replace("_", " ").replace(".", " ").split(" ").filter(Boolean);
  if (tokens.length >= 2) {
    return `${tokens[0][0]}${tokens[1][0]}`.toUpperCase();
  }
  return fallback.slice(0, 2).toUpperCase();
}

function VmUserAvatar({ session }: { session: GuacamoleVmUserSession }) {
  const imageUrl = session.identity?.avatar_url?.trim();
  const label = buildAvatarLabel(session);
  const alt = session.identity?.display_name || session.username;

  if (imageUrl) {
    return (
      <Image
        src={imageUrl}
        alt={alt}
        width={44}
        height={44}
        unoptimized
        className="h-11 w-11 rounded-xl border border-slate-700 object-cover"
      />
    );
  }

  return (
    <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-slate-700 bg-slate-900 text-xs font-semibold text-slate-200">
      {label}
    </div>
  );
}

function buildInUseLabel(session: GuacamoleVmUserSession) {
  const users = session.in_use_by_users?.filter(Boolean) ?? [];
  const user = users[0] ?? session.in_use_by;
  if (!user) {
    return "In use";
  }

  const primaryLabel = user.display_name || user.username || user.email || user.subject;
  if (users.length <= 1) {
    return `In use by ${primaryLabel}`;
  }

  const secondaryLabels = users
    .slice(1, 3)
    .map((entry) => entry.display_name || entry.username || entry.email || entry.subject)
    .filter(Boolean);
  const remainingCount = Math.max(0, users.length - 1 - secondaryLabels.length);
  const suffixParts = [...secondaryLabels];
  if (remainingCount > 0) {
    suffixParts.push(`+${remainingCount} more`);
  }
  return `In use by ${primaryLabel}, ${suffixParts.join(", ")}`;
}

function InUseByBadge({ session }: { session: GuacamoleVmUserSession }) {
  const user = session.in_use_by_users?.[0] ?? session.in_use_by;
  const fallbackSource = (user?.avatar_initials || user?.display_name || user?.username || "U").trim();
  const fallbackInitials = fallbackSource.slice(0, 2).toUpperCase();
  const userCount = session.in_use_by_users?.length ?? (user ? 1 : 0);

  return (
    <span className="inline-flex max-w-full items-center gap-2 rounded-full bg-amber-500/15 px-2 py-1 text-[11px] font-medium text-amber-200">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-full border border-amber-400/20 bg-amber-500/20 text-[10px] font-semibold text-amber-100">
        {user?.avatar_url ? (
          <Image
            src={user.avatar_url}
            alt={buildInUseLabel(session)}
            width={20}
            height={20}
            unoptimized
            className="h-5 w-5 object-cover"
          />
        ) : (
          fallbackInitials
        )}
      </span>
      <span className="truncate">{buildInUseLabel(session)}</span>
      {userCount > 1 && (
        <span className="rounded-full border border-amber-400/20 bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-amber-50">
          {userCount}
        </span>
      )}
    </span>
  );
}

function getSelectedSession(sessions: GuacamoleVmUserSession[], selectedSessionKey: string | null) {
  return sessions.find((entry) => entry.session_key === selectedSessionKey) || sessions[0] || null;
}

function getWorkspaceStatusPresentation(session: WorkspaceConnection | null, isCurrentAgent: boolean, hasGlobalSession: boolean) {
  const restoringSession = Boolean(
    isCurrentAgent
    && session?.clientSession
    && !session.connected
    && ["queued", "preparing", "resuming", "credentials_submitted"].includes(session.status),
  );

  if (session?.connected && isCurrentAgent) {
    return {
      className: "bg-emerald-500/15 text-emerald-300",
      label: "Connected",
    };
  }

  if (restoringSession) {
    return {
      className: "bg-cyan-500/15 text-cyan-300",
      label: "Restoring session",
    };
  }

  if (isCurrentAgent) {
    return {
      className: "bg-blue-500/15 text-blue-300",
      label: session?.status || "Starting",
    };
  }

  if (hasGlobalSession) {
    return {
      className: "bg-amber-500/15 text-amber-300",
      label: "In Use",
    };
  }

  return {
    className: "bg-slate-700 text-slate-300",
    label: "Idle",
  };
}

export function GuacamolePanel({ agentId, active = false, canOperate = false }: GuacamolePanelProps) {
  const { data, loading, sessionLoading } = useGuacamoleSession(agentId);
  const { data: vmUserSessions, loading: vmUserSessionsLoading, refresh: refreshVmUserSessions } = useGuacamoleVmUserSessions(agentId);
  const {
    session,
    openSession,
    resumeSession,
    minimizeSession,
    fullscreenSession,
    closeSession,
    isCurrentAgentSession,
  } = useGuacamoleWorkspace();
  const [selectedSessionKey, setSelectedSessionKey] = useState<string | null>(null);
  const [readOnly, setReadOnly] = useState(false);
  const [kickInFlightSubject, setKickInFlightSubject] = useState<string | null>(null);

  const authSession = loadAuthSession();
  const canViewRemote = canOperate || hasMinimumRole(authSession?.user.roles, "viewer");
  const accessPolicy = data?.access ?? session?.accessPolicy ?? null;
  const viewRule = accessPolicy?.permissions.view;
  const interactRule = accessPolicy?.permissions.interact;
  const uploadRule = accessPolicy?.permissions.upload;
  const downloadRule = accessPolicy?.permissions.download;
  const effectivePermissions = accessPolicy?.effective_permissions ?? {};
  const minimumRole = viewRule?.minimum_role ?? "operator";
  const interactiveMinimumRole = interactRule?.minimum_role ?? "admin";
  const canOpenRemote = accessPolicy ? effectivePermissions.view === true : loading;
  const canUseInteractive = accessPolicy ? effectivePermissions.interact === true : false;
  const canRecord = accessPolicy ? effectivePermissions.recording === true : false;
  const canKickSessions = accessPolicy ? effectivePermissions.session_kick === true : false;
  const operatorReadOnlyOnly = canOpenRemote && !canUseInteractive;

  useEffect(() => {
    if (operatorReadOnlyOnly) {
      setReadOnly(true);
    }
  }, [operatorReadOnlyOnly]);

  const activeVmSessions = vmUserSessions?.sessions || [];

  if (!active) {
    return null;
  }

  if (!canViewRemote) {
    return null;
  }

  if (!canOpenRemote) {
    return (
      <div className="rounded-xl border border-slate-700 bg-slate-800/30 p-4 text-sm text-slate-400">
        Remote desktop session control requires {formatRoleLabel(minimumRole)} role for this agent.
      </div>
    );
  }

  const hasGlobalSession = Boolean(session);
  const isCurrentAgent = isCurrentAgentSession(agentId);
  const currentError = isCurrentAgent ? session?.error : null;
  const workspaceStatusPresentation = getWorkspaceStatusPresentation(session, isCurrentAgent, hasGlobalSession);
  const effectiveSelectedSessionKey = activeVmSessions.some((entry) => entry.session_key === selectedSessionKey)
    ? selectedSessionKey
    : (activeVmSessions.find((entry) => entry.is_preferred) || activeVmSessions[0])?.session_key || null;
  const selectedVmSession = getSelectedSession(activeVmSessions, effectiveSelectedSessionKey);
  const selectedConnectionId = selectedVmSession?.guacamole?.connection_id || data?.connection_id || "";
  const selectedConnectionName = selectedVmSession?.guacamole?.connection_name || data?.connection_label || "Remote Desktop";
  const selectedUsername = selectedVmSession?.username || data?.resolved_fields?.guacamole_username || "";
  const preferredUsername = data?.resolved_fields?.guacamole_username || activeVmSessions.find((entry) => entry.is_preferred)?.username || "";
  const effectiveReadOnly = operatorReadOnlyOnly || readOnly;

  const openSelectedWorkspace = () => {
    openSession(agentId, selectedConnectionName, {
      readOnly: effectiveReadOnly,
      recorded: false,
      requestedConnectionId: selectedConnectionId || null,
      requestedVmUsername: selectedUsername || null,
    });
  };

  const openRecordedWorkspace = () => {
    openSession(agentId, `${selectedConnectionName} (Recorded)`, {
      readOnly: true,
      recorded: true,
      requestedConnectionId: selectedConnectionId || null,
      requestedVmUsername: selectedUsername || null,
    });
  };

  const kickSessionOwner = async (owner: NonNullable<GuacamoleVmUserSession["in_use_by_users"]>[number]) => {
    const ownerLabel = owner.display_name || owner.username || owner.email || owner.subject;
    const confirmed = typeof window === "undefined"
      ? true
      : window.confirm(`Close the remote session used by ${ownerLabel}?`);
    if (!confirmed) {
      return;
    }

    setKickInFlightSubject(owner.subject);
    try {
      await kickGuacamoleOwnerSession(agentId, owner.subject);
      await refreshVmUserSessions();
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to close the selected session";
      if (typeof window !== "undefined") {
        window.alert(message);
      }
    } finally {
      setKickInFlightSubject(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-slate-700/70 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">Remote Access</h2>
            <p className="text-xs text-slate-500 mt-1">
              The backend now maintains Guacamole connections per signed-in VM user inside the agent group. Choose the Windows session you want to open and launch it with the access mode allowed for your role.
            </p>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <label className="inline-flex items-center gap-2 rounded-md border border-slate-700 bg-slate-900/70 px-3 py-1.5 text-xs text-slate-300">
              <input
                type="checkbox"
                checked={effectiveReadOnly}
                onChange={(event) => setReadOnly(event.target.checked)}
                disabled={operatorReadOnlyOnly}
                className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-950 text-cyan-400 focus:ring-cyan-500/40"
              />
              Read-only
            </label>
            <button
              onClick={openSelectedWorkspace}
              disabled={!selectedConnectionId || sessionLoading}
              className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:border-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sessionLoading ? "Connecting..." : effectiveReadOnly ? "Open Read-only" : isCurrentAgent ? "Open Workspace" : hasGlobalSession ? "Switch Session" : "Connect"}
            </button>
            <button
              onClick={openRecordedWorkspace}
              disabled={!selectedConnectionId || sessionLoading || !data?.recording?.enabled || !data?.recording?.configured || !canRecord}
              className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-100 hover:border-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {sessionLoading ? "Preparing..." : "Start Recorded Session"}
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
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Connection Profile</span>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                  selectedConnectionId ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"
                }`}>
                  {loading ? "Loading" : selectedConnectionId ? "Ready" : "Unavailable"}
                </span>
              </div>
              <InfoRow label="Workspace mode" value={effectiveReadOnly ? "Read-only" : "Interactive"} />
              <InfoRow label="Access threshold" value={formatRoleLabel(minimumRole)} />
              <InfoRow label="Interactive threshold" value={formatRoleLabel(interactiveMinimumRole)} />
              <InfoRow label="File upload" value={formatTransferState(uploadRule?.enabled !== false)} />
              <InfoRow label="File download" value={formatTransferState(downloadRule?.enabled !== false)} />
              <InfoRow label="Recording Profile" value={data?.recording?.enabled ? (data.recording.configured ? "Ready for on-demand use" : "Misconfigured") : "Disabled"} />
              <InfoRow label="Session Capture" value={isCurrentAgent ? (session?.recorded ? "Recorded" : "Off") : "-"} />
              <InfoRow label="Connection" value={selectedConnectionName} />
              <InfoRow label="Resolution" value={data?.display?.mode === "fixed"
                ? `${data.display.width}x${data.display.height} @ ${data.display.dpi} DPI`
                : `Dynamic @ ${data?.display?.dpi ?? 96} DPI`} />
              <InfoRow label="Selected VM user" value={selectedUsername || "Automatic"} />
              <InfoRow label="Preferred VM user" value={preferredUsername || "Automatic"} />
              <InfoRow label="Agent group" value={selectedVmSession?.guacamole?.group_name || data?.resolved_fields?.guacamole_group} />
              <InfoRow
                label="Target host"
                value={data?.resolved_fields?.guacamole_target_host || data?.resolved_fields?.hostname}
              />
            </div>

            <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Workspace Status</span>
                <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${workspaceStatusPresentation.className}`}>
                  {workspaceStatusPresentation.label}
                </span>
              </div>
              <InfoRow label="Current agent" value={session?.agentId || "None"} />
              <InfoRow label="Window" value={session?.fullscreen ? "Fullscreen" : session?.minimized ? "Minimized" : session ? "Docked workspace" : "Closed"} />
              <InfoRow label="Started" value={formatWorkspaceTime(session?.launchedAt)} />
              <InfoRow label="Input mode" value={session?.readOnly ? "Read-only" : session ? "Interactive" : "-"} />
              {isCurrentAgent && currentError && <p className="text-xs text-rose-300">{currentError}</p>}
              {!isCurrentAgent && hasGlobalSession && (
                <p className="text-xs text-amber-200/90">
                  The current workspace is attached to another agent. Select Switch Session if you want to move this single live workspace here.
                </p>
              )}
            </div>

            <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Selected Session</span>
                <span className="rounded-full bg-slate-800 px-2.5 py-1 text-[11px] font-medium text-slate-300">
                  {selectedVmSession ? "Targeted" : "Automatic"}
                </span>
              </div>
              {selectedVmSession ? (
                <div className="rounded-lg border border-slate-800 bg-slate-950/70 p-3">
                  <div className="flex items-start gap-3">
                    <VmUserAvatar session={selectedVmSession} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-slate-100">
                        {selectedVmSession.identity?.display_name || selectedVmSession.username}
                      </p>
                      <p className="mt-1 text-[11px] text-slate-500">
                        {selectedVmSession.identity?.email || selectedVmSession.username}
                      </p>
                      <p className="mt-2 text-[11px] text-slate-400">
                        Connection {selectedVmSession.guacamole.connection_name || selectedVmSession.username} under group {selectedVmSession.guacamole.group_name || "-"}
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-slate-700 bg-slate-950/60 px-3 py-4 text-sm text-slate-400">
                  No VM session is available to target yet.
                </div>
              )}
            </div>
          </div>

          <div className="rounded-lg border border-slate-700/80 bg-slate-950/95 min-h-[22rem] overflow-hidden p-6">
            <div className="flex h-full flex-col justify-between gap-6">
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-slate-100">Signed-In VM Users</h3>
                <p className="text-sm text-slate-400">
                  This inventory comes from the Windows agent heartbeat and is reconciled on the backend into per-user Guacamole connections under the agent group. If a signed-in VM user matches a currently authenticated app identity, the mapped profile avatar is shown here.
                </p>
                <p className="text-sm text-slate-400">
                  {operatorReadOnlyOnly
                    ? `Your role can open this agent only in read-only mode. Interactive control requires ${formatRoleLabel(interactiveMinimumRole)}.`
                    : "The read-only toggle keeps the same remote stream but blocks keyboard and mouse input inside the operator workspace."}
                </p>
              </div>

              {activeVmSessions.length > 0 ? (
                <div className="space-y-2">
                  {activeVmSessions.map((vmSession) => {
                    const isSelected = selectedVmSession?.session_key === vmSession.session_key;
                    const isWorkspaceTarget = Boolean(isCurrentAgent && session?.requestedConnectionId && vmSession.guacamole.connection_id && session.requestedConnectionId === vmSession.guacamole.connection_id);
                    return (
                      <div
                        key={vmSession.session_key}
                        role="button"
                        tabIndex={0}
                        onClick={() => setSelectedSessionKey(vmSession.session_key)}
                        onKeyDown={(event) => {
                          if (event.key !== "Enter" && event.key !== " ") {
                            return;
                          }
                          event.preventDefault();
                          setSelectedSessionKey(vmSession.session_key);
                        }}
                        className={`w-full rounded-lg border px-3 py-3 text-left transition ${
                          isSelected
                            ? "border-cyan-500/40 bg-cyan-500/10"
                            : "border-slate-800 bg-slate-950/70 hover:border-slate-700"
                        }`}
                        aria-pressed={isSelected}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex min-w-0 items-start gap-3">
                            <VmUserAvatar session={vmSession} />
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-slate-100">
                                {vmSession.identity?.display_name || vmSession.username}
                              </p>
                              <p className="mt-1 truncate text-[11px] text-slate-500">
                                {vmSession.identity?.email || vmSession.username}
                              </p>
                              <p className="mt-2 text-[11px] text-slate-400">
                                {vmSession.session_name} · Session {vmSession.session_id} · {vmSession.process_count} process{vmSession.process_count === 1 ? "" : "es"}
                              </p>
                              <p className="mt-1 text-[11px] text-slate-500">
                                Guacamole connection: {vmSession.guacamole.connection_name || "Pending"}
                              </p>
                            </div>
                          </div>
                          <div className="flex flex-wrap justify-end gap-2">
                            {vmSession.is_active && (
                              <span className="rounded-full bg-emerald-500/15 px-2 py-1 text-[11px] font-medium text-emerald-300">
                                Active
                              </span>
                            )}
                            {vmSession.is_preferred && (
                              <span className="rounded-full bg-cyan-500/15 px-2 py-1 text-[11px] font-medium text-cyan-300">
                                Preferred
                              </span>
                            )}
                            {vmSession.identity && (
                              <span className="rounded-full bg-indigo-500/15 px-2 py-1 text-[11px] font-medium text-indigo-300">
                                Identity mapped
                              </span>
                            )}
                            {vmSession.is_in_use && <InUseByBadge session={vmSession} />}
                            {isWorkspaceTarget && (
                              <span className="rounded-full bg-blue-500/15 px-2 py-1 text-[11px] font-medium text-blue-300">
                                Workspace target
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
                          <span>Windows state: {vmSession.status || "Unknown"}</span>
                          {vmSession.identity?.auth_provider && <span>Auth profile: {vmSession.identity.auth_provider}</span>}
                        </div>
                        {canKickSessions && (vmSession.in_use_by_users?.length ?? 0) > 0 && (
                          <div className="mt-3 flex flex-wrap gap-2">
                            {vmSession.in_use_by_users?.map((owner) => {
                              const ownerLabel = owner.display_name || owner.username || owner.email || owner.subject;
                              const isBusy = kickInFlightSubject === owner.subject;
                              return (
                                <button
                                  key={`${vmSession.session_key}:${owner.subject}`}
                                  type="button"
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    void kickSessionOwner(owner);
                                  }}
                                  disabled={isBusy}
                                  className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-[11px] font-medium text-rose-200 hover:border-rose-400 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {isBusy ? `Closing ${ownerLabel}...` : `Kick ${ownerLabel}`}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/60 p-4 text-sm text-slate-400">
                  {vmUserSessionsLoading
                    ? "Refreshing signed-in VM users..."
                    : "No signed-in VM users are currently reported by the agent."}
                </div>
              )}
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
