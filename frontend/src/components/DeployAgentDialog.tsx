"use client";

import { useEffect, useState } from "react";
import { buildInstallCommand, getDeploymentInstallerUrl, prepareDeployment, useDeployment, useDeploymentConfig } from "@/hooks/useDeploymentAPI";

interface DeployAgentDialogProps {
  open: boolean;
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

export function DeployAgentDialog({ open, initialAgentId, initialHostname, initialDisplayName, onClose }: DeployAgentDialogProps) {
  const [agentId, setAgentId] = useState(initialAgentId || "");
  const [hostname, setHostname] = useState(initialHostname || "");
  const [displayName, setDisplayName] = useState(initialDisplayName || "");
  const [repoUrl, setRepoUrl] = useState("");
  const [sourceRef, setSourceRef] = useState("main");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deploymentId, setDeploymentId] = useState<string | null>(null);
  const [defaultsApplied, setDefaultsApplied] = useState(false);
  const [copyState, setCopyState] = useState<string | null>(null);

  const { data: config } = useDeploymentConfig();
  const { data: deployment, taskLog } = useDeployment(deploymentId ?? config?.active_deployment?.id ?? null);

  useEffect(() => {
    if (!open) {
      setDefaultsApplied(false);
      return;
    }
    setAgentId(initialAgentId || initialHostname || "");
    setHostname(initialHostname || "");
    setDisplayName(initialDisplayName || initialHostname || "");
    setError(null);
    setDeploymentId(config?.active_deployment?.id ?? null);
  }, [open, initialAgentId, initialDisplayName, initialHostname, config?.active_deployment?.id]);

  useEffect(() => {
    if (!open || defaultsApplied || !config) {
      return;
    }
    setRepoUrl(config.default_repo_url || "");
    setSourceRef(config.default_source_ref || "main");
    setDefaultsApplied(true);
  }, [open, defaultsApplied, config]);

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/70 p-4 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl shadow-black/40">
        <div className="flex items-center justify-between border-b border-slate-700 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Prepare Agent Deployment</h2>
            <p className="text-sm text-slate-500">Server builds the package from the selected ref. Installation stays manual on the target machine.</p>
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
              <span className="mb-1 block text-slate-300">Git Ref</span>
              <input
                value={sourceRef}
                onChange={(event) => setSourceRef(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="main"
              />
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Repo URL</span>
              <input
                value={repoUrl}
                onChange={(event) => setRepoUrl(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                placeholder="https://github.com/kubiax94/python-rpa-platform.git"
              />
            </label>

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
                    repo_url: repoUrl,
                    source_ref: sourceRef,
                  });
                  setDeploymentId(result.id);
                } catch (submitError) {
                  setError(submitError instanceof Error ? submitError.message : "Deployment request failed");
                } finally {
                  setSubmitting(false);
                }
              }}
              disabled={submitting || !hostname.trim() || (!!config?.active_deployment && config.active_deployment.id !== deploymentId)}
              className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {submitting ? "Preparing..." : "Prepare Deployment"}
            </button>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-950/60 p-4">
            <h3 className="text-sm font-semibold text-slate-100">Deployment Status</h3>
            {!deployment && <p className="mt-3 text-sm text-slate-500">Submit the form to start a background build job.</p>}

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
                  <span className="text-slate-400">Repo</span>
                  <span className="font-mono text-slate-200 break-all text-right">{deployment.repo_url || "-"}</span>
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
                    onClick={async () => {
                      await navigator.clipboard.writeText(buildInstallCommand(deployment, config));
                      setCopyState("Install command copied");
                      setTimeout(() => setCopyState(null), 2500);
                    }}
                    className="rounded-lg bg-cyan-500 px-3 py-1.5 text-sm font-medium text-slate-950 transition-colors hover:bg-cyan-400"
                  >
                    Copy install command
                  </button>
                  {copyState && <span className="self-center text-xs text-cyan-300">{copyState}</span>}
                </div>
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