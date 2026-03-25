"use client";

export function SettingsPage() {
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
