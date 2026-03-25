"use client";

import { useMemo, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { useMetrics, type MetricRow } from "@/hooks/useTelemetryAPI";

interface TelemetryChartsProps {
  agentId: string;
}

type TimeRange = "15m" | "1h" | "6h" | "24h" | "7d";

const RANGE_MINUTES: Record<TimeRange, number> = {
  "15m": 15,
  "1h": 60,
  "6h": 360,
  "24h": 1440,
  "7d": 10080,
};

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

// Aggregate metrics by timestamp across all processes
function aggregateByTimestamp(rows: MetricRow[]) {
  const byTs = new Map<number, { cpu_sum: number; cpu_max: number; mem_sum: number; count: number }>();

  for (const r of rows) {
    const existing = byTs.get(r.ts);
    if (existing) {
      existing.cpu_sum += r.cpu_avg;
      existing.cpu_max = Math.max(existing.cpu_max, r.cpu_max);
      existing.mem_sum += r.mem_ws;
      existing.count++;
    } else {
      byTs.set(r.ts, { cpu_sum: r.cpu_avg, cpu_max: r.cpu_max, mem_sum: r.mem_ws, count: 1 });
    }
  }

  return Array.from(byTs.entries())
    .sort(([a], [b]) => a - b)
    .map(([ts, v]) => ({
      ts,
      time: formatTime(ts),
      cpu_avg: Number(v.cpu_sum.toFixed(1)),
      cpu_max: Number(v.cpu_max.toFixed(1)),
      memory: v.mem_sum,
    }));
}

// Per-process data for the top N consumers
function topProcessTimelines(rows: MetricRow[], topN: number = 5) {
  // Find top processes by average CPU
  const perProc = new Map<string, { cpuTotal: number; memTotal: number; count: number; exe: string }>();
  for (const r of rows) {
    const key = `${r.pid}`;
    const entry = perProc.get(key);
    if (entry) {
      entry.cpuTotal += r.cpu_avg;
      entry.memTotal += r.mem_ws;
      entry.count++;
    } else {
      perProc.set(key, { cpuTotal: r.cpu_avg, memTotal: r.mem_ws, count: 1, exe: r.exe });
    }
  }

  const allRanked = Array.from(perProc.entries())
    .map(([pid, v]) => ({ pid, exe: v.exe, avgCpu: v.cpuTotal / v.count, avgMem: v.memTotal / v.count }));

  const rankedCpu = [...allRanked].sort((a, b) => b.avgCpu - a.avgCpu).slice(0, topN);
  const rankedMem = [...allRanked].sort((a, b) => b.avgMem - a.avgMem).slice(0, topN);

  const topCpuPids = new Set(rankedCpu.map((r) => r.pid));
  const topMemPids = new Set(rankedMem.map((r) => r.pid));

  // Build CPU timelines
  const cpuByTs = new Map<number, Record<string, number>>();
  const memByTs = new Map<number, Record<string, number>>();
  for (const r of rows) {
    const pidStr = `${r.pid}`;
    if (topCpuPids.has(pidStr)) {
      if (!cpuByTs.has(r.ts)) cpuByTs.set(r.ts, {});
      cpuByTs.get(r.ts)![`cpu_${pidStr}`] = r.cpu_avg;
    }
    if (topMemPids.has(pidStr)) {
      if (!memByTs.has(r.ts)) memByTs.set(r.ts, {});
      memByTs.get(r.ts)![`mem_${pidStr}`] = r.mem_ws;
    }
  }

  const cpuData = Array.from(cpuByTs.entries())
    .sort(([a], [b]) => a - b)
    .map(([ts, vals]) => ({ ts, time: formatTime(ts), ...vals }));

  const memData = Array.from(memByTs.entries())
    .sort(([a], [b]) => a - b)
    .map(([ts, vals]) => ({ ts, time: formatTime(ts), ...vals }));

  return { cpuData, memData, rankedCpu, rankedMem };
}

const COLORS = ["#f59e0b", "#10b981", "#6366f1", "#ec4899", "#06b6d4", "#f97316"];

export function TelemetryCharts({ agentId }: TelemetryChartsProps) {
  const [range, setRange] = useState<TimeRange>("1h");
  const [showBreakdowns, setShowBreakdowns] = useState(false);
  const { data: metrics, loading } = useMetrics(agentId, undefined, RANGE_MINUTES[range]);

  const aggregate = useMemo(() => aggregateByTimestamp(metrics), [metrics]);
  const { cpuData, memData, rankedCpu, rankedMem } = useMemo(
    () => topProcessTimelines(metrics, 5),
    [metrics]
  );

  return (
    <div className="space-y-6">
      {/* Time range selector */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-300">Telemetry History</h3>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => setShowBreakdowns((current) => !current)}
            className={`px-3 py-1 text-xs rounded-md transition-colors ${
              showBreakdowns
                ? "bg-purple-600 text-white"
                : "bg-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-slate-300"
            }`}
          >
            {showBreakdowns ? "Hide breakdowns" : "Show breakdowns"}
          </button>
          <div className="flex gap-1">
            {(Object.keys(RANGE_MINUTES) as TimeRange[]).map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className={`px-3 py-1 text-xs rounded-md transition-colors ${
                  range === r
                    ? "bg-blue-600 text-white"
                    : "bg-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-slate-300"
                }`}
              >
                {r}
              </button>
            ))}
          </div>
          {loading && (
            <span className="ml-2 text-xs text-slate-500 animate-pulse">loading...</span>
          )}
        </div>
      </div>

      {metrics.length === 0 && !loading ? (
        <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-8 text-center">
          <p className="text-slate-500 text-sm">
            No telemetry data yet — metrics appear after the first flush (~60s after server start).
          </p>
        </div>
      ) : (
        <>
          {/* Aggregate CPU/Memory */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {/* CPU chart */}
            <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
                CPU Usage (aggregate)
              </h4>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={aggregate}>
                  <defs>
                    <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="cpuMaxGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#ef4444" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 10 }} />
                  <YAxis tick={{ fill: "#64748b", fontSize: 10 }} unit="%" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "1px solid #334155",
                      borderRadius: "8px",
                      fontSize: 12,
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="cpu_max"
                    stroke="#ef4444"
                    fill="url(#cpuMaxGrad)"
                    strokeWidth={1}
                    name="Peak"
                  />
                  <Area
                    type="monotone"
                    dataKey="cpu_avg"
                    stroke="#f59e0b"
                    fill="url(#cpuGrad)"
                    strokeWidth={2}
                    name="Average"
                  />
                  <Legend
                    verticalAlign="top"
                    height={24}
                    wrapperStyle={{ fontSize: 11, color: "#94a3b8" }}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>

            {/* Memory chart */}
            <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
                Memory Usage (Working Set)
              </h4>
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={aggregate}>
                  <defs>
                    <linearGradient id="memGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#8b5cf6" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#8b5cf6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 10 }} />
                  <YAxis
                    tick={{ fill: "#64748b", fontSize: 10 }}
                    tickFormatter={(v: number) => formatBytes(v)}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "1px solid #334155",
                      borderRadius: "8px",
                      fontSize: 12,
                    }}
                    formatter={(value) => [formatBytes(Number(value)), "Working Set"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="memory"
                    stroke="#8b5cf6"
                    fill="url(#memGrad)"
                    strokeWidth={2}
                    name="Working Set"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Per-process CPU breakdown */}
          {showBreakdowns && cpuData.length > 0 && (
            <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                Top Process CPU Breakdown
              </h4>
              <div className="flex gap-3 mb-3 flex-wrap">
                {rankedCpu.map((p, i) => (
                  <span key={p.pid} className="flex items-center gap-1.5 text-xs text-slate-400">
                    <span
                      className="w-2.5 h-2.5 rounded-full inline-block"
                      style={{ backgroundColor: COLORS[i % COLORS.length] }}
                    />
                    <span className="font-mono">{p.exe}</span>
                    <span className="text-slate-600">({p.pid})</span>
                  </span>
                ))}
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={cpuData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 10 }} />
                  <YAxis tick={{ fill: "#64748b", fontSize: 10 }} unit="%" />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "1px solid #334155",
                      borderRadius: "8px",
                      fontSize: 12,
                    }}
                  />
                  {rankedCpu.map((p, i) => (
                    <Area
                      key={p.pid}
                      type="monotone"
                      dataKey={`cpu_${p.pid}`}
                      stackId="1"
                      stroke={COLORS[i % COLORS.length]}
                      fill={COLORS[i % COLORS.length]}
                      fillOpacity={0.3}
                      strokeWidth={1.5}
                      name={`${p.exe} (${p.pid})`}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Per-process Memory breakdown */}
          {showBreakdowns && memData.length > 0 && (
            <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">
                Top Process Memory Breakdown
              </h4>
              <div className="flex gap-3 mb-3 flex-wrap">
                {rankedMem.map((p, i) => (
                  <span key={p.pid} className="flex items-center gap-1.5 text-xs text-slate-400">
                    <span
                      className="w-2.5 h-2.5 rounded-full inline-block"
                      style={{ backgroundColor: COLORS[i % COLORS.length] }}
                    />
                    <span className="font-mono">{p.exe}</span>
                    <span className="text-slate-600">({p.pid})</span>
                  </span>
                ))}
              </div>
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={memData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 10 }} />
                  <YAxis
                    tick={{ fill: "#64748b", fontSize: 10 }}
                    tickFormatter={(v: number) => formatBytes(v)}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#1e293b",
                      border: "1px solid #334155",
                      borderRadius: "8px",
                      fontSize: 12,
                    }}
                    formatter={(value, name) => [formatBytes(Number(value)), name]}
                  />
                  {rankedMem.map((p, i) => (
                    <Area
                      key={p.pid}
                      type="monotone"
                      dataKey={`mem_${p.pid}`}
                      stackId="1"
                      stroke={COLORS[i % COLORS.length]}
                      fill={COLORS[i % COLORS.length]}
                      fillOpacity={0.3}
                      strokeWidth={1.5}
                      name={`${p.exe} (${p.pid})`}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {!showBreakdowns && (cpuData.length > 0 || memData.length > 0) && (
            <div className="rounded-lg border border-dashed border-slate-700 bg-slate-800/20 p-4 text-sm text-slate-500">
              Per-process breakdown charts are hidden by default to reduce overview rendering cost.
            </div>
          )}
        </>
      )}
    </div>
  );
}
