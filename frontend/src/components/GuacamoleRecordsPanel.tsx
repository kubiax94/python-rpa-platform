"use client";

import { useState } from "react";
import { GuacamoleRecordingPlayerDialog } from "@/components/GuacamoleRecordingPlayerDialog";
import { type GuacamoleRecordingEntry, useGuacamoleRecordings } from "@/hooks/useGuacamole";
import { withAccessToken } from "@/lib/auth";

function formatDateTime(value?: number | null): string {
  if (!value) {
    return "-";
  }

  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleString();
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

export function GuacamoleRecordsPanel({ agentId, active = false }: { agentId: string; active?: boolean }) {
  const { data, loading, refresh } = useGuacamoleRecordings({ agentId });
  const [playbackEntry, setPlaybackEntry] = useState<GuacamoleRecordingEntry | null>(null);

  if (!active) {
    return null;
  }

  const entries = data?.entries || [];

  const getRecordingUserLabel = (entry: GuacamoleRecordingEntry): string => {
    return entry.owner?.display_name || entry.owner?.username || entry.owner?.email || entry.username || "-";
  };

  return (
    <>
      <div className="space-y-4">
        <div className="rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-slate-700/70 px-4 py-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-100">Records</h2>
              <p className="mt-1 text-xs text-slate-500">
                Browse Guacamole recordings for this agent, open them inside the app, or download the raw .guac file.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${entries.length > 0 ? "bg-cyan-500/15 text-cyan-200" : "bg-slate-700 text-slate-300"}`}>
                {loading ? "Loading" : `${entries.length} recording${entries.length === 1 ? "" : "s"}`}
              </span>
              <button
                onClick={() => void refresh()}
                className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
              >
                Refresh
              </button>
            </div>
          </div>

          <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(18rem,0.6fr)]">
            <div className="rounded-lg border border-slate-700/80 bg-slate-950/80 overflow-hidden">
              <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(7rem,0.6fr)_7rem_8rem] gap-3 border-b border-slate-800 px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                <span>Name</span>
                <span>User</span>
                <span>Modified</span>
                <span className="text-right">Actions</span>
              </div>

              {entries.length > 0 ? (
                <div className="divide-y divide-slate-800">
                  {entries.map((entry) => (
                    <div key={entry.relative_path} className="grid grid-cols-[minmax(0,1.2fr)_minmax(7rem,0.6fr)_7rem_8rem] gap-3 px-4 py-3 text-sm text-slate-300">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-100">{entry.name}</p>
                        <p className="mt-1 truncate text-[11px] text-slate-500">{entry.relative_path}</p>
                      </div>
                      <div className="min-w-0">
                        <p className="truncate">{getRecordingUserLabel(entry)}</p>
                        <p className="mt-1 text-[11px] text-slate-500">{formatBytes(entry.size_bytes)}</p>
                      </div>
                      <div className="text-[11px] text-slate-400">{formatDateTime(entry.modified_at)}</div>
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => setPlaybackEntry(entry)}
                          className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1 text-[11px] font-medium text-cyan-200 hover:border-cyan-400"
                        >
                          Play
                        </button>
                        <a
                          href={withAccessToken(entry.download_url)}
                          className="rounded-md border border-slate-600 bg-slate-900/70 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:border-slate-500"
                        >
                          Download
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="px-4 py-8 text-sm text-slate-400">
                  {loading ? "Loading recordings for this agent..." : "No recordings are currently available for this agent."}
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Recording Notes</p>
                <div className="mt-3 space-y-2 text-sm text-slate-400">
                  <p>Recorded sessions are replayed inside the app using the Guacamole player.</p>
                  <p>Downloads keep the original .guac stream, which is useful for external analysis or archive retention.</p>
                  <p>This panel is filtered to the current agent so operators do not have to leave the agent view to inspect records.</p>
                </div>
              </div>

              <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Inventory</p>
                <div className="mt-3 space-y-2 text-sm text-slate-300">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-slate-500">Agent</span>
                    <span className="font-mono text-xs text-slate-200">{agentId}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-slate-500">Browse status</span>
                    <span>{loading ? "Refreshing" : data?.configured ? "Ready" : "Unavailable"}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-slate-500">Files</span>
                    <span>{entries.length}</span>
                  </div>
                </div>
              </div>
            </div>
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