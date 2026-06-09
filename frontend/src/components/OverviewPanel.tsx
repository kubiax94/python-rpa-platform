"use client";

import dynamic from "next/dynamic";
import { type ReactNode, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getAgentMetrics, getAgentSessions, type AgentState, type SessionReplica } from "@/types/agent";
import { useMetrics, type MetricRow } from "@/hooks/useTelemetryAPI";
import { EventLog } from "./EventLog";

const TelemetryCharts = dynamic(
  () => import("./TelemetryCharts").then((module) => module.TelemetryCharts),
  {
    ssr: false,
    loading: () => (
      <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4 text-sm text-slate-500">
        Loading telemetry charts...
      </div>
    ),
  }
);

interface OverviewPanelProps {
  agentId: string;
  state: AgentState;
}

interface ConsumerItem {
  pid: string;
  exe: string;
  cpu: number;
  mem: number;
  memPrivate: number;
  ioReadBps: number;
  ioWriteBps: number;
  ioOtherBps: number;
  session: string;
}

interface SessionSummary {
  sessionKey: string;
  sessionId: number | null;
  displayName: string;
  username: string | null;
  status?: string;
  procCount: number;
  cpuTotal: number;
  memWs: number;
  memPb: number;
  ioReadBps: number;
  ioWriteBps: number;
}

interface SessionHistoryPoint {
  ts: number;
  time: string;
  cpu: number;
  memory: number;
  io: number;
  ioRead: number;
  ioWrite: number;
  processCount: number;
}

type TopN = 5 | 10 | 15 | 25;
type HistoryRange = "15m" | "1h" | "6h" | "24h";
type ConsumerScope = "machine" | "session";

const TOP_N_OPTIONS: TopN[] = [5, 10, 15, 25];
const HISTORY_RANGE_MINUTES: Record<HistoryRange, number> = {
  "15m": 15,
  "1h": 60,
  "6h": 360,
  "24h": 1440,
};

function formatBytes(bytes: number, fractionDigits = 1): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(fractionDigits)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(fractionDigits)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(fractionDigits)} GB`;
}

function formatPercent(value: number): string {
  return `${value.toFixed(2)}%`;
}

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString("pl-PL", { hour: "2-digit", minute: "2-digit" });
}

function formatDuration(seconds?: number): string {
  if (!seconds || seconds <= 0) return "—";
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function formatRate(bytesPerSecond?: number): string {
  if (bytesPerSecond == null || bytesPerSecond < 0) return "—";
  return `${formatBytes(bytesPerSecond, 2)}/s`;
}

function formatIoPair(read?: number, write?: number): string {
  return `R ${formatRate(read)} | W ${formatRate(write)}`;
}

function sessionStatusBadge(status?: string) {
  if (!status) return { text: "Unknown", cls: "bg-slate-600/30 text-slate-400" };
  switch (status) {
    case "Active": return { text: "Active", cls: "bg-emerald-500/20 text-emerald-400" };
    case "Connected": return { text: "Connected", cls: "bg-blue-500/20 text-blue-400" };
    case "Disconnected": return { text: "Disconnected", cls: "bg-amber-500/20 text-amber-400" };
    case "Down": return { text: "Down", cls: "bg-red-500/20 text-red-400" };
    case "Idle": return { text: "Idle", cls: "bg-slate-500/20 text-slate-400" };
    default: return { text: status, cls: "bg-slate-600/30 text-slate-400" };
  }
}

function cleanSessionKey(key: string): string {
  return key.replace(/-None$/, "");
}

function resolveSessionLabel(sessionKey: string, sessionData: SessionReplica): string {
  if (sessionData.session_name) return cleanSessionKey(sessionData.session_name);
  if (sessionData.username && sessionData.username !== "unknown") return sessionData.username;
  return cleanSessionKey(sessionKey);
}

function aggregateSessionHistory(rows: MetricRow[], sessionId: number | null): SessionHistoryPoint[] {
  if (sessionId == null) {
    return [];
  }

  const byTimestamp = new Map<number, {
    cpu: number;
    memory: number;
    ioRead: number;
    ioWrite: number;
    processIds: Set<number>;
  }>();

  for (const row of rows) {
    if (row.session_id !== sessionId) {
      continue;
    }

    const existing = byTimestamp.get(row.ts);
    if (existing) {
      existing.cpu += row.cpu_avg ?? 0;
      existing.memory += row.mem_ws ?? 0;
      existing.ioRead += row.io_read_bps ?? 0;
      existing.ioWrite += row.io_write_bps ?? 0;
      existing.processIds.add(row.pid);
    } else {
      byTimestamp.set(row.ts, {
        cpu: row.cpu_avg ?? 0,
        memory: row.mem_ws ?? 0,
        ioRead: row.io_read_bps ?? 0,
        ioWrite: row.io_write_bps ?? 0,
        processIds: new Set([row.pid]),
      });
    }
  }

  return Array.from(byTimestamp.entries())
    .sort(([left], [right]) => left - right)
    .map(([ts, value]) => ({
      ts,
      time: formatTime(ts),
      cpu: Number(value.cpu.toFixed(2)),
      memory: value.memory,
      io: Number((value.ioRead + value.ioWrite).toFixed(2)),
      ioRead: Number(value.ioRead.toFixed(2)),
      ioWrite: Number(value.ioWrite.toFixed(2)),
      processCount: value.processIds.size,
    }));
}

export function OverviewPanel({ agentId, state }: OverviewPanelProps) {
  const sessions = getAgentSessions(state);
  const systemMetrics = getAgentMetrics(state);
  const [topN, setTopN] = useState<TopN>(10);
  const [historyRange, setHistoryRange] = useState<HistoryRange>("1h");
  const [selectedSessionKey, setSelectedSessionKey] = useState<string | null>(null);
  const [consumerScope, setConsumerScope] = useState<ConsumerScope>("machine");
  const { data: metricHistory, loading: metricHistoryLoading } = useMetrics(agentId, undefined, HISTORY_RANGE_MINUTES[historyRange]);
  const diskSummary = systemMetrics?.disk_total_bytes
    ? `${formatBytes(systemMetrics.disk_free_bytes ?? 0)} free / ${formatBytes(systemMetrics.disk_total_bytes)} total${systemMetrics.system_drive ? ` (${systemMetrics.system_drive})` : ""}`
    : "—";
  const osSummary = systemMetrics?.os_name
    ? `${systemMetrics.os_name}${systemMetrics.os_version ? ` ${systemMetrics.os_version}` : ""}`
    : "—";
  const cpuSummary = systemMetrics?.cpu_model
    ? `${systemMetrics.cpu_model}${systemMetrics.logical_cores ? ` (${systemMetrics.logical_cores} cores)` : ""}`
    : "—";
  const azureVmSummary = systemMetrics?.is_azure
    ? [systemMetrics.azure_vm_name, systemMetrics.azure_vm_size].filter(Boolean).join(" • ") || "Azure VM"
    : "Non-Azure host";
  const azureLocationSummary = systemMetrics?.is_azure
    ? [systemMetrics.azure_location, systemMetrics.azure_zone ? `zone ${systemMetrics.azure_zone}` : ""].filter(Boolean).join(" • ") || "—"
    : "—";
  const maintenanceSummary = systemMetrics?.maintenance_summary || "—";
  const ipSummary = systemMetrics?.azure_private_ip || systemMetrics?.azure_public_ip || "—";
  const diskIoSummary = systemMetrics
    ? formatIoPair(systemMetrics.disk_read_bps, systemMetrics.disk_write_bps)
    : "—";
  const networkSummary = systemMetrics
    ? `In ${formatRate(systemMetrics.network_recv_bps)} | Out ${formatRate(systemMetrics.network_sent_bps)}`
    : "—";

  const stats = useMemo(() => {
    let totalProcs = 0;
    let totalCpu = 0;
    let totalMemoryWs = 0;
    let totalMemoryPb = 0;
    const allProcs: ConsumerItem[] = [];
    const sessionSummaries: SessionSummary[] = [];

    for (const [sessionKey, session] of sessions) {
      let sessionCpu = 0;
      let sessionMemWs = 0;
      let sessionMemPb = 0;
      let sessionIoReadBps = 0;
      let sessionIoWriteBps = 0;

      for (const [pid, proc] of Object.entries(session.processes || {})) {
        totalProcs++;
        const cpu = proc.cpu_usage ?? 0;
        const mem = proc.memory_usage?.working_set_size ?? 0;
        const memPrivate = proc.memory_usage?.private_bytes ?? 0;
        const ioReadBps = proc.io_counters?.read_bps ?? 0;
        const ioWriteBps = proc.io_counters?.write_bps ?? 0;
        const ioOtherBps = proc.io_counters?.other_bps ?? 0;

        totalCpu += cpu;
        totalMemoryWs += mem;
        totalMemoryPb += memPrivate;
        sessionCpu += cpu;
        sessionMemWs += mem;
        sessionMemPb += memPrivate;
        sessionIoReadBps += ioReadBps;
        sessionIoWriteBps += ioWriteBps;

        allProcs.push({
          pid,
          exe: proc.exe || "unknown",
          cpu,
          mem,
          memPrivate,
          ioReadBps,
          ioWriteBps,
          ioOtherBps,
          session: sessionKey,
        });
      }

      sessionSummaries.push({
        sessionKey,
        sessionId: session.session_id ?? null,
        displayName: resolveSessionLabel(sessionKey, session),
        username: session.username && session.username !== "unknown" ? session.username : null,
        status: session.status,
        procCount: typeof session.process_count === "number" ? session.process_count : Object.keys(session.processes || {}).length,
        cpuTotal: sessionCpu,
        memWs: sessionMemWs,
        memPb: sessionMemPb,
        ioReadBps: sessionIoReadBps,
        ioWriteBps: sessionIoWriteBps,
      });
    }

    const topCpu = [...allProcs].sort((a, b) => b.cpu - a.cpu);
    const topMem = [...allProcs].sort((a, b) => Math.max(b.mem, b.memPrivate) - Math.max(a.mem, a.memPrivate));
    const topIo = [...allProcs].sort(
      (a, b) => (b.ioReadBps + b.ioWriteBps + b.ioOtherBps) - (a.ioReadBps + a.ioWriteBps + a.ioOtherBps)
    );

    sessionSummaries.sort((a, b) => {
      const leftActive = a.status === "Active" ? 1 : 0;
      const rightActive = b.status === "Active" ? 1 : 0;
      if (leftActive !== rightActive) return rightActive - leftActive;
      return b.cpuTotal - a.cpuTotal;
    });

    return {
      totalProcs,
      totalCpu,
      totalMemoryWs,
      totalMemoryPb,
      topCpu,
      topMem,
      topIo,
      sessionSummaries,
    };
  }, [sessions]);

  const selectedSession = selectedSessionKey
    ? stats.sessionSummaries.find((session) => session.sessionKey === selectedSessionKey) ?? null
    : null;

  const sessionHistory = useMemo(
    () => aggregateSessionHistory(metricHistory, selectedSession?.sessionId ?? null),
    [metricHistory, selectedSession?.sessionId]
  );

  const scopedCpuItems = consumerScope === "session" && selectedSessionKey
    ? stats.topCpu.filter((item) => item.session === selectedSessionKey)
    : stats.topCpu;
  const scopedMemoryItems = consumerScope === "session" && selectedSessionKey
    ? stats.topMem.filter((item) => item.session === selectedSessionKey)
    : stats.topMem;
  const scopedIoItems = consumerScope === "session" && selectedSessionKey
    ? stats.topIo.filter((item) => item.session === selectedSessionKey)
    : stats.topIo;

  const scopedSummary = consumerScope === "session" && selectedSession
    ? {
        label: selectedSession.displayName,
        cpu: formatPercent(selectedSession.cpuTotal),
        memory: `WS ${formatBytes(selectedSession.memWs)} | PB ${formatBytes(selectedSession.memPb)}`,
        io: formatIoPair(selectedSession.ioReadBps, selectedSession.ioWriteBps),
      }
    : {
        label: "Whole machine",
        cpu: formatPercent(stats.totalCpu),
        memory: `WS ${formatBytes(stats.totalMemoryWs)} | PB ${formatBytes(stats.totalMemoryPb)}`,
        io: `Disk ${diskIoSummary} | Net ${networkSummary}`,
      };

  const memoryFill = systemMetrics?.total_ram_bytes
    ? Math.min((stats.totalMemoryWs / systemMetrics.total_ram_bytes) * 100, 100)
    : 0;

  const networkCardValue = (
    <DualMetricValue
      firstLabel="IN"
      firstValue={formatRate(systemMetrics?.network_recv_bps)}
      secondLabel="OUT"
      secondValue={formatRate(systemMetrics?.network_sent_bps)}
    />
  );

  const diskCardValue = (
    <DualMetricValue
      firstLabel="READ"
      firstValue={formatRate(systemMetrics?.disk_read_bps)}
      secondLabel="WRITE"
      secondValue={formatRate(systemMetrics?.disk_write_bps)}
    />
  );

  const memoryCardValue = (
    <span className="font-mono tabular-nums whitespace-nowrap text-lg xl:text-xl text-fuchsia-400">
      {systemMetrics?.total_ram_bytes
        ? `${formatBytes(stats.totalMemoryWs, 2)} / ${formatBytes(systemMetrics.total_ram_bytes, 2)}`
        : formatBytes(stats.totalMemoryWs, 2)}
    </span>
  );

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
          System Information
        </h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
          <InfoRow label="Agent ID" value={agentId.substring(0, 16)} mono />
          <InfoRow label="Hostname" value={systemMetrics?.hostname || "—"} />
          <InfoRow label="OS" value={osSummary} hint={systemMetrics?.os_build} />
          <InfoRow label="Azure VM" value={azureVmSummary} hint={azureLocationSummary} />
          <InfoRow label="Disk" value={diskSummary} />
          <InfoRow label="CPU Model" value={cpuSummary} />
          <InfoRow label="Uptime" value={formatDuration(systemMetrics?.uptime_seconds)} />
          <InfoRow label="Maintenance" value={maintenanceSummary} />
          <InfoRow label="Private IP" value={ipSummary} />
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-4 gap-4">
        {stats.sessionSummaries.map((session) => (
          <SessionCard
            key={session.sessionKey}
            session={session}
            selected={selectedSessionKey === session.sessionKey}
            onClick={() => {
              const nextSelected = selectedSessionKey === session.sessionKey ? null : session.sessionKey;
              setSelectedSessionKey(nextSelected);
              setConsumerScope(nextSelected ? "session" : "machine");
            }}
          />
        ))}
      </div>

      {selectedSession && (
        <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4 space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h3 className="text-sm font-semibold text-slate-200">
                Session History: {selectedSession.displayName}
              </h3>
              <p className="text-xs text-slate-500">
                CPU, memory, disk I/O and process count for the selected session.
              </p>
            </div>
            <div className="flex items-center gap-1 flex-wrap">
              {(Object.keys(HISTORY_RANGE_MINUTES) as HistoryRange[]).map((range) => (
                <button
                  key={range}
                  type="button"
                  onClick={() => setHistoryRange(range)}
                  className={`px-3 py-1.5 text-xs rounded-lg transition-all shadow-sm ${
                    historyRange === range
                      ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-cyan-900/50 shadow-lg"
                      : "bg-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
                  }`}
                >
                  {range}
                </button>
              ))}
            </div>
          </div>

          {selectedSession.sessionId == null ? (
            <p className="text-sm text-slate-500">This session does not expose a stable session ID for historical aggregation.</p>
          ) : sessionHistory.length === 0 ? (
            <p className="text-sm text-slate-500">
              {metricHistoryLoading ? "Loading session history..." : "No session history yet. Data appears after the first telemetry DB flush."}
            </p>
          ) : (
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <HistoryChartCard
                title="CPU Usage"
                data={sessionHistory}
                dataKey="cpu"
                color="#f59e0b"
                valueFormatter={(value) => `${value.toFixed(2)}%`}
                yAxisFormatter={(value) => `${Math.round(value)}%`}
              />
              <HistoryChartCard
                title="Memory Usage"
                data={sessionHistory}
                dataKey="memory"
                color="#a855f7"
                valueFormatter={(value) => formatBytes(value, 2)}
                yAxisFormatter={(value) => formatBytes(value, 0)}
              />
              <HistoryChartCard
                title="Disk I/O"
                data={sessionHistory}
                dataKey="io"
                color="#10b981"
                subtitle="read + write throughput"
                valueFormatter={(value, entry) => `${formatRate(value)} (${formatIoPair(entry.ioRead, entry.ioWrite)})`}
                yAxisFormatter={(value) => formatBytes(value, 0)}
              />
              <HistoryChartCard
                title="Process Count"
                data={sessionHistory}
                dataKey="processCount"
                color="#38bdf8"
                valueFormatter={(value) => String(value)}
                yAxisFormatter={(value) => String(Math.round(value))}
              />
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
        <StatCard label="System CPU" value={formatPercent(systemMetrics?.cpu_usage ?? 0)} sub="host-wide" color="amber" />
        <StatCard label="Network" value={networkCardValue} sub="host throughput" color="blue" />
        <StatCard label="Disk I/O" value={diskCardValue} sub="host throughput" color="emerald" />
        <StatCard label="Total Memory" value={memoryCardValue} sub={`PB ${formatBytes(stats.totalMemoryPb, 2)}`} color="purple" progress={memoryFill} />
      </div>

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Show top</span>
          <div className="flex gap-1">
            {TOP_N_OPTIONS.map((n) => (
              <button
                key={n}
                onClick={() => setTopN(n)}
                className={`px-3 py-1.5 text-xs rounded-lg transition-all shadow-sm ${
                  topN === n
                    ? "bg-gradient-to-r from-cyan-500 to-blue-600 text-white shadow-cyan-900/50 shadow-lg"
                    : "bg-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-slate-200 hover:shadow-md hover:shadow-slate-950/40"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Scope</span>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setConsumerScope("machine")}
              className={`px-3 py-1.5 text-xs rounded-lg transition-all shadow-sm ${
                consumerScope === "machine"
                  ? "bg-gradient-to-r from-violet-500 to-fuchsia-600 text-white shadow-fuchsia-900/50 shadow-lg"
                  : "bg-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
              }`}
            >
              Whole machine
            </button>
            <button
              type="button"
              disabled={!selectedSession}
              onClick={() => selectedSession && setConsumerScope("session")}
              className={`px-3 py-1.5 text-xs rounded-lg transition-all shadow-sm ${
                consumerScope === "session"
                  ? "bg-gradient-to-r from-violet-500 to-fuchsia-600 text-white shadow-fuchsia-900/50 shadow-lg"
                  : "bg-slate-700/50 text-slate-400 hover:bg-slate-700 hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed"
              }`}
            >
              {selectedSession ? selectedSession.displayName : "Select session"}
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 2xl:grid-cols-3 gap-4">
        <TopConsumerList
          title="Top CPU Consumers"
          items={scopedCpuItems.slice(0, topN)}
          rows={topN}
          summary={`${scopedSummary.label} • ${scopedSummary.cpu}`}
          getValue={(p) => p.cpu}
          formatValue={(value) => formatPercent(value)}
          barColor="bg-amber-500"
          valueColor="text-amber-400"
        />

        <TopMemoryConsumerList
          title="Top Memory Consumers"
          items={scopedMemoryItems.slice(0, topN)}
          rows={topN}
          summary={`${scopedSummary.label} • ${scopedSummary.memory}`}
        />

        <TopConsumerList
          title="Top I/O Consumers"
          items={scopedIoItems.slice(0, topN)}
          rows={topN}
          summary={`${scopedSummary.label} • ${scopedSummary.io}`}
          getValue={(p) => p.ioReadBps + p.ioWriteBps + p.ioOtherBps}
          formatValue={(value) => formatRate(value)}
          barColor="bg-emerald-500"
          valueColor="text-emerald-400"
        />
      </div>

      <TelemetryCharts agentId={agentId} />
      <EventLog agentId={agentId} />
    </div>
  );
}

function StatCard({ label, value, sub, color, progress }: {
  label: string;
  value: ReactNode;
  sub: ReactNode;
  color: string;
  progress?: number;
}) {
  const colorMap: Record<string, string> = {
    blue: "text-blue-400",
    emerald: "text-emerald-400",
    amber: "text-amber-400",
    orange: "text-orange-400",
    purple: "text-purple-400",
  };
  const cardMap: Record<string, string> = {
    blue: "from-blue-950/60 via-slate-900/60 to-slate-900/80 shadow-blue-950/40",
    emerald: "from-emerald-950/60 via-slate-900/60 to-slate-900/80 shadow-emerald-950/40",
    amber: "from-amber-950/60 via-slate-900/60 to-slate-900/80 shadow-amber-950/30",
    orange: "from-orange-950/60 via-slate-900/60 to-slate-900/80 shadow-orange-950/30",
    purple: "from-fuchsia-950/60 via-slate-900/60 to-slate-900/80 shadow-fuchsia-950/30",
  };

  return (
    <div className={`rounded-lg border border-slate-700 bg-gradient-to-br ${cardMap[color] || "from-slate-900/80 to-slate-900/80"} p-4 shadow-lg`}>
      <p className="text-xs text-slate-500 uppercase tracking-wider">{label}</p>
      <div className={`mt-1 ${colorMap[color] || "text-slate-200"}`}>{value}</div>
      <p className="text-xs text-slate-500 mt-0.5">{sub}</p>
      {typeof progress === "number" && (
        <div className="mt-3 h-2 bg-slate-700/80 rounded-full overflow-hidden">
          <div className="h-full bg-fuchsia-400 rounded-full transition-[width] duration-300" style={{ width: `${progress}%` }} />
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value, hint, mono }: {
  label: string;
  value: string;
  hint?: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-slate-200 ${mono ? "font-mono" : ""}`} title={hint}>
        {value}
      </p>
    </div>
  );
}

function SessionCard({ session, selected, onClick }: { session: SessionSummary; selected: boolean; onClick: () => void }) {
  const badge = sessionStatusBadge(session.status);

  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full text-left rounded-lg border p-4 shadow-lg transition-all shadow-slate-950/30 bg-gradient-to-br from-slate-800/70 via-slate-900/80 to-slate-900/90 ${selected ? "border-cyan-500/80 ring-1 ring-cyan-400/40" : "border-slate-700 hover:border-slate-600"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-100">{session.displayName}</h3>
          {session.username && <p className="text-xs text-slate-400 mt-1">{session.username}</p>}
        </div>
        <span className={`px-2 py-0.5 rounded-full text-[11px] ${badge.cls}`}>
          {badge.text}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-3 mt-4 text-sm">
        <MiniMetric label="Processes" value={String(session.procCount)} accent="text-blue-400" />
        <MiniMetric label="CPU" value={formatPercent(session.cpuTotal)} accent="text-amber-400" />
        <MiniMetric label="I/O" value={formatIoPair(session.ioReadBps, session.ioWriteBps)} accent="text-emerald-400" />
        <MiniMetric label="Memory" value={`WS ${formatBytes(session.memWs)}`} secondary={`PB ${formatBytes(session.memPb)}`} accent="text-fuchsia-400" />
      </div>
    </button>
  );
}

function MiniMetric({ label, value, secondary, accent }: {
  label: string;
  value: string;
  secondary?: string;
  accent: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/30 p-3">
      <p className="text-[11px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-sm font-semibold ${accent}`}>{value}</p>
      {secondary && <p className="text-[11px] text-slate-500 mt-0.5">{secondary}</p>}
    </div>
  );
}

function DualMetricValue({ firstLabel, firstValue, secondLabel, secondValue }: {
  firstLabel: string;
  firstValue: string;
  secondLabel: string;
  secondValue: string;
}) {
  return (
    <div className="font-mono tabular-nums whitespace-nowrap text-base xl:text-lg leading-5">
      <div>
        <span className="text-slate-500 text-xs mr-2">{firstLabel}</span>
        <span>{firstValue}</span>
      </div>
      <div>
        <span className="text-slate-500 text-xs mr-2">{secondLabel}</span>
        <span>{secondValue}</span>
      </div>
    </div>
  );
}

function HistoryChartCard({
  title,
  data,
  dataKey,
  color,
  subtitle,
  valueFormatter,
  yAxisFormatter,
}: {
  title: string;
  data: SessionHistoryPoint[];
  dataKey: keyof SessionHistoryPoint;
  color: string;
  subtitle?: string;
  valueFormatter: (value: number, entry: SessionHistoryPoint) => string;
  yAxisFormatter: (value: number) => string;
}) {
  const gradientId = `grad-${title.replace(/[^a-z0-9]/gi, "")}`;

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/40 p-4">
      <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-1">{title}</h4>
      {subtitle && <p className="text-[11px] text-slate-500 mb-3">{subtitle}</p>}
      <ResponsiveContainer width="100%" height={180}>
        <AreaChart data={data}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.35} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis dataKey="time" tick={{ fill: "#64748b", fontSize: 10 }} />
          <YAxis tick={{ fill: "#64748b", fontSize: 10 }} tickFormatter={(value: number) => yAxisFormatter(value)} />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1e293b",
              border: "1px solid #334155",
              borderRadius: "8px",
              fontSize: 12,
            }}
            formatter={(value, _name, item) => [valueFormatter(Number(value ?? 0), item.payload as SessionHistoryPoint), title]}
          />
          <Area type="monotone" dataKey={dataKey} stroke={color} fill={`url(#${gradientId})`} strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function TopConsumerList({ title, items, rows, summary, getValue, formatValue, barColor, valueColor }: {
  title: string;
  items: ConsumerItem[];
  rows: number;
  summary?: string;
  getValue: (item: ConsumerItem) => number;
  formatValue: (value: number) => string;
  barColor: string;
  valueColor: string;
}) {
  const maxVal = items.length > 0 ? Math.max(getValue(items[0]), 0.001) : 1;
  const padded = Array.from({ length: rows }, (_, index) => items[index] ?? null);

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {title}
        </h3>
        {summary && <span className="text-[11px] text-slate-400 text-right">{summary}</span>}
      </div>
      <div className="space-y-1.5">
        {padded.map((proc, index) => (
          <div key={proc ? `${proc.session}-${proc.pid}` : `empty-${index}`} className="flex items-center gap-3 h-6">
            {proc ? (
              <>
                <span className="text-xs font-mono text-slate-500 w-12 shrink-0 text-right">{proc.pid}</span>
                <span className="text-xs text-slate-300 w-36 truncate shrink-0" title={proc.exe}>{proc.exe}</span>
                <div className="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden min-w-[60px]">
                  <div
                    className={`h-full ${barColor} rounded-full`}
                    style={{ width: `${Math.max((getValue(proc) / maxVal) * 100, 1)}%` }}
                  />
                </div>
                <span className={`text-xs font-mono ${valueColor} w-24 text-right shrink-0`}>
                  {formatValue(getValue(proc))}
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-700 select-none">—</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function TopMemoryConsumerList({ title, items, rows, summary }: {
  title: string;
  items: ConsumerItem[];
  rows: number;
  summary?: string;
}) {
  const maxVal = items.length > 0 ? Math.max(...items.map((item) => Math.max(item.mem, item.memPrivate)), 1) : 1;
  const padded = Array.from({ length: rows }, (_, index) => items[index] ?? null);

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-500">
          {title}
        </h3>
        {summary && <span className="text-[11px] text-slate-400 text-right">{summary}</span>}
      </div>
      <div className="space-y-2">
        {padded.map((proc, index) => (
          <div key={proc ? `${proc.session}-${proc.pid}` : `empty-${index}`} className="flex items-start gap-3 min-h-9">
            {proc ? (
              <>
                <span className="text-xs font-mono text-slate-500 w-12 shrink-0 text-right pt-1">{proc.pid}</span>
                <span className="text-xs text-slate-300 w-36 truncate shrink-0 pt-1" title={proc.exe}>{proc.exe}</span>
                <div className="flex-1 min-w-[80px] space-y-1 pt-1">
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-purple-500 rounded-full"
                      style={{ width: `${Math.max((proc.mem / maxVal) * 100, 1)}%` }}
                    />
                  </div>
                  <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-cyan-400 rounded-full"
                      style={{ width: `${Math.max((proc.memPrivate / maxVal) * 100, 1)}%` }}
                    />
                  </div>
                </div>
                <span className="text-[11px] font-mono text-right shrink-0 w-32 leading-4">
                  <span className="block text-purple-400">WS {formatBytes(proc.mem)}</span>
                  <span className="block text-cyan-400">PB {formatBytes(proc.memPrivate)}</span>
                </span>
              </>
            ) : (
              <span className="text-xs text-slate-700 select-none">—</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
