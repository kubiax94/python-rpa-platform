"use client";

import { useEffect, useMemo, useState } from "react";
import { API_BASE, fetchJSON, sendJSON } from "@/lib/auth";
import { formatRoleLabel, type AppRole } from "@/lib/rbac";
import type { GuacamoleAccessPolicy, GuacamolePermissionKey } from "@/hooks/useGuacamole";
import { createDefaultGuacamoleAccessPolicy, GUACAMOLE_PERMISSION_ROWS, joinPrincipalList, splitPrincipalList } from "@/lib/guacamoleAccess";

type AgentRegistryResponse = {
  id: string;
  hostname?: string;
  display_name?: string;
  metadata?: {
    guacamole?: {
      access?: GuacamoleAccessPolicy;
    };
  };
};

interface AgentAccessPolicyPanelProps {
  agentId: string;
  active: boolean;
  canManageAccess: boolean;
}

export function AgentAccessPolicyPanel({ agentId, active, canManageAccess }: AgentAccessPolicyPanelProps) {
  const [hostname, setHostname] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [policy, setPolicy] = useState<GuacamoleAccessPolicy>(createDefaultGuacamoleAccessPolicy());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!active) {
      return;
    }

    setLoading(true);
    setError(null);
    setSuccessMessage(null);
    void fetchJSON<AgentRegistryResponse>(`${API_BASE}/api/agent-registry/${encodeURIComponent(agentId)}`)
      .then((response) => {
        setHostname(response.hostname || agentId);
        setDisplayName(response.display_name || response.hostname || agentId);
        setPolicy(response.metadata?.guacamole?.access ?? createDefaultGuacamoleAccessPolicy());
      })
      .catch((nextError) => {
        setError(nextError instanceof Error ? nextError.message : String(nextError));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [active, agentId]);

  const rows = useMemo(() => GUACAMOLE_PERMISSION_ROWS.map((row) => ({
    ...row,
    rule: policy.permissions[row.key],
  })), [policy]);

  const updateRule = (permission: GuacamolePermissionKey, patch: Partial<GuacamoleAccessPolicy["permissions"][GuacamolePermissionKey]>) => {
    setPolicy((current) => ({
      ...current,
      permissions: {
        ...current.permissions,
        [permission]: {
          ...current.permissions[permission],
          ...patch,
        },
      },
    }));
  };

  if (!active) {
    return null;
  }

  if (!canManageAccess) {
    return (
      <div className="rounded-xl border border-slate-700 bg-slate-800/30 p-4 text-sm text-slate-400">
        Access Policy management requires admin role.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-700 bg-slate-800/30 p-5">
        <div className="mb-4">
          <h2 className="text-base font-semibold text-slate-100">Access Policy</h2>
          <p className="mt-1 text-sm text-slate-400">
            Access is granted if the user matches the minimum app role or is explicitly listed by user subject or Entra group object ID.
          </p>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block text-slate-300">Hostname / FQDN</span>
            <input
              value={hostname}
              onChange={(event) => setHostname(event.target.value)}
              disabled={loading || saving}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block text-slate-300">Display Name</span>
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              disabled={loading || saving}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
            />
          </label>
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-700 bg-slate-800/30">
        <div className="border-b border-slate-700 px-5 py-4">
          <h3 className="text-sm font-semibold text-slate-100">Permission Matrix</h3>
          <p className="mt-1 text-xs text-slate-500">One group object ID or user subject per line.</p>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-700 text-sm">
            <thead className="bg-slate-900/70 text-xs uppercase tracking-[0.16em] text-slate-500">
              <tr>
                <th className="px-4 py-3 text-left">Capability</th>
                <th className="px-4 py-3 text-left">Enabled</th>
                <th className="px-4 py-3 text-left">Minimum Role</th>
                <th className="px-4 py-3 text-left">Groups</th>
                <th className="px-4 py-3 text-left">Users</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rows.map(({ key, label, description, rule }) => (
                <tr key={key} className="align-top">
                  <td className="px-4 py-4">
                    <div className="font-medium text-slate-100">{label}</div>
                    <div className="mt-1 max-w-sm text-xs text-slate-500">{description}</div>
                  </td>
                  <td className="px-4 py-4">
                    <label className="inline-flex items-center gap-2 text-slate-200">
                      <input
                        type="checkbox"
                        checked={rule.enabled}
                        disabled={loading || saving}
                        onChange={(event) => updateRule(key, { enabled: event.target.checked })}
                        className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-400 focus:ring-cyan-500/40"
                      />
                      <span>{rule.enabled ? "On" : "Off"}</span>
                    </label>
                  </td>
                  <td className="px-4 py-4">
                    <select
                      value={rule.minimum_role}
                      disabled={loading || saving}
                      onChange={(event) => updateRule(key, { minimum_role: event.target.value as AppRole })}
                      className="w-36 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none focus:border-cyan-500"
                    >
                      <option value="viewer">Viewer</option>
                      <option value="operator">Operator</option>
                      <option value="admin">Admin</option>
                    </select>
                    <div className="mt-2 text-xs text-slate-500">Fallback gate: {formatRoleLabel(rule.minimum_role)}</div>
                  </td>
                  <td className="px-4 py-4">
                    <textarea
                      value={joinPrincipalList(rule.groups)}
                      disabled={loading || saving}
                      onChange={(event) => updateRule(key, { groups: splitPrincipalList(event.target.value) })}
                      rows={4}
                      className="w-56 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="group object id"
                    />
                  </td>
                  <td className="px-4 py-4">
                    <textarea
                      value={joinPrincipalList(rule.users)}
                      disabled={loading || saving}
                      onChange={(event) => updateRule(key, { users: splitPrincipalList(event.target.value) })}
                      rows={4}
                      className="w-56 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-100 outline-none focus:border-cyan-500"
                      placeholder="user subject"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-4 py-3 text-xs text-slate-300">
        Recommended production pattern: keep `Remote View` broader, but restrict `Interactive Input`, `File Upload`, `File Download` and `Session Kick` to explicit DevOps groups.
      </div>

      {error && <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div>}
      {successMessage && <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">{successMessage}</div>}

      <div className="flex justify-end">
        <button
          type="button"
          disabled={loading || saving || !hostname.trim()}
          onClick={async () => {
            setSaving(true);
            setError(null);
            setSuccessMessage(null);
            try {
              await sendJSON(`${API_BASE}/api/agent-registry/${encodeURIComponent(agentId)}`, "PATCH", {
                hostname: hostname.trim(),
                display_name: displayName.trim(),
                guacamole_access: {
                  permissions: policy.permissions,
                },
              });
              setSuccessMessage("Access policy saved.");
            } catch (nextError) {
              setError(nextError instanceof Error ? nextError.message : String(nextError));
            } finally {
              setSaving(false);
            }
          }}
          className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-4 py-2 text-sm font-medium text-cyan-100 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save Access Policy"}
        </button>
      </div>
    </div>
  );
}