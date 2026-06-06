"use client";

import { useState, type ReactNode } from "react";
import { GuacamoleRecordingPlayerDialog } from "@/components/GuacamoleRecordingPlayerDialog";
import {
  killAllTrackedGuacamoleSessions,
  type GuacamoleRecordingEntry,
  useGuacamoleConfig,
  useGuacamoleConnections,
  useGuacamoleRecordings,
  useGuacamoleTrackedSessions,
} from "@/hooks/useGuacamole";
import { describeFrontendWebSocketUrl, withAccessToken } from "@/lib/auth";
import { formatRoleLabel, getHighestRole, type AppRole } from "@/lib/rbac";
import { updateServerSettings, useServerSettings } from "@/hooks/useDeploymentAPI";

type SettingsSection = "general" | "identity" | "guacamole";
const APP_ROLE_OPTIONS: AppRole[] = ["viewer", "operator", "admin"];

function formatDateTime(value?: number | null): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
}

function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) {
    return "-";
  }

  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }

  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  }

  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function formatBytes(value?: number | null): string {
  if (value == null || Number.isNaN(value)) {
    return "-";
  }

  if (value < 1024) {
    return `${value} B`;
  }

  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }

  if (value < 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  return `${(value / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function maskToken(value: string): string {
  if (!value) {
    return "-";
  }

  if (value.length <= 12) {
    return value;
  }

  return `${value.slice(0, 6)}...${value.slice(-6)}`;
}

function SettingsNavItem({
  active,
  title,
  description,
  badge,
  onClick,
}: {
  active: boolean;
  title: string;
  description: string;
  badge?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full rounded-2xl border px-4 py-3 text-left transition-colors ${
        active
          ? "border-cyan-500/40 bg-cyan-500/12 text-slate-100"
          : "border-slate-800 bg-slate-950/55 text-slate-300 hover:border-slate-700 hover:bg-slate-900/70"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">{title}</p>
          <p className="mt-1 text-xs text-slate-500">{description}</p>
        </div>
        {badge && (
          <span className="rounded-full border border-slate-700 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.16em] text-slate-400">
            {badge}
          </span>
        )}
      </div>
    </button>
  );
}

function SectionCard({
  title,
  subtitle,
  aside,
  children,
}: {
  title: string;
  subtitle?: string;
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/72 shadow-[0_18px_60px_rgba(2,6,23,0.35)]">
      <div className="flex items-start justify-between gap-4 border-b border-slate-800 px-5 py-4">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-200">{title}</h2>
          {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
        </div>
        {aside}
      </div>
      <div className="px-5 py-5">{children}</div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  accent = "slate",
  detail,
}: {
  label: string;
  value: string;
  accent?: "slate" | "cyan" | "emerald" | "amber" | "rose";
  detail?: string;
}) {
  const accentClassName = {
    slate: "border-slate-800 bg-slate-950/70 text-slate-100",
    cyan: "border-cyan-500/20 bg-cyan-500/10 text-cyan-100",
    emerald: "border-emerald-500/20 bg-emerald-500/10 text-emerald-100",
    amber: "border-amber-500/20 bg-amber-500/10 text-amber-100",
    rose: "border-rose-500/20 bg-rose-500/10 text-rose-100",
  }[accent];

  return (
    <div className={`rounded-2xl border p-4 ${accentClassName}`}>
      <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">{label}</p>
      <p className="mt-3 text-2xl font-semibold">{value}</p>
      {detail && <p className="mt-2 text-xs text-slate-400">{detail}</p>}
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="max-w-[65%] break-all text-right font-mono text-xs text-slate-200">{value}</span>
    </div>
  );
}

export function SettingsPage() {
  const [activeSection, setActiveSection] = useState<SettingsSection>("general");
  const { data: guacamoleConfig, loading: guacamoleConfigLoading } = useGuacamoleConfig();
  const {
    data: guacamoleConnections,
    loading: connectionsLoading,
    refresh: refreshGuacamoleConnections,
  } = useGuacamoleConnections();
  const {
    data: trackedSessions,
    loading: trackedSessionsLoading,
    refresh: refreshTrackedSessions,
  } = useGuacamoleTrackedSessions();
  const {
    data: recordings,
    loading: recordingsLoading,
    refresh: refreshRecordings,
  } = useGuacamoleRecordings();
  const { data: serverSettings, loading: settingsLoading, refresh: refreshServerSettings } = useServerSettings();
  const [draftDeployment, setDraftDeployment] = useState<null | {
    default_repo_url: string;
    artifact_share_root: string;
    latest_installer_share_template: string;
  }>(null);
  const [draftIdentity, setDraftIdentity] = useState<null | {
    provider: string;
    provider_locked: boolean;
    local_bootstrap_available: boolean;
    session_ttl_seconds: number;
    azure: {
      tenant_id: string;
      client_id: string;
      authority_url: string;
      redirect_path: string;
      scopes: string[];
      client_secret: string;
      client_secret_configured: boolean;
      activated_at?: number | null;
      active: boolean;
      group_role_mappings: Array<{
        group_object_id: string;
        group_name: string;
        app_roles: string[];
      }>;
    };
  }>(null);
  const [draftGuacamole, setDraftGuacamole] = useState<null | {
    display: {
      mode: "dynamic" | "fixed";
      width?: number | null;
      height?: number | null;
      dpi: number;
    };
    recording: {
      enabled: boolean;
      browse_url: string;
      path_template: string;
      name_template: string;
      create_path: boolean;
      exclude_output: boolean;
      exclude_mouse: boolean;
      exclude_touch: boolean;
      include_keys: boolean;
    };
  }>(null);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [identitySaveState, setIdentitySaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [identitySaveError, setIdentitySaveError] = useState<string | null>(null);
  const [guacamoleSaveState, setGuacamoleSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [guacamoleSaveError, setGuacamoleSaveError] = useState<string | null>(null);
  const [killState, setKillState] = useState<"idle" | "killing" | "success" | "error">("idle");
  const [killMessage, setKillMessage] = useState<string | null>(null);
  const [playbackEntry, setPlaybackEntry] = useState<GuacamoleRecordingEntry | null>(null);

  const deploymentSettings = draftDeployment ?? serverSettings?.deployment ?? {
    default_repo_url: "",
    artifact_share_root: "",
    latest_installer_share_template: "",
  };
  const identitySettings = draftIdentity ?? {
    provider: serverSettings?.identity.provider ?? "local_bootstrap",
    provider_locked: serverSettings?.identity.provider_locked ?? false,
    local_bootstrap_available: serverSettings?.identity.local_bootstrap_available ?? false,
    session_ttl_seconds: serverSettings?.identity.session_ttl_seconds ?? 43200,
    azure: {
      tenant_id: serverSettings?.identity.azure.tenant_id ?? "",
      client_id: serverSettings?.identity.azure.client_id ?? "",
      authority_url: serverSettings?.identity.azure.authority_url ?? "",
      redirect_path: serverSettings?.identity.azure.redirect_path ?? "/api/users/callback/microsoft",
      scopes: serverSettings?.identity.azure.scopes ?? ["openid", "profile", "email"],
      client_secret: "",
      client_secret_configured: serverSettings?.identity.azure.client_secret_configured ?? false,
      activated_at: serverSettings?.identity.azure.activated_at ?? null,
      active: serverSettings?.identity.azure.active ?? false,
      group_role_mappings: serverSettings?.identity.azure.group_role_mappings ?? [],
    },
  };
  const guacamoleSettings = draftGuacamole ?? {
    display: {
      mode: serverSettings?.guacamole.display.mode ?? "dynamic",
      width: serverSettings?.guacamole.display.width ?? 1600,
      height: serverSettings?.guacamole.display.height ?? 900,
      dpi: serverSettings?.guacamole.display.dpi ?? 96,
    },
    recording: {
      enabled: serverSettings?.guacamole.recording.enabled ?? false,
      browse_url: serverSettings?.guacamole.recording.browse_url ?? "",
      path_template: serverSettings?.guacamole.recording.path_template ?? "/recordings/{agent_id}/{username}",
      name_template: serverSettings?.guacamole.recording.name_template ?? "{connection_name}-{timestamp}.guac",
      create_path: serverSettings?.guacamole.recording.create_path ?? true,
      exclude_output: serverSettings?.guacamole.recording.exclude_output ?? false,
      exclude_mouse: serverSettings?.guacamole.recording.exclude_mouse ?? false,
      exclude_touch: serverSettings?.guacamole.recording.exclude_touch ?? false,
      include_keys: serverSettings?.guacamole.recording.include_keys ?? true,
    },
  };

  const providerLocked = identitySettings.provider_locked;
  const azureActive = identitySettings.azure.active;

  const trackedCount = trackedSessions?.tracked_count ?? 0;
  const connectionCount = guacamoleConnections?.connection_count ?? 0;
  const recordingCount = recordings?.entry_count ?? 0;

  const refreshGuacamoleOperations = async () => {
    await Promise.all([refreshGuacamoleConnections(), refreshTrackedSessions(), refreshRecordings()]);
  };

  return (
    <>
      <div className="min-h-full">
      <div className="mb-6 flex items-end justify-between gap-6">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-cyan-300">Server Settings</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-100">Control Plane Configuration</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-500">
            Structured settings workspace for server defaults, transport behavior, and Guacamole operations. This layout is ready for more backend domains without another full redesign.
          </p>
        </div>

        <div className="grid min-w-[16rem] gap-2 rounded-2xl border border-slate-800 bg-slate-900/72 px-4 py-3 text-xs text-slate-400">
          <div className="flex items-center justify-between gap-3">
            <span>Guacamole bridge</span>
            <span className="font-mono text-slate-200">{guacamoleConfigLoading ? "loading" : guacamoleConfig?.enabled ? "enabled" : "disabled"}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span>Tracked sessions</span>
            <span className="font-mono text-slate-200">{trackedSessionsLoading ? "loading" : trackedCount}</span>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className="space-y-4 rounded-[28px] border border-slate-800 bg-[radial-gradient(circle_at_top,#12324b_0%,rgba(15,23,42,0.95)_32%,rgba(2,6,23,0.98)_100%)] p-4 shadow-[0_22px_80px_rgba(2,6,23,0.45)]">
          <div className="border-b border-slate-800 px-2 pb-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-500">Sections</p>
            <p className="mt-2 text-sm text-slate-300">Operator-style submenu for current and future backend settings.</p>
          </div>

          <div className="space-y-3">
            <SettingsNavItem
              active={activeSection === "general"}
              title="General"
              description="Deployment defaults, transport assumptions, and shared server metadata."
              badge="Core"
              onClick={() => setActiveSection("general")}
            />
            <SettingsNavItem
              active={activeSection === "identity"}
              title="Identity"
              description="Local bootstrap admin, Azure Entra SSO, and automatic group to app role mapping."
              badge={azureActive ? "sso active" : providerLocked ? "locked" : "setup"}
              onClick={() => setActiveSection("identity")}
            />
            <SettingsNavItem
              active={activeSection === "guacamole"}
              title="Guacamole"
              description="Bridge inventory, tracked sessions, operator controls, and diagnostics."
              badge={trackedCount > 0 ? `${trackedCount} live` : undefined}
              onClick={() => setActiveSection("guacamole")}
            />
          </div>
        </aside>

        <div className="space-y-6">
          {activeSection === "general" && (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <MetricCard
                  label="Settings Mode"
                  value={settingsLoading ? "Loading" : "Editable"}
                  accent="cyan"
                  detail="Current server defaults are writable through the backend settings API."
                />
                <MetricCard
                  label="Artifact Share"
                  value={deploymentSettings.artifact_share_root ? "Configured" : "Unset"}
                  accent={deploymentSettings.artifact_share_root ? "emerald" : "amber"}
                  detail={deploymentSettings.artifact_share_root || "No shared artifact root configured yet."}
                />
              </div>

              <SectionCard
                title="Server Defaults"
                subtitle="Persisted deployment defaults used by the server and the prepare deployment dialog."
                aside={<span className="font-mono text-xs text-slate-500">{settingsLoading ? "loading" : "editable"}</span>}
              >
                <div className="grid gap-4 xl:grid-cols-2">
                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Default Repo URL</span>
                    <input
                      value={deploymentSettings.default_repo_url}
                      onChange={(event) => setDraftDeployment((current) => ({
                        ...(current ?? deploymentSettings),
                        default_repo_url: event.target.value,
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="https://github.com/example/repo.git"
                    />
                  </label>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Artifact Share Root</span>
                    <input
                      value={deploymentSettings.artifact_share_root}
                      onChange={(event) => setDraftDeployment((current) => ({
                        ...(current ?? deploymentSettings),
                        artifact_share_root: event.target.value,
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="\\\\HOST\\share\\artifacts\\deployments"
                    />
                  </label>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Latest Installer Share Template</span>
                    <input
                      value={deploymentSettings.latest_installer_share_template}
                      onChange={(event) => setDraftDeployment((current) => ({
                        ...(current ?? deploymentSettings),
                        latest_installer_share_template: event.target.value,
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="\\\\HOST\\share\\latest\\install-{deployment_id}.ps1"
                    />
                  </label>
                </div>

                <div className="mt-5 flex flex-wrap items-center gap-3">
                  <button
                    onClick={async () => {
                      setSaveState("saving");
                      setSaveError(null);
                      try {
                        await updateServerSettings({
                          deployment: {
                            default_repo_url: deploymentSettings.default_repo_url,
                            artifact_share_root: deploymentSettings.artifact_share_root,
                            latest_installer_share_template: deploymentSettings.latest_installer_share_template,
                          },
                        });
                        await refreshServerSettings();
                        setDraftDeployment(null);
                        setSaveState("saved");
                      } catch (error) {
                        setSaveState("error");
                        setSaveError(error instanceof Error ? error.message : "Failed to save settings");
                      }
                    }}
                    disabled={settingsLoading || saveState === "saving"}
                    className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                  >
                    {saveState === "saving" ? "Saving..." : "Save Server Defaults"}
                  </button>
                  {saveState === "saved" && <span className="text-xs text-emerald-300">Saved</span>}
                  {saveError && <span className="text-xs text-rose-300">{saveError}</span>}
                </div>
              </SectionCard>

              <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
                <SectionCard title="Transport" subtitle="Static assumptions currently baked into the control plane frontend.">
                  <div className="divide-y divide-slate-800">
                    <DetailRow label="WebSocket URL" value={describeFrontendWebSocketUrl()} />
                    <DetailRow label="Heartbeat interval" value="1s (sync every 10s)" />
                    <DetailRow label="Workspace model" value="Single global Guacamole workspace per user" />
                  </div>
                </SectionCard>

                <SectionCard title="About" subtitle="Current dashboard build metadata.">
                  <div className="divide-y divide-slate-800">
                    <DetailRow label="Version" value="0.1.0" />
                    <DetailRow label="Protocol" value="WebSocket + JSON" />
                    <DetailRow label="Settings structure" value="Generalized layout ready for more backend domains" />
                  </div>
                </SectionCard>
              </div>
            </>
          )}

          {activeSection === "identity" && (
            <>
              <div className="grid gap-4 lg:grid-cols-4">
                <MetricCard
                  label="Provider"
                  value={identitySettings.provider === "azure_entra" ? "Azure Entra" : "Local Bootstrap"}
                  accent={azureActive ? "emerald" : "cyan"}
                  detail={providerLocked ? "Provider locked after SSO activation" : "Provider can still be activated from local bootstrap mode"}
                />
                <MetricCard
                  label="Local Admin"
                  value={identitySettings.local_bootstrap_available ? "Available" : "Disabled"}
                  accent={identitySettings.local_bootstrap_available ? "amber" : "slate"}
                  detail="Bootstrap credentials are read from ENV only and never persisted into server settings."
                />
                <MetricCard
                  label="Role Mappings"
                  value={String(identitySettings.azure.group_role_mappings.length)}
                  detail="Each Azure group object ID resolves to one effective app role on sign-in."
                />
                <MetricCard
                  label="Session TTL"
                  value={formatDuration(identitySettings.session_ttl_seconds)}
                  detail="User session lifetime for dashboard bearer tokens."
                />
              </div>

              <SectionCard
                title="Identity Model"
                subtitle="Configure Microsoft Entra and map Azure groups into application roles."
                aside={<span className="font-mono text-xs text-slate-500">{providerLocked ? "provider locked" : "editable"}</span>}
              >
                <div className="grid gap-4 xl:grid-cols-2">
                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Session TTL Seconds</span>
                    <input
                      type="number"
                      min={900}
                      max={604800}
                      value={identitySettings.session_ttl_seconds}
                      onChange={(event) => setDraftIdentity((current) => ({
                        ...(current ?? identitySettings),
                        session_ttl_seconds: Number(event.target.value || 43200),
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                    />
                  </label>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Authority URL</span>
                    <input
                      value={identitySettings.azure.authority_url}
                      onChange={(event) => setDraftIdentity((current) => ({
                        ...(current ?? identitySettings),
                        azure: {
                          ...(current?.azure ?? identitySettings.azure),
                          authority_url: event.target.value,
                        },
                      }))}
                      disabled={providerLocked}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500 disabled:opacity-60"
                      placeholder="https://login.microsoftonline.com/<tenant>/v2.0"
                    />
                  </label>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Tenant ID</span>
                    <input
                      value={identitySettings.azure.tenant_id}
                      onChange={(event) => setDraftIdentity((current) => ({
                        ...(current ?? identitySettings),
                        azure: {
                          ...(current?.azure ?? identitySettings.azure),
                          tenant_id: event.target.value,
                        },
                      }))}
                      disabled={providerLocked}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500 disabled:opacity-60"
                    />
                  </label>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Client ID</span>
                    <input
                      value={identitySettings.azure.client_id}
                      onChange={(event) => setDraftIdentity((current) => ({
                        ...(current ?? identitySettings),
                        azure: {
                          ...(current?.azure ?? identitySettings.azure),
                          client_id: event.target.value,
                        },
                      }))}
                      disabled={providerLocked}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500 disabled:opacity-60"
                    />
                  </label>

                  <div className="block text-sm">
                    <span className="mb-1 block text-slate-300">Redirect Callback</span>
                    <div className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-300">
                      {identitySettings.azure.redirect_path}
                    </div>
                    <span className="mt-1 block text-xs text-slate-500">
                      Fixed application callback. Register exactly this path in Entra for the public base URL of this server. It is no longer operator-editable.
                    </span>
                  </div>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Client Secret</span>
                    <input
                      type="password"
                      value={identitySettings.azure.client_secret}
                      onChange={(event) => setDraftIdentity((current) => ({
                        ...(current ?? identitySettings),
                        azure: {
                          ...(current?.azure ?? identitySettings.azure),
                          client_secret: event.target.value,
                        },
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder={identitySettings.azure.client_secret_configured ? "Stored secret configured. Enter new value to rotate." : "Optional for confidential client"}
                    />
                  </label>
                </div>

                <label className="mt-4 block text-sm">
                  <span className="mb-1 block text-slate-300">Scopes</span>
                  <input
                    value={identitySettings.azure.scopes.join(", ")}
                    onChange={(event) => setDraftIdentity((current) => ({
                      ...(current ?? identitySettings),
                      azure: {
                        ...(current?.azure ?? identitySettings.azure),
                        scopes: event.target.value.split(",").map((scope) => scope.trim()).filter(Boolean),
                      },
                    }))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                    placeholder="openid, profile, email"
                  />
                </label>

                <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-100">Azure Group Role Mapping</p>
                      <p className="mt-1 text-xs text-slate-500">Prefer group object IDs. Display names are stored only as operator labels.</p>
                    </div>
                    <button
                      onClick={() => setDraftIdentity((current) => ({
                        ...(current ?? identitySettings),
                        azure: {
                          ...(current?.azure ?? identitySettings.azure),
                          group_role_mappings: [
                            ...((current?.azure ?? identitySettings.azure).group_role_mappings || []),
                            { group_object_id: "", group_name: "", app_roles: ["viewer"] },
                          ],
                        },
                      }))}
                      className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-200 hover:border-slate-600"
                    >
                      Add Mapping
                    </button>
                  </div>

                  <div className="mt-4 space-y-3">
                    {identitySettings.azure.group_role_mappings.length === 0 && (
                      <div className="rounded-xl border border-dashed border-slate-800 px-4 py-5 text-sm text-slate-500">
                        No mappings yet. Without mappings users fall back to the `viewer` role.
                      </div>
                    )}
                    {identitySettings.azure.group_role_mappings.map((mapping, index) => (
                      <div key={`${mapping.group_object_id}:${index}`} className="grid gap-3 rounded-xl border border-slate-800 bg-slate-950/70 p-4 xl:grid-cols-[1.1fr_1fr_1fr_auto]">
                        <input
                          value={mapping.group_object_id}
                          onChange={(event) => setDraftIdentity((current) => ({
                            ...(current ?? identitySettings),
                            azure: {
                              ...(current?.azure ?? identitySettings.azure),
                              group_role_mappings: (current?.azure ?? identitySettings.azure).group_role_mappings.map((entry, entryIndex) => entryIndex === index ? { ...entry, group_object_id: event.target.value } : entry),
                            },
                          }))}
                          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500"
                          placeholder="Azure group object ID"
                        />
                        <input
                          value={mapping.group_name}
                          onChange={(event) => setDraftIdentity((current) => ({
                            ...(current ?? identitySettings),
                            azure: {
                              ...(current?.azure ?? identitySettings.azure),
                              group_role_mappings: (current?.azure ?? identitySettings.azure).group_role_mappings.map((entry, entryIndex) => entryIndex === index ? { ...entry, group_name: event.target.value } : entry),
                            },
                          }))}
                          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500"
                          placeholder="Operator label / Azure group name"
                        />
                        <select
                          value={getHighestRole(mapping.app_roles)}
                          onChange={(event) => setDraftIdentity((current) => ({
                            ...(current ?? identitySettings),
                            azure: {
                              ...(current?.azure ?? identitySettings.azure),
                              group_role_mappings: (current?.azure ?? identitySettings.azure).group_role_mappings.map((entry, entryIndex) => entryIndex === index ? { ...entry, app_roles: [event.target.value as AppRole] } : entry),
                            },
                          }))}
                          className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-500"
                        >
                          {APP_ROLE_OPTIONS.map((role) => (
                            <option key={role} value={role}>
                              {formatRoleLabel(role)}
                            </option>
                          ))}
                        </select>
                        <div className="text-xs text-slate-500 xl:col-start-3">
                          Effective role granted to members of this Azure group.
                        </div>
                        <button
                          onClick={() => setDraftIdentity((current) => ({
                            ...(current ?? identitySettings),
                            azure: {
                              ...(current?.azure ?? identitySettings.azure),
                              group_role_mappings: (current?.azure ?? identitySettings.azure).group_role_mappings.filter((_, entryIndex) => entryIndex !== index),
                            },
                          }))}
                          className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-200 hover:border-rose-400"
                        >
                          Remove
                        </button>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="mt-6 flex flex-wrap items-center gap-3">
                  <button
                    onClick={async () => {
                      setIdentitySaveState("saving");
                      setIdentitySaveError(null);
                      try {
                        await updateServerSettings({
                          identity: {
                            session_ttl_seconds: identitySettings.session_ttl_seconds,
                            azure: {
                              tenant_id: identitySettings.azure.tenant_id,
                              client_id: identitySettings.azure.client_id,
                              authority_url: identitySettings.azure.authority_url,
                              scopes: identitySettings.azure.scopes,
                              ...(identitySettings.azure.client_secret ? { client_secret: identitySettings.azure.client_secret } : {}),
                              group_role_mappings: identitySettings.azure.group_role_mappings,
                            },
                          },
                        });
                        await refreshServerSettings();
                        setDraftIdentity(null);
                        setIdentitySaveState("saved");
                      } catch (error) {
                        setIdentitySaveState("error");
                        setIdentitySaveError(error instanceof Error ? error.message : "Failed to save identity settings");
                      }
                    }}
                    disabled={settingsLoading || identitySaveState === "saving"}
                    className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                  >
                    {identitySaveState === "saving" ? "Saving..." : "Save Identity Settings"}
                  </button>
                  <button
                    onClick={async () => {
                      const confirmed = typeof window === "undefined"
                        ? true
                        : window.confirm("Activate Azure Entra SSO and permanently lock the provider?");
                      if (!confirmed) {
                        return;
                      }

                      setIdentitySaveState("saving");
                      setIdentitySaveError(null);
                      try {
                        await updateServerSettings({
                          identity: {
                            session_ttl_seconds: identitySettings.session_ttl_seconds,
                            azure: {
                              tenant_id: identitySettings.azure.tenant_id,
                              client_id: identitySettings.azure.client_id,
                              authority_url: identitySettings.azure.authority_url,
                              scopes: identitySettings.azure.scopes,
                              ...(identitySettings.azure.client_secret ? { client_secret: identitySettings.azure.client_secret } : {}),
                              group_role_mappings: identitySettings.azure.group_role_mappings,
                              activate: true,
                            },
                          },
                        });
                        await refreshServerSettings();
                        setDraftIdentity(null);
                        setIdentitySaveState("saved");
                      } catch (error) {
                        setIdentitySaveState("error");
                        setIdentitySaveError(error instanceof Error ? error.message : "Failed to activate Azure SSO");
                      }
                    }}
                    disabled={settingsLoading || identitySaveState === "saving" || azureActive}
                    className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-sm font-medium text-emerald-200 transition-colors hover:border-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {azureActive ? "Azure SSO Active" : "Activate Azure SSO"}
                  </button>
                  {identitySaveState === "saved" && <span className="text-xs text-emerald-300">Identity settings saved</span>}
                  {identitySaveError && <span className="text-xs text-rose-300">{identitySaveError}</span>}
                </div>
              </SectionCard>

              <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
                <SectionCard title="Lifecycle" subtitle="How bootstrap and SSO activation behave at runtime.">
                  <div className="divide-y divide-slate-800">
                    <DetailRow label="Local bootstrap" value={identitySettings.local_bootstrap_available ? "enabled from ENV" : "disabled"} />
                    <DetailRow label="Provider locked" value={providerLocked ? "yes" : "no"} />
                    <DetailRow label="Azure active" value={azureActive ? "yes" : "no"} />
                    <DetailRow label="Activated at" value={formatDateTime(identitySettings.azure.activated_at)} />
                    <DetailRow label="Stored secret" value={identitySettings.azure.client_secret_configured ? "configured" : "not stored"} />
                  </div>
                </SectionCard>

                <SectionCard title="Integration Notes" subtitle="Current model for Azure app onboarding and role assignment.">
                  <div className="space-y-3 rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-400">
                    <p>1. Skonfiguruj tenant i client ID, a callback zarejestruj w Entra jako stały endpoint aplikacji.</p>
                    <p>2. Dodaj mapowania grup Azure do ról appki, najlepiej po `group_object_id`.</p>
                    <p>3. Aktywacja SSO blokuje providera i wyłącza lokalny bootstrap admin.</p>
                    <p>4. Po rejestracji aplikacji w Entra użytkownicy będą dostawali role automatycznie na podstawie claimu `groups` i ewentualnie `roles`.</p>
                  </div>
                </SectionCard>
              </div>
            </>
          )}

          {activeSection === "guacamole" && (
            <>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard
                  label="Bridge Status"
                  value={guacamoleConfigLoading ? "Loading" : guacamoleConfig?.enabled ? "Enabled" : "Disabled"}
                  accent={guacamoleConfig?.enabled ? "emerald" : "amber"}
                  detail={guacamoleConfig?.configured ? "Configuration loaded" : "Configuration incomplete"}
                />
                <MetricCard
                  label="Tracked Sessions"
                  value={trackedSessionsLoading ? "..." : String(trackedCount)}
                  accent={trackedCount > 0 ? "cyan" : "slate"}
                  detail={trackedSessions?.idle_timeout_seconds != null ? `Idle timeout ${formatDuration(trackedSessions.idle_timeout_seconds)}` : undefined}
                />
                <MetricCard
                  label="Guacamole Connections"
                  value={connectionsLoading ? "..." : String(connectionCount)}
                  detail={guacamoleConnections?.default_data_source || "No default data source reported"}
                />
                <MetricCard
                  label="Static Mappings"
                  value={String(guacamoleConfig?.mapping_count ?? 0)}
                  detail={guacamoleConfig?.default_connection_mode || "No mapping strategy configured"}
                />
                <MetricCard
                  label="Recording"
                  value={guacamoleConfig?.recording?.enabled ? "Enabled" : "Disabled"}
                  accent={guacamoleConfig?.recording?.enabled ? (guacamoleConfig?.recording?.configured ? "emerald" : "amber") : "slate"}
                  detail={guacamoleConfig?.recording?.configured ? (guacamoleConfig?.recording?.path_template || "Path configured") : "Filesystem path missing or feature disabled"}
                />
                <MetricCard
                  label="Recording Files"
                  value={recordingsLoading ? "..." : String(recordingCount)}
                  accent={recordingCount > 0 ? "cyan" : "slate"}
                  detail={recordings?.browse_url || "No recording browse URL configured"}
                />
              </div>

              <SectionCard
                title="Guacamole Profile"
                subtitle="These fields define the global display and recording profile used for Guacamole sessions."
                aside={<span className="font-mono text-xs text-slate-500">{settingsLoading ? "loading" : "editable"}</span>}
              >
                <div className="grid gap-4 xl:grid-cols-4">
                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Display Mode</span>
                    <select
                      value={guacamoleSettings.display.mode}
                      onChange={(event) => setDraftGuacamole((current) => ({
                        ...(current ?? guacamoleSettings),
                        display: {
                          ...(current?.display ?? guacamoleSettings.display),
                          mode: event.target.value as "dynamic" | "fixed",
                        },
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                    >
                      <option value="dynamic">dynamic</option>
                      <option value="fixed">fixed</option>
                    </select>
                  </label>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Width</span>
                    <input
                      type="number"
                      min={1}
                      value={guacamoleSettings.display.width ?? ""}
                      onChange={(event) => setDraftGuacamole((current) => ({
                        ...(current ?? guacamoleSettings),
                        display: {
                          ...(current?.display ?? guacamoleSettings.display),
                          width: event.target.value ? Number(event.target.value) : null,
                        },
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="1600"
                    />
                  </label>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">Height</span>
                    <input
                      type="number"
                      min={1}
                      value={guacamoleSettings.display.height ?? ""}
                      onChange={(event) => setDraftGuacamole((current) => ({
                        ...(current ?? guacamoleSettings),
                        display: {
                          ...(current?.display ?? guacamoleSettings.display),
                          height: event.target.value ? Number(event.target.value) : null,
                        },
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="900"
                    />
                  </label>

                  <label className="block text-sm">
                    <span className="mb-1 block text-slate-300">DPI</span>
                    <input
                      type="number"
                      min={1}
                      value={guacamoleSettings.display.dpi}
                      onChange={(event) => setDraftGuacamole((current) => ({
                        ...(current ?? guacamoleSettings),
                        display: {
                          ...(current?.display ?? guacamoleSettings.display),
                          dpi: event.target.value ? Number(event.target.value) : 96,
                        },
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="96"
                    />
                  </label>
                </div>

                <div className="mt-2 text-xs text-slate-500">
                  Global display profile for new Guacamole sessions. `fixed` uses the resolution above; `dynamic` lets the viewport negotiate size.
                </div>

                <div className="grid gap-4 xl:grid-cols-2">
                  <label className="block text-sm xl:col-span-2">
                    <span className="mb-1 block text-slate-300">Recording Browse URL</span>
                    <input
                      value={guacamoleSettings.recording.browse_url}
                      onChange={(event) => setDraftGuacamole((current) => ({
                        ...(current ?? guacamoleSettings),
                        recording: {
                          ...(current?.recording ?? guacamoleSettings.recording),
                          browse_url: event.target.value,
                        },
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="https://guac.example.internal/recordings"
                    />
                    <span className="mt-1 block text-xs text-slate-500">To powinien być URL do nginx z włączonym `autoindex_format json` dla katalogu recordings. Backend użyje go do listowania i proxowania pobrań.</span>
                  </label>

                  <label className="block text-sm xl:col-span-2">
                    <span className="mb-1 block text-slate-300">Recording Path</span>
                    <input
                      value={guacamoleSettings.recording.path_template}
                      onChange={(event) => setDraftGuacamole((current) => ({
                        ...(current ?? guacamoleSettings),
                        recording: {
                          ...(current?.recording ?? guacamoleSettings.recording),
                          path_template: event.target.value,
                        },
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="/recordings/{agent_id}/{username}"
                    />
                    <span className="mt-1 block text-xs text-slate-500">Ścieżka musi istnieć po stronie Linux/guacd. Jeśli chcesz to serwować przez nginx, wystaw ten sam katalog read-only.</span>
                  </label>

                  <label className="block text-sm xl:col-span-2">
                    <span className="mb-1 block text-slate-300">Recording Name</span>
                    <input
                      value={guacamoleSettings.recording.name_template}
                      onChange={(event) => setDraftGuacamole((current) => ({
                        ...(current ?? guacamoleSettings),
                        recording: {
                          ...(current?.recording ?? guacamoleSettings.recording),
                          name_template: event.target.value,
                        },
                      }))}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="{connection_name}-{timestamp}.guac"
                    />
                  </label>
                </div>

                <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {[
                    ["Enable recording", "enabled"],
                    ["Automatically create path", "create_path"],
                    ["Exclude graphics/streams", "exclude_output"],
                    ["Exclude mouse", "exclude_mouse"],
                    ["Exclude touch events", "exclude_touch"],
                    ["Include key events", "include_keys"],
                  ].map(([label, key]) => (
                    <label key={key} className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-sm text-slate-300">
                      <span>{label}</span>
                      <input
                        type="checkbox"
                        checked={Boolean(guacamoleSettings.recording[key as keyof typeof guacamoleSettings.recording])}
                        onChange={(event) => setDraftGuacamole((current) => ({
                          ...(current ?? guacamoleSettings),
                          recording: {
                            ...(current?.recording ?? guacamoleSettings.recording),
                            [key]: event.target.checked,
                          },
                        }))}
                        className="h-4 w-4 rounded border-slate-600 bg-slate-900 text-cyan-400 focus:ring-cyan-500"
                      />
                    </label>
                  ))}
                </div>

                <div className="mt-5 flex flex-wrap items-center gap-3">
                  <button
                    onClick={async () => {
                      setGuacamoleSaveState("saving");
                      setGuacamoleSaveError(null);
                      try {
                        await updateServerSettings({
                          guacamole: {
                            display: {
                              mode: guacamoleSettings.display.mode,
                              width: guacamoleSettings.display.width,
                              height: guacamoleSettings.display.height,
                              dpi: guacamoleSettings.display.dpi,
                            },
                            recording: {
                              enabled: guacamoleSettings.recording.enabled,
                              browse_url: guacamoleSettings.recording.browse_url,
                              path_template: guacamoleSettings.recording.path_template,
                              name_template: guacamoleSettings.recording.name_template,
                              create_path: guacamoleSettings.recording.create_path,
                              exclude_output: guacamoleSettings.recording.exclude_output,
                              exclude_mouse: guacamoleSettings.recording.exclude_mouse,
                              exclude_touch: guacamoleSettings.recording.exclude_touch,
                              include_keys: guacamoleSettings.recording.include_keys,
                            },
                          },
                        });
                        await Promise.all([refreshServerSettings(), refreshGuacamoleOperations()]);
                        setDraftGuacamole(null);
                        setGuacamoleSaveState("saved");
                      } catch (error) {
                        setGuacamoleSaveState("error");
                        setGuacamoleSaveError(error instanceof Error ? error.message : "Failed to save Guacamole settings");
                      }
                    }}
                    disabled={settingsLoading || guacamoleSaveState === "saving"}
                    className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                  >
                    {guacamoleSaveState === "saving" ? "Saving..." : "Save Guacamole Settings"}
                  </button>
                  {guacamoleSaveState === "saved" && <span className="text-xs text-emerald-300">Guacamole settings saved</span>}
                  {guacamoleSaveError && <span className="text-xs text-rose-300">{guacamoleSaveError}</span>}
                </div>
              </SectionCard>

              <SectionCard
                title="Operations"
                subtitle="Manual refresh and operator intervention for tracked Guacamole sessions."
                aside={
                  <div className="flex items-center gap-3">
                    <button
                      onClick={() => void refreshGuacamoleOperations()}
                      className="rounded-lg border border-slate-600 bg-slate-950/70 px-3 py-2 text-xs font-medium text-slate-300 hover:border-slate-500"
                    >
                      Refresh Inventory
                    </button>
                    <button
                      onClick={async () => {
                        if (!trackedCount) {
                          return;
                        }

                        const confirmed = typeof window === "undefined"
                          ? true
                          : window.confirm(`Kill all ${trackedCount} tracked Guacamole session(s)?`);
                        if (!confirmed) {
                          return;
                        }

                        setKillState("killing");
                        setKillMessage(null);
                        try {
                          const result = await killAllTrackedGuacamoleSessions();
                          setKillState("success");
                          setKillMessage(`Closed ${result.closed_count} tracked session(s).`);
                          await refreshGuacamoleOperations();
                        } catch (error) {
                          setKillState("error");
                          setKillMessage(error instanceof Error ? error.message : "Failed to kill tracked sessions");
                        }
                      }}
                      disabled={killState === "killing" || trackedCount === 0}
                      className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-200 hover:border-rose-400 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {killState === "killing" ? "Killing..." : "Kill All Tracked Sessions"}
                    </button>
                  </div>
                }
              >
                <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
                  <div className="grid gap-4 md:grid-cols-2">
                    <MetricCard
                      label="Current Tracked"
                      value={String(trackedCount)}
                      accent={trackedCount > 0 ? "amber" : "slate"}
                      detail="Sessions held in the backend monitor, including auth token and tunnel tracking."
                    />
                    <MetricCard
                      label="Data Sources"
                      value={guacamoleConnections?.available_data_sources?.length ? String(guacamoleConnections.available_data_sources.length) : "0"}
                      detail={guacamoleConnections?.available_data_sources?.join(", ") || "No sources returned by Guacamole."}
                    />
                  </div>
                  <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4 text-sm text-slate-300">
                    <p className="font-medium text-slate-100">Operator note</p>
                    <p className="mt-2 text-slate-400">
                      Kill All Tracked Sessions invalidates every backend-tracked Guacamole auth token and tears down active websocket and HTTP tunnel bookkeeping. Use it when sessions drift, after operator error, or during recovery.
                    </p>
                    {killMessage && (
                      <p className={`mt-3 text-xs ${killState === "error" ? "text-rose-300" : "text-emerald-300"}`}>
                        {killMessage}
                      </p>
                    )}
                  </div>
                </div>
              </SectionCard>

              <div className="grid gap-6 2xl:grid-cols-[0.95fr_1.05fr]">
                <SectionCard title="Bridge Overview" subtitle="Current backend and upstream Guacamole configuration surface.">
                  <div className="divide-y divide-slate-800">
                    <DetailRow label="Configured" value={guacamoleConfig?.configured ? "yes" : "no"} />
                    <DetailRow label="Base URL" value={guacamoleConfig?.base_url || "-"} />
                    <DetailRow label="API user configured" value={guacamoleConfig?.auth_username_configured ? "yes" : "no"} />
                    <DetailRow label="API password configured" value={guacamoleConfig?.auth_password_configured ? "yes" : "no"} />
                    <DetailRow label="Auth provider" value={guacamoleConfig?.auth_provider || "-"} />
                    <DetailRow label="Default mapping" value={guacamoleConfig?.default_connection_mode || "-"} />
                    <DetailRow label="Connection type" value={guacamoleConfig?.connection_type || "-"} />
                    <DetailRow label="Recording enabled" value={guacamoleConfig?.recording?.enabled ? "yes" : "no"} />
                    <DetailRow label="Recording browse URL" value={guacamoleConfig?.recording?.browse_url || "-"} />
                    <DetailRow label="Recording path" value={guacamoleConfig?.recording?.path_template || "-"} />
                    <DetailRow label="Recording name" value={guacamoleConfig?.recording?.name_template || "-"} />
                    <DetailRow label="WebSocket tunnel" value={guacamoleConfig?.websocket_tunnel_url || "-"} />
                    <DetailRow label="HTTP tunnel" value={guacamoleConfig?.http_tunnel_url || "-"} />
                  </div>

                  {!!guacamoleConfig?.notes?.length && (
                    <div className="mt-5 space-y-2 rounded-xl border border-slate-800 bg-slate-950/55 p-4 text-xs text-slate-400">
                      {guacamoleConfig.notes.map((note) => (
                        <p key={note}>{note}</p>
                      ))}
                    </div>
                  )}

                  {!!guacamoleConnections?.warnings?.length && (
                    <div className="mt-4 space-y-2 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-xs text-amber-100/90">
                      {guacamoleConnections.warnings.map((warning) => (
                        <p key={warning}>{warning}</p>
                      ))}
                    </div>
                  )}
                </SectionCard>

                <SectionCard title="Tracked Sessions" subtitle="Active session inventory maintained by the backend RDP monitor.">
                  <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/70">
                    <table className="min-w-full text-sm">
                      <thead className="bg-slate-900/90 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">Agent</th>
                          <th className="px-3 py-2 text-left font-medium">Owner</th>
                          <th className="px-3 py-2 text-left font-medium">Auth</th>
                          <th className="px-3 py-2 text-left font-medium">Connection</th>
                          <th className="px-3 py-2 text-left font-medium">Source</th>
                          <th className="px-3 py-2 text-right font-medium">Tunnels</th>
                          <th className="px-3 py-2 text-right font-medium">Idle</th>
                          <th className="px-3 py-2 text-left font-medium">Last Activity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {trackedSessions?.sessions?.length ? (
                          trackedSessions.sessions.map((trackedSession) => (
                            <tr key={trackedSession.auth_token} className="border-t border-slate-800 text-slate-300">
                              <td className="px-3 py-2 font-medium text-slate-100">{trackedSession.agent_id || "-"}</td>
                              <td className="px-3 py-2 text-xs text-slate-300">{trackedSession.owner?.display_name || trackedSession.owner?.username || trackedSession.owner?.email || "-"}</td>
                              <td className="px-3 py-2 font-mono text-xs text-slate-400">{maskToken(trackedSession.auth_token)}</td>
                              <td className="px-3 py-2 font-mono text-xs text-slate-300">{trackedSession.connection_id || "-"}</td>
                              <td className="px-3 py-2 font-mono text-xs text-slate-400">{trackedSession.data_source || "-"}</td>
                              <td className="px-3 py-2 text-right font-mono text-xs text-slate-300">{trackedSession.tunnel_count}</td>
                              <td className="px-3 py-2 text-right font-mono text-xs text-slate-300">{formatDuration(trackedSession.idle_seconds)}</td>
                              <td className="px-3 py-2 font-mono text-xs text-slate-500">{formatDateTime(trackedSession.last_activity_at)}</td>
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td colSpan={8} className="px-3 py-6 text-center text-sm text-slate-500">
                              {trackedSessionsLoading ? "Loading tracked sessions..." : "No tracked Guacamole sessions are currently held by the backend."}
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </SectionCard>
              </div>

              <SectionCard
                title="Recording Inventory"
                subtitle="Files discovered through the configured recording browse URL and served back through the backend download proxy."
                aside={
                  <button
                    onClick={() => void refreshRecordings()}
                    className="rounded-lg border border-slate-600 bg-slate-950/70 px-3 py-2 text-xs font-medium text-slate-300 hover:border-slate-500"
                  >
                    Refresh Recordings
                  </button>
                }
              >
                {!!recordings?.warnings?.length && (
                  <div className="mb-4 space-y-2 rounded-xl border border-amber-500/20 bg-amber-500/10 p-4 text-xs text-amber-100/90">
                    {recordings.warnings.map((warning) => (
                      <p key={warning}>{warning}</p>
                    ))}
                  </div>
                )}

                <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/70">
                  <table className="min-w-full text-sm">
                    <thead className="bg-slate-900/90 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Agent</th>
                        <th className="px-3 py-2 text-left font-medium">User</th>
                        <th className="px-3 py-2 text-left font-medium">File</th>
                        <th className="px-3 py-2 text-left font-medium">Modified</th>
                        <th className="px-3 py-2 text-right font-medium">Size</th>
                        <th className="px-3 py-2 text-right font-medium">Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recordings?.entries?.length ? (
                        recordings.entries.map((entry) => (
                          <tr key={entry.relative_path} className="border-t border-slate-800 text-slate-300">
                            <td className="px-3 py-2 font-mono text-xs text-slate-300">{entry.agent_id || "-"}</td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-400">{entry.owner?.display_name || entry.owner?.username || entry.owner?.email || entry.username || "-"}</td>
                            <td className="px-3 py-2">
                              <div className="text-slate-100">{entry.name || "-"}</div>
                              <div className="mt-1 font-mono text-[11px] text-slate-500">{entry.relative_path}</div>
                            </td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-400">{formatDateTime(entry.modified_at ?? null)}</td>
                            <td className="px-3 py-2 text-right font-mono text-xs text-slate-300">{formatBytes(entry.size_bytes ?? null)}</td>
                            <td className="px-3 py-2 text-right">
                              <div className="flex items-center justify-end gap-2">
                                <button
                                  type="button"
                                  onClick={() => setPlaybackEntry(entry)}
                                  className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs font-medium text-slate-200 hover:border-slate-500"
                                >
                                  Play
                                </button>
                                <a
                                  href={withAccessToken(entry.download_url)}
                                  className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-medium text-cyan-100 hover:border-cyan-400"
                                >
                                  Download
                                </a>
                              </div>
                            </td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={6} className="px-3 py-6 text-center text-sm text-slate-500">
                            {recordingsLoading ? "Loading recordings..." : "No recordings were returned by the server."}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </SectionCard>

              <SectionCard title="Guacamole Connections" subtitle="Current connections discovered from the configured Guacamole data sources.">
                <div className="mb-4 grid gap-3 md:grid-cols-3">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Default Data Source</p>
                    <p className="mt-2 font-mono text-sm text-slate-200">{guacamoleConnections?.default_data_source || "-"}</p>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 md:col-span-2">
                    <p className="text-[11px] uppercase tracking-[0.18em] text-slate-500">Available Data Sources</p>
                    <p className="mt-2 font-mono text-sm text-slate-200 break-all">
                      {guacamoleConnections?.available_data_sources?.join(", ") || "-"}
                    </p>
                  </div>
                </div>

                <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-950/70">
                  <table className="min-w-full text-sm">
                    <thead className="bg-slate-900/90 text-[11px] uppercase tracking-[0.18em] text-slate-500">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Name</th>
                        <th className="px-3 py-2 text-left font-medium">Identifier</th>
                        <th className="px-3 py-2 text-left font-medium">Protocol</th>
                        <th className="px-3 py-2 text-left font-medium">Data Source</th>
                        <th className="px-3 py-2 text-left font-medium">Parent</th>
                        <th className="px-3 py-2 text-right font-medium">Active</th>
                      </tr>
                    </thead>
                    <tbody>
                      {guacamoleConnections?.connections?.length ? (
                        guacamoleConnections.connections.map((connection) => (
                          <tr key={`${connection.data_source}:${connection.identifier}`} className="border-t border-slate-800 text-slate-300">
                            <td className="px-3 py-2 text-slate-100">{connection.name || "-"}</td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-400">{connection.identifier || "-"}</td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-300">{connection.protocol || "-"}</td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-400">{connection.data_source || "-"}</td>
                            <td className="px-3 py-2 font-mono text-xs text-slate-500">{connection.parent_identifier || "-"}</td>
                            <td className="px-3 py-2 text-right font-mono text-xs text-slate-300">{connection.active_connections ?? 0}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td colSpan={6} className="px-3 py-6 text-center text-sm text-slate-500">
                            {connectionsLoading ? "Loading Guacamole connections..." : "No Guacamole connections were returned by the server."}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </SectionCard>
            </>
          )}
        </div>
      </div>
      </div>
      <GuacamoleRecordingPlayerDialog
        entry={playbackEntry}
        open={Boolean(playbackEntry)}
        onClose={() => setPlaybackEntry(null)}
      />
    </>
  );
}
