"use client";

import { useEffect, useState } from "react";
import { buildLocalInstallCommand, getDeploymentInstallerUrl, getDeploymentPackageUrl, prepareDeployment, useDeployment, useDeploymentConfig } from "@/hooks/useDeploymentAPI";
import { useDeploymentProvisioning } from "@/hooks/useDeploymentAPI";
import { GuacamoleProvisioningSummary } from "@/components/GuacamoleProvisioningSummary";

interface DeployAgentDialogProps {
  open: boolean;
  canPrepareDeployment?: boolean;
  initialAgentId?: string | null;
  initialHostname?: string | null;
  initialDisplayName?: string | null;
  onClose: () => void;
}

function formatDateTime(ts: number | null | undefined): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("pl-PL");
}

function deploymentStatusClass(status: string): string {
  if (status === "ready") return "bg-emerald-500/15 text-emerald-300";
  if (status === "failed") return "bg-red-500/15 text-red-300";
  if (status === "expired_bootstrap") return "bg-orange-500/15 text-orange-300";
  return "bg-amber-500/15 text-amber-300";
}

export function DeployAgentDialog({ open, canPrepareDeployment = true, initialAgentId, initialHostname, initialDisplayName, onClose }: DeployAgentDialogProps) {
  const [agentId, setAgentId] = useState(initialAgentId || "");
  const [hostname, setHostname] = useState(initialHostname || "");
  const [displayName, setDisplayName] = useState(initialDisplayName || "");
  const [guacamoleTargetHost, setGuacamoleTargetHost] = useState("");
  const [guacamoleUsername, setGuacamoleUsername] = useState("");
  const [guacamoleDomain, setGuacamoleDomain] = useState("");
  const [guacamolePassword, setGuacamolePassword] = useState("");
  const [guacamoleSecret, setGuacamoleSecret] = useState("");
  const [selectedReleaseId, setSelectedReleaseId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [defaultsApplied, setDefaultsApplied] = useState(false);
  const [copyState, setCopyState] = useState<string | null>(null);

  const { data: config } = useDeploymentConfig();
  const { data: deployment, taskLog } = useDeployment(deploymentId ?? config?.active_deployment?.id ?? null);
  const { data: provisioningDiagnostics, loading: provisioningLoading } = useDeploymentProvisioning(
    deploymentId ?? config?.active_deployment?.id ?? null,
  );

  useEffect(() => {
    if (!open) {
      setDefaultsApplied(false);
      return;
    }
    setAgentId(initialAgentId || initialHostname || "");
    setHostname(initialHostname || "");
    setDisplayName(initialDisplayName || initialHostname || "");
    setGuacamoleTargetHost(initialHostname || "");
    setGuacamoleUsername("");
    setGuacamoleDomain("");
    setGuacamolePassword("");
    setGuacamoleSecret("");
    setSelectedReleaseId("");
    setError(null);
    setDeploymentId(config?.active_deployment?.id ?? null);
  }, [open, initialAgentId, initialDisplayName, initialHostname, config?.active_deployment?.id]);

  useEffect(() => {
    if (!open || defaultsApplied || !config) {
      return;
    }
    setSelectedReleaseId(config.latest_release?.id || config.releases[0]?.id || "");
    setDefaultsApplied(true);
  }, [open, defaultsApplied, config]);

  const selectedRelease = config?.releases.find((release) => release.id === selectedReleaseId) ?? config?.latest_release ?? null;

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl shadow-black/40">
        <div className="flex items-center justify-between border-b border-slate-700 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Prepare Agent Deployment</h2>
            <p className="text-sm text-slate-500">Server prepares the package from a published release. Installation stays manual on the target machine.</p>
          </div>
          <button onClick={onClose} className="rounded-md px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200">
            Close
          </button>
        </div>

        <div className="grid gap-6 px-5 py-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="space-y-4">
            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Agent ID</span>
              <input
                value={agentId}
                onChange={(event) => setAgentId(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="agent-win-01"
              />
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Hostname</span>
              <input
                value={hostname}
                onChange={(event) => setHostname(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="DESKTOP-ABC123"
              />
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Display Name</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="Operator desktop"
              />
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Guacamole / RDP Target Host</span>
              <input
                value={guacamoleTargetHost}
                onChange={(event) => setGuacamoleTargetHost(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="192.168.1.50 or vm01.lab.local"
              />
              <span className="mt-1 block text-xs text-slate-500">
                This is the real RDP endpoint used by Guacamole. It can be an IP or DNS name and does not need to match the agent hostname.
              </span>
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Guacamole Username</span>
              <input
                value={guacamoleUsername}
                onChange={(event) => setGuacamoleUsername(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="Optional VM username"
              />
              <span className="mt-1 block text-xs text-slate-500">
                Enter only the account name here. If you need `DOMAIN\\user`, put `user` here and fill the domain field below.
              </span>
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Guacamole Domain</span>
              <input
                value={guacamoleDomain}
                onChange={(event) => setGuacamoleDomain(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="Optional domain, for example DESKTOP-JJULF7D"
              />
              <span className="mt-1 block text-xs text-slate-500">
                This is sent to Guacamole as the RDP `domain` parameter. If left empty, the backend will still split `DOMAIN\\user` automatically when it sees that legacy format.
              </span>
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Guacamole Password</span>
              <input
                type="password"
                autoComplete="new-password"
                value={guacamolePassword}
                onChange={(event) => setGuacamolePassword(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="Optional RDP password"
              />
              <span className="mt-1 block text-xs text-slate-500">
                Used only to render Guacamole connection parameters during provisioning. It is not persisted into agent metadata or deployment files.
              </span>
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Secret Reference</span>
              <input
                value={guacamoleSecret}
                onChange={(event) => setGuacamoleSecret(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="Optional secret ID or Vaultwarden reference"
              />
              <span className="mt-1 block text-xs text-slate-500">
                This is passed through as a template value for Guacamole parameters. It does not integrate Vaultwarden automatically yet, but it gives you a stable reference to wire later.
              </span>
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Agent Release</span>
              <select
                value={selectedReleaseId}
                onChange={(event) => setSelectedReleaseId(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
              >
                <option value="">Latest available release</option>
                {config?.releases.map((release) => (
                  <option key={release.id} value={release.id}>
                    {(release.tag_name || release.version || release.id) + (release.commit_sha ? ` (${release.commit_sha.slice(0, 12)})` : "")}
                  </option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-slate-500">
                The server downloads the published `agent_service.exe` asset for the chosen release and generates the bootstrap package around it.
              </span>
            </label>

            {selectedRelease && (
              <div className="rounded-lg border border-slate-700 bg-slate-950/60 px-3 py-2 text-xs text-slate-400">
                <div>
                  Release: <span className="font-mono text-slate-200">{selectedRelease.tag_name || selectedRelease.version || selectedRelease.id}</span>
                </div>
                <div>
                  Commit: <span className="font-mono text-slate-200">{selectedRelease.commit_sha || "-"}</span>
                </div>
              </div>
            )}

            {config?.active_deployment && (!deploymentId || deploymentId !== config.active_deployment.id) && (
              <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-100">
                Another prepare deployment is already running for {config.active_deployment.hostname}. Wait until it finishes before starting a new one.
              </p>
            )}

            {error && <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">{error}</p>}

            <button
              onClick={async () => {
                setSubmitting(true);
                setError(null);
                try {
                  const result = await prepareDeployment({
                    agent_id: agentId || hostname,
                    hostname,
                    display_name: displayName,
                    guacamole_target_host: guacamoleTargetHost || hostname,
                    guacamole_username: guacamoleUsername,
                    guacamole_domain: guacamoleDomain,
                    guacamole_password: guacamolePassword,
                    guacamole_secret: guacamoleSecret,
                    guacamole_group_name: agentId || hostname,
                    guacamole_connection_name: hostname,
                    release_id: selectedReleaseId || undefined,
                  });
                  setDeploymentId(result.id);
                } catch (submitError) {
                  setError(submitError instanceof Error ? submitError.message : "Deployment request failed");
                } finally {
                  setSubmitting(false);
                }
              }}
              disabled={!canPrepareDeployment || submitting || !hostname.trim() || (!!config?.active_deployment && config.active_deployment.id !== deploymentId)}
              className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {submitting ? "Preparing..." : "Prepare Deployment"}
            </button>
            {!canPrepareDeployment && <p className="text-xs text-slate-500">Preparing deployments requires operator role.</p>}
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-950/60 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Deployment Status</h3>
            {!deployment && <p className="mt-3 text-sm text-slate-500">Submit the form to start a background release packaging job.</p>}

            {deployment && (
              <div className="mt-4 space-y-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-400">Status</span>
                  <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${deploymentStatusClass(deployment.status)}`}>
                    {deployment.status}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-slate-400">Created</span>
                  <span className="font-mono text-slate-200">{formatDateTime(deployment.created_at)}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-slate-400">Release</span>
                  <span className="font-mono text-slate-200 break-all text-right">{deployment.tag_name || deployment.release_id || "-"}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-slate-400">Commit</span>
                  <span className="font-mono text-slate-200 break-all text-right">{deployment.commit_sha || "resolving..."}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-slate-400">Package</span>
                  <span className="font-mono text-slate-200 break-all text-right">{deployment.artifact_dir || "building..."}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-slate-400">Installer</span>
                  <span className="font-mono text-slate-200 break-all text-right">{deployment.install_script_path || "building..."}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-slate-400">Installer copy</span>
                  <span className="font-mono text-slate-200 break-all text-right">{deployment.installer_copy_path || "building..."}</span>
                </div>
                <div className="flex items-start justify-between gap-3">
                  <span className="text-slate-400">Bootstrap</span>
                  <span className="font-mono text-slate-200 break-all text-right">{deployment.bootstrap_path || "building..."}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => window.open(getDeploymentInstallerUrl(deployment.id), "_blank", "noopener,noreferrer")}
                    className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 transition-colors hover:bg-slate-800"
                  >
                    Open installer
                  </button>
                  <button
                    type="button"
                    onClick={() => window.open(getDeploymentPackageUrl(deployment.id), "_blank", "noopener,noreferrer")}
                    className="rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400"
                  >
                    Download ZIP
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      await navigator.clipboard.writeText(buildLocalInstallCommand(deployment));
                      setCopyState("Local install command copied");
                      setTimeout(() => setCopyState(null), 2500);
                    }}
                    className="rounded-lg border border-cyan-500/40 px-3 py-1.5 text-sm font-medium text-cyan-200 transition-colors hover:bg-cyan-500/10"
                  >
                    Copy local command
                  </button>
                  {copyState && <span className="self-center text-xs text-cyan-300">{copyState}</span>}
                </div>
                <div className="rounded-lg border border-slate-700 bg-slate-900/70 p-3 text-xs text-slate-400">
                  Download package.zip, extract it on the target VM, and run install.ps1 with -PackagePath pointing at the extracted package directory.
                </div>
                <GuacamoleProvisioningSummary diagnostics={provisioningDiagnostics} loading={provisioningLoading} />
                {!!taskLog.log && (
                  <details open className="rounded-lg border border-slate-700 bg-slate-900/70 p-3">
                    <summary className="cursor-pointer text-slate-300">Live console output</summary>
                    <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap text-xs text-slate-400">{taskLog.log}</pre>
                  </details>
                )}
                {deployment.error && (
                  <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-red-100">
                    {deployment.error}
                  </div>
                )}
                {deployment.status === "expired_bootstrap" && (
                  <div className="rounded-lg border border-orange-500/30 bg-orange-500/10 p-3 text-orange-100">
                    Bootstrap token expired before first registration. Prepare a new deployment package and reinstall the bootstrap files on the VM.
                  </div>
                )}
                {!!deployment.build_log && (
                  <details className="rounded-lg border border-slate-700 bg-slate-900/70 p-3">
                    <summary className="cursor-pointer text-slate-300">Build log</summary>
                    <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap text-xs text-slate-400">{deployment.build_log}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}