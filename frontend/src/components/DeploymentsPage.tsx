"use client";

import { useState } from "react";
import { buildLocalInstallCommand, getDeploymentInstallerUrl, getDeploymentPackageUrl, useDeployment, useDeploymentProvisioning, useDeployments } from "@/hooks/useDeploymentAPI";
import { GuacamoleProvisioningSummary } from "@/components/GuacamoleProvisioningSummary";

function formatDateTime(ts: number | null | undefined): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("pl-PL");
}

function statusClasses(status: string): string {
  if (status === "ready") return "bg-emerald-500/15 text-emerald-300";
  if (status === "failed") return "bg-red-500/15 text-red-300";
  if (status === "expired_bootstrap") return "bg-orange-500/15 text-orange-300";
  if (status === "building") return "bg-amber-500/15 text-amber-300";
  return "bg-slate-700 text-slate-300";
}

export function DeploymentsPage() {
  const { data: deployments, loading } = useDeployments();
  const [selectedDeploymentId, setSelectedDeploymentId] = useState<string | null>(null);
  const [copiedMessage, setCopiedMessage] = useState<string | null>(null);
  const effectiveSelectedDeploymentId = selectedDeploymentId && deployments.some((item) => item.id === selectedDeploymentId)
    ? selectedDeploymentId
    : deployments[0]?.id ?? null;
  const { data: deployment, taskLog } = useDeployment(effectiveSelectedDeploymentId);
  const { data: provisioningDiagnostics, loading: provisioningLoading } = useDeploymentProvisioning(effectiveSelectedDeploymentId);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Deployments</h1>
          <p className="text-sm text-slate-500">History of prepared deployment artifacts with task logs and installer actions.</p>
        </div>
        {copiedMessage && <span className="text-sm text-cyan-300">{copiedMessage}</span>}
      </div>

      <div className="grid gap-6 xl:grid-cols-[380px_minmax(0,1fr)]">
        <div className="overflow-hidden rounded-2xl border border-slate-700 bg-slate-900">
          <div className="border-b border-slate-700 px-4 py-3 text-sm font-medium text-slate-200">
            Recent deployments
          </div>
          <div className="max-h-[70vh] overflow-y-auto">
            {loading && deployments.length === 0 && (
              <div className="px-4 py-6 text-sm text-slate-500">Loading deployments...</div>
            )}
            {!loading && deployments.length === 0 && (
              <div className="px-4 py-6 text-sm text-slate-500">No deployments yet.</div>
            )}
            {deployments.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setSelectedDeploymentId(item.id)}
                className={`w-full border-b border-slate-800 px-4 py-3 text-left transition-colors hover:bg-slate-800/70 ${effectiveSelectedDeploymentId === item.id ? "bg-slate-800" : "bg-transparent"}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="font-medium text-slate-100">{item.hostname || item.agent_id}</div>
                    <div className="mt-1 font-mono text-xs text-slate-500">{item.id}</div>
                  </div>
                  <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusClasses(item.status)}`}>
                    {item.status}
                  </span>
                </div>
                <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                  <span>{item.source_ref || "main"}</span>
                  <span>{formatDateTime(item.created_at)}</span>
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-700 bg-slate-900 p-5">
          {!deployment && <div className="text-sm text-slate-500">Select a deployment to inspect artifacts, status, and task logs.</div>}

          {deployment && (
            <div className="space-y-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold text-slate-100">{deployment.hostname || deployment.agent_id}</h2>
                  <div className="mt-1 font-mono text-xs text-slate-500">{deployment.id}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${statusClasses(deployment.status)}`}>
                    {deployment.status}
                  </span>
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
                      setCopiedMessage("Local install command copied");
                      setTimeout(() => setCopiedMessage(null), 2500);
                    }}
                    className="rounded-lg border border-cyan-500/40 px-3 py-1.5 text-sm font-medium text-cyan-200 transition-colors hover:bg-cyan-500/10"
                  >
                    Copy local command
                  </button>
                </div>
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm">
                  <div className="text-slate-400">Created</div>
                  <div className="mt-1 font-mono text-slate-200">{formatDateTime(deployment.created_at)}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm">
                  <div className="text-slate-400">Completed</div>
                  <div className="mt-1 font-mono text-slate-200">{formatDateTime(deployment.completed_at)}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm md:col-span-2">
                  <div className="text-slate-400">Repo</div>
                  <div className="mt-1 break-all font-mono text-slate-200">{deployment.repo_url || "-"}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm md:col-span-2">
                  <div className="text-slate-400">Commit</div>
                  <div className="mt-1 break-all font-mono text-slate-200">{deployment.commit_sha || "-"}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm md:col-span-2">
                  <div className="text-slate-400">Package</div>
                  <div className="mt-1 break-all font-mono text-slate-200">{deployment.artifact_dir || "-"}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm md:col-span-2">
                  <div className="text-slate-400">Installer copy</div>
                  <div className="mt-1 break-all font-mono text-slate-200">{deployment.installer_copy_path || deployment.install_script_path || "-"}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm md:col-span-2">
                  <div className="text-slate-400">Local install mode</div>
                  <div className="mt-1 text-slate-300">Download package.zip, extract it on the target VM, and run install.ps1 with -PackagePath pointing at the extracted package directory.</div>
                </div>
              </div>

                <GuacamoleProvisioningSummary diagnostics={provisioningDiagnostics} loading={provisioningLoading} />

              <div className="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
                <div className="mb-2 text-sm font-medium text-slate-200">Task log</div>
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs text-slate-400">{taskLog.log || "No task log available yet."}</pre>
              </div>

              <div className="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
                <div className="mb-2 text-sm font-medium text-slate-200">Build log</div>
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap text-xs text-slate-400">{deployment.build_log || "No build log saved."}</pre>
              </div>

              {deployment.error && (
                <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-100">
                  {deployment.error}
                </div>
              )}

              {deployment.status === "expired_bootstrap" && (
                <div className="rounded-xl border border-orange-500/30 bg-orange-500/10 p-4 text-sm text-orange-100">
                  This deployment package expired before the agent completed first bootstrap. Generate a new deployment and replace bootstrap files on the target VM.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}