"use client";

import { useState, useEffect, useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.10:8765";

export interface MetricRow {
  ts: number;
  agent_id: string;
  session_id: number | null;
  pid: number;
  exe: string;
  cpu_avg: number;
  cpu_max: number;
  mem_ws: number;
  mem_pb: number;
  handles: number;
  io_read_bps: number;
  io_write_bps: number;
}

export interface EventRow {
  id: number;
  ts: number;
  agent_id: string;
  session_id: number | null;
  pid: number | null;
  type: string;
  exe: string | null;
  detail: string | null;
}

export interface AgentSummary {
  agent_id: string;
  process_count: number;
  avg_cpu: number;
  total_mem_ws: number;
  last_seen: number;
}

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function useMetrics(agentId: string, pid?: number, rangeMinutes: number = 60) {
  const [data, setData] = useState<MetricRow[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const now = Math.floor(Date.now() / 1000);
      const from = now - rangeMinutes * 60;
      let url = `${API_BASE}/api/metrics?agent_id=${encodeURIComponent(agentId)}&from_ts=${from}&to_ts=${now}&limit=50000`;
      if (pid) url += `&pid=${pid}`;
      const rows = await fetchJSON<MetricRow[]>(url);
      setData(rows);
    } catch (e) {
      console.error("[useMetrics] Error:", e);
    } finally {
      setLoading(false);
    }
  }, [agentId, pid, rangeMinutes]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 60_000); // auto-refresh every 60s
    return () => clearInterval(interval);
  }, [refresh]);

  return { data, loading, refresh };
}

export function useEvents(agentId?: string, eventType?: string, limit: number = 100) {
  const [data, setData] = useState<EventRow[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (agentId) params.set("agent_id", agentId);
      if (eventType) params.set("event_type", eventType);
      params.set("limit", String(limit));
      const rows = await fetchJSON<EventRow[]>(`${API_BASE}/api/events?${params}`);
      setData(rows);
    } catch (e) {
      console.error("[useEvents] Error:", e);
    } finally {
      setLoading(false);
    }
  }, [agentId, eventType, limit]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 30_000); // refresh every 30s
    return () => clearInterval(interval);
  }, [refresh]);

  return { data, loading, refresh };
}
