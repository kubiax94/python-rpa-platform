"use client";

import { useEvents } from "@/hooks/useTelemetryAPI";

interface EventLogProps {
  agentId: string;
}

function formatTimestamp(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleString("pl-PL", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function relativeTime(ts: number): string {
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

const EVENT_STYLES: Record<string, { icon: string; color: string; bg: string }> = {
  start: { icon: "▶", color: "text-emerald-400", bg: "bg-emerald-500/10" },
  stop: { icon: "■", color: "text-slate-400", bg: "bg-slate-500/10" },
  fail: { icon: "✕", color: "text-red-400", bg: "bg-red-500/10" },
  disappeared: { icon: "?", color: "text-amber-400", bg: "bg-amber-500/10" },
  restart: { icon: "↻", color: "text-blue-400", bg: "bg-blue-500/10" },
};

function getEventStyle(type: string) {
  return EVENT_STYLES[type] || { icon: "•", color: "text-slate-400", bg: "bg-slate-500/10" };
}

export function EventLog({ agentId }: EventLogProps) {
  const { data: events, loading } = useEvents(agentId, undefined, 100);

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          Event Log
        </h3>
        {loading && <span className="text-xs text-slate-500 animate-pulse">refreshing...</span>}
      </div>

      {events.length === 0 ? (
        <p className="text-sm text-slate-500 italic py-4 text-center">
          {loading ? "Loading events..." : "No events recorded yet — events appear after process start/stop/fail."}
        </p>
      ) : (
        <div className="space-y-1 max-h-80 overflow-y-auto pr-1">
          {events.map((ev) => {
            const style = getEventStyle(ev.type);
            return (
              <div
                key={ev.id}
                className={`flex items-center gap-3 px-3 py-2 rounded-md ${style.bg} transition-colors hover:brightness-110`}
              >
                <span className={`text-base w-5 text-center ${style.color}`}>{style.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`text-xs font-semibold uppercase ${style.color}`}>
                      {ev.type}
                    </span>
                    {ev.exe && (
                      <span className="text-xs text-slate-300 font-mono truncate">{ev.exe}</span>
                    )}
                    {ev.pid && (
                      <span className="text-xs text-slate-500 font-mono">PID {ev.pid}</span>
                    )}
                  </div>
                  {ev.detail && (
                    <p className="text-xs text-slate-500 mt-0.5 truncate">{ev.detail}</p>
                  )}
                </div>
                <div className="text-right shrink-0">
                  <p className="text-xs text-slate-500" title={formatTimestamp(ev.ts)}>
                    {relativeTime(ev.ts)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
