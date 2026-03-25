"use client";

import { useCallback, useEffect, useState } from "react";
import type { AgentState } from "@/types/agent";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.10:8765";

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export function useAgentState(agentId: string | null) {
  const [data, setData] = useState<AgentState | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!agentId) {
      setData(null);
      return;
    }

    setLoading(true);
    try {
      const state = await fetchJSON<AgentState>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}`);
      setData(state);
    } catch (e) {
      console.error("[useAgentState] Error:", e);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    if (!agentId) {
      setData(null);
      return;
    }

    refresh();
    const interval = setInterval(refresh, 2000);
    return () => clearInterval(interval);
  }, [agentId, refresh]);

  return { data, loading, refresh };
}
