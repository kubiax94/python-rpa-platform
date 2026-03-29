"use client";

import { useCallback, useEffect, useState } from "react";
import type { AgentState } from "@/types/agent";
import { API_BASE, fetchJSON } from "@/lib/auth";

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
