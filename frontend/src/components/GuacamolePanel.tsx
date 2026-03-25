"use client";

import { useGuacamoleSession } from "@/hooks/useGuacamole";

interface GuacamolePanelProps {
  agentId: string;
}

function InfoRow({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono text-slate-200 text-right break-all">{value || "-"}</span>
    </div>
  );
}

export function GuacamolePanel({ agentId }: GuacamolePanelProps) {
  const { data, loading, refresh } = useGuacamoleSession(agentId);

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-slate-700/70 px-4 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-100">Remote Desktop</h2>
            <p className="text-xs text-slate-500 mt-1">Guacamole bridge resolved on the FastAPI side for this agent.</p>
          </div>
          <div className="flex items-center gap-2">
            {data?.launch_url && (
              <a
                href={data.launch_url}
                target="_blank"
                rel="noreferrer"
                className="rounded-md border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-xs font-medium text-blue-300 hover:bg-blue-500/20"
              >
                Open Guacamole
              </a>
            )}
            <button
              onClick={() => refresh()}
              className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
            >
              Refresh
            </button>
          </div>
        </div>

        <div className="grid gap-4 p-4 lg:grid-cols-[360px_minmax(0,1fr)]">
          <div className="space-y-4">
            <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Status</span>
                <span
                  className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                    data?.status === "ready"
                      ? "bg-emerald-500/15 text-emerald-300"
                      : "bg-amber-500/15 text-amber-300"
                  }`}
                >
                  {loading ? "Loading" : data?.status === "ready" ? "Ready" : "Needs config"}
                </span>
              </div>
              <InfoRow label="Connection" value={data?.connection_label} />
              <InfoRow label="Source" value={data?.source} />
              <InfoRow label="Hostname" value={data?.resolved_fields?.hostname} />
              <InfoRow label="Azure VM" value={data?.resolved_fields?.azure_vm_name} />
              <InfoRow label="Public IP" value={data?.resolved_fields?.public_ip} />
              <InfoRow label="Private IP" value={data?.resolved_fields?.private_ip} />
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

            {!data?.launch_url && !loading && (
              <div className="rounded-lg border border-slate-700/80 bg-slate-900/50 p-4 text-sm text-slate-400">
                Set GUACAMOLE_BASE_URL and a launch template on the server, then map this agent to a connection id or name.
              </div>
            )}
          </div>

          <div className="rounded-lg border border-slate-700/80 bg-slate-950/70 min-h-[520px] overflow-hidden">
            {data?.allow_embed && data?.embed_url ? (
              <iframe
                title={`Guacamole ${agentId}`}
                src={data.embed_url}
                className="h-[520px] w-full bg-slate-950"
                referrerPolicy="strict-origin-when-cross-origin"
              />
            ) : (
              <div className="flex h-[520px] items-center justify-center p-8 text-center text-sm text-slate-500">
                <div>
                  <p className="text-slate-300">Embedded session preview is not available.</p>
                  <p className="mt-2">Use the external launch button or enable embedding in the bridge config.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}