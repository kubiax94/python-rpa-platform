"use client";

interface ConnectionStatusProps {
  connected: boolean;
  agentCount: number;
}

export function ConnectionStatus({ connected, agentCount }: ConnectionStatusProps) {
  return (
    <div className="flex items-center gap-4 text-sm">
      <div className="flex items-center gap-2">
        <div
          className={`w-2.5 h-2.5 rounded-full ${
            connected ? "bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.5)]" : "bg-red-400"
          }`}
        />
        <span className="text-slate-400">
          {connected ? "Connected" : "Disconnected"}
        </span>
      </div>
      <span className="text-slate-500">|</span>
      <span className="text-slate-400">
        {agentCount} agent{agentCount !== 1 ? "s" : ""}
      </span>
    </div>
  );
}
