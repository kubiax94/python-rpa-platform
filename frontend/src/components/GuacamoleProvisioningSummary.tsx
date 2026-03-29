"use client";

import type { DeploymentProvisioningDiagnostics } from "@/hooks/useDeploymentAPI";

interface GuacamoleProvisioningSummaryProps {
  diagnostics: DeploymentProvisioningDiagnostics | null;
  loading?: boolean;
}

function actionClass(action: string): string {
  if (action === "created") return "bg-emerald-500/15 text-emerald-300 border-emerald-500/30";
  if (action === "updated") return "bg-amber-500/15 text-amber-300 border-amber-500/30";
  if (action === "reused") return "bg-cyan-500/15 text-cyan-300 border-cyan-500/30";
  return "bg-slate-800 text-slate-300 border-slate-700";
}

function labelForAction(action: string): string {
  if (action === "created") return "Created";
  if (action === "updated") return "Updated";
  if (action === "reused") return "Reused";
  if (action === "skipped") return "Skipped";
  return action || "Unknown";
}

function EntityCard({
  title,
  entity,
}: {
  title: string;
  entity: { action?: string; identifier?: string; name?: string } | null | undefined;
}) {
  const action = String(entity?.action || "skipped");
  const identifier = String(entity?.identifier || "");
  const name = String(entity?.name || "");

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="text-slate-300">{title}</span>
        <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${actionClass(action)}`}>
          {labelForAction(action)}
        </span>
      </div>
      <div className="mt-3 space-y-2 text-xs">
        <div>
          <div className="text-slate-500">Name</div>
          <div className="mt-1 break-all font-mono text-slate-200">{name || "-"}</div>
        </div>
        <div>
          <div className="text-slate-500">Identifier</div>
          <div className="mt-1 break-all font-mono text-slate-200">{identifier || "-"}</div>
        </div>
      </div>
    </div>
  );
}

export function GuacamoleProvisioningSummary({ diagnostics, loading = false }: GuacamoleProvisioningSummaryProps) {
  return (
    <div className="rounded-xl border border-slate-700 bg-slate-950/70 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium text-slate-200">Guacamole Provisioning</h3>
          <p className="mt-1 text-xs text-slate-500">Server-side result for the agent group and connection prepared during deployment setup.</p>
        </div>
        {loading && <span className="text-xs text-slate-500">Refreshing...</span>}
      </div>

      {!diagnostics && <p className="mt-3 text-sm text-slate-500">Loading provisioning summary...</p>}

      {diagnostics && !diagnostics.available && (
        <p className="mt-3 text-sm text-slate-500">{diagnostics.detail || "No Guacamole provisioning diagnostics recorded for this deployment."}</p>
      )}

      {diagnostics?.available && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap gap-4 text-xs text-slate-400">
            <span>Data source: <span className="font-mono text-slate-300">{diagnostics.data_source || "-"}</span></span>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <EntityCard title="Connection Group" entity={diagnostics.group} />
            <EntityCard title="Connection" entity={diagnostics.connection} />
          </div>
          {diagnostics.detail && <p className="text-xs text-slate-500">{diagnostics.detail}</p>}
        </div>
      )}
    </div>
  );
}