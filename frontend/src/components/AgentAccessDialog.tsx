"use client";

import { useEffect, useState } from "react";
import { API_BASE, fetchJSON, sendJSON } from "@/lib/auth";
import type { AppRole } from "@/lib/rbac";

type AgentRegistryResponse = {
  id: string;
  hostname?: string;
  display_name?: string;
  metadata?: {
    guacamole?: {
      access?: {
        minimum_role?: AppRole;
        interactive_minimum_role?: AppRole;
        file_transfer?: {
          upload_enabled?: boolean;
          download_enabled?: boolean;
        };
      };
    };
  };
};

const ROLE_ORDER: Record<AppRole, number> = {
  viewer: 0,
  operator: 1,
  admin: 2,
};

interface AgentAccessDialogProps {
  agentId: string | null;
  open: boolean;
  onClose: () => void;
  onSaved?: () => Promise<void> | void;
}

export function AgentAccessDialog({ agentId, open, onClose, onSaved }: AgentAccessDialogProps) {
  const [hostname, setHostname] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [minimumRole, setMinimumRole] = useState<AppRole>("operator");
  const [interactiveMinimumRole, setInteractiveMinimumRole] = useState<AppRole>("admin");
  const [uploadEnabled, setUploadEnabled] = useState(true);
  const [downloadEnabled, setDownloadEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !agentId) {
      return;
    }

    setLoading(true);
    setError(null);
    void fetchJSON<AgentRegistryResponse>(`${API_BASE}/api/agent-registry/${encodeURIComponent(agentId)}`)
      .then((item) => {
        const access = item.metadata?.guacamole?.access;
        setHostname(item.hostname || agentId);
        setDisplayName(item.display_name || item.hostname || agentId);
        setMinimumRole(access?.minimum_role || "operator");
        setInteractiveMinimumRole(access?.interactive_minimum_role || "admin");
        setUploadEnabled(access?.file_transfer?.upload_enabled ?? true);
        setDownloadEnabled(access?.file_transfer?.download_enabled ?? true);
      })
      .catch((nextError) => {
        setError(nextError instanceof Error ? nextError.message : String(nextError));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [agentId, open]);

  useEffect(() => {
    if (ROLE_ORDER[interactiveMinimumRole] < ROLE_ORDER[minimumRole]) {
      setInteractiveMinimumRole(minimumRole);
    }
  }, [interactiveMinimumRole, minimumRole]);

  if (!open || !agentId) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/70 p-4 backdrop-blur-sm sm:p-6">
      <div className="my-8 w-full max-w-2xl rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl shadow-black/40">
        <div className="flex items-center justify-between border-b border-slate-700 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Edit Agent Access</h2>
            <p className="text-sm text-slate-500">Configure per-agent remote access thresholds and Guacamole file transfer.</p>
          </div>
          <button onClick={onClose} className="rounded-md px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-slate-200">
            Close
          </button>
        </div>

        <div className="space-y-4 px-5 py-5">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Hostname / FQDN</span>
              <input
                value={hostname}
                onChange={(event) => setHostname(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                disabled={loading || submitting}
              />
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Display name</span>
              <input
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                disabled={loading || submitting}
              />
            </label>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Read-only access threshold</span>
              <select
                value={minimumRole}
                onChange={(event) => setMinimumRole(event.target.value as AppRole)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                disabled={loading || submitting}
              >
                <option value="viewer">Viewer</option>
                <option value="operator">Operator</option>
                <option value="admin">Admin</option>
              </select>
            </label>

            <label className="block text-sm">
              <span className="mb-1 block text-slate-300">Interactive access threshold</span>
              <select
                value={interactiveMinimumRole}
                onChange={(event) => setInteractiveMinimumRole(event.target.value as AppRole)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                disabled={loading || submitting}
              >
                <option value="viewer">Viewer</option>
                <option value="operator">Operator</option>
                <option value="admin">Admin</option>
              </select>
            </label>
          </div>

          <div className="rounded-xl border border-slate-700 bg-slate-950/60 p-4">
            <p className="text-sm font-medium text-slate-100">File transfer</p>
            <p className="mt-1 text-xs text-slate-500">
              These flags are written into the Guacamole connection parameters for this agent and the workspace UI follows them immediately.
            </p>
            <div className="mt-4 flex flex-col gap-3 text-sm text-slate-200">
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={uploadEnabled}
                  onChange={(event) => setUploadEnabled(event.target.checked)}
                  disabled={loading || submitting}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-400 focus:ring-cyan-500/40"
                />
                Allow upload from browser to VM
              </label>
              <label className="inline-flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={downloadEnabled}
                  onChange={(event) => setDownloadEnabled(event.target.checked)}
                  disabled={loading || submitting}
                  className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-400 focus:ring-cyan-500/40"
                />
                Allow download from VM to browser
              </label>
            </div>
          </div>

          <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-xs text-slate-300">
            Suggested model: set read-only threshold lower than interactive threshold for production agents. For example: `viewer` can inspect, `admin` can control.
          </div>

          {error && <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div>}

          <div className="flex items-center justify-end gap-3 border-t border-slate-700 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:border-slate-600 hover:bg-slate-800"
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={async () => {
                setSubmitting(true);
                setError(null);
                try {
                  await sendJSON(`${API_BASE}/api/agent-registry/${encodeURIComponent(agentId)}`, "PATCH", {
                    hostname: hostname.trim(),
                    display_name: displayName.trim(),
                    guacamole_access: {
                      minimum_role: minimumRole,
                      interactive_minimum_role: interactiveMinimumRole,
                      file_transfer: {
                        upload_enabled: uploadEnabled,
                        download_enabled: downloadEnabled,
                      },
                    },
                  });
                  await onSaved?.();
                  onClose();
                } catch (nextError) {
                  setError(nextError instanceof Error ? nextError.message : String(nextError));
                } finally {
                  setSubmitting(false);
                }
              }}
              disabled={loading || submitting || !hostname.trim()}
              className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "Saving..." : "Save changes"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}