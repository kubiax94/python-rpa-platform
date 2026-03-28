"use client";

import { useGuacamoleConfig } from "@/hooks/useGuacamole";

export function SettingsPage() {
  const { data: guacamoleConfig, loading } = useGuacamoleConfig();

  return (
    <div>
      <h1 className="text-xl font-semibold text-slate-100 mb-6">Settings</h1>
      <div className="space-y-4 max-w-lg">
        <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
          <h2 className="text-sm font-medium text-slate-200 mb-3">Connection</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">WebSocket URL</span>
              <span className="font-mono text-slate-300">ws://localhost:8765</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Heartbeat interval</span>
              <span className="font-mono text-slate-300">1s (sync every 10s)</span>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
          <h2 className="text-sm font-medium text-slate-200 mb-3">Guacamole</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">Bridge status</span>
              <span className="font-mono text-slate-300">
                {loading ? "loading" : guacamoleConfig?.enabled ? "enabled" : "disabled"}
              </span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">Configured</span>
              <span className="font-mono text-slate-300">{guacamoleConfig?.configured ? "yes" : "no"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">Base URL</span>
              <span className="font-mono text-slate-300 break-all text-right">{guacamoleConfig?.base_url || "-"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">API user configured</span>
              <span className="font-mono text-slate-300">{guacamoleConfig?.auth_username_configured ? "yes" : "no"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">API password configured</span>
              <span className="font-mono text-slate-300">{guacamoleConfig?.auth_password_configured ? "yes" : "no"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">Auth provider</span>
              <span className="font-mono text-slate-300">{guacamoleConfig?.auth_provider || "-"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">Default mapping</span>
              <span className="font-mono text-slate-300">{guacamoleConfig?.default_connection_mode || "-"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">Connection type</span>
              <span className="font-mono text-slate-300">{guacamoleConfig?.connection_type || "-"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">Static mappings</span>
              <span className="font-mono text-slate-300">{guacamoleConfig?.mapping_count ?? 0}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">WebSocket tunnel</span>
              <span className="font-mono text-slate-300 break-all text-right">{guacamoleConfig?.websocket_tunnel_url || "-"}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-slate-400">HTTP tunnel</span>
              <span className="font-mono text-slate-300 break-all text-right">{guacamoleConfig?.http_tunnel_url || "-"}</span>
            </div>
          </div>
          {!!guacamoleConfig?.notes?.length && (
            <div className="mt-4 space-y-2 rounded-md border border-slate-700/80 bg-slate-900/60 p-3 text-xs text-slate-400">
              {guacamoleConfig.notes.map((note) => (
                <p key={note}>{note}</p>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
          <h2 className="text-sm font-medium text-slate-200 mb-3">About</h2>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Version</span>
              <span className="font-mono text-slate-300">0.1.0</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Protocol</span>
              <span className="font-mono text-slate-300">WebSocket + JSON</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
