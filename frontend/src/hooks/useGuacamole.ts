"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.10:8765";

export interface GuacamoleConfig {
  enabled: boolean;
  configured: boolean;
  base_url?: string;
  allow_embed: boolean;
  default_connection_mode: string;
  mapping_count: number;
  embed_template_configured: boolean;
  launch_template_configured: boolean;
  notes: string[];
}

export interface GuacamoleSession {
  enabled: boolean;
  configured: boolean;
  status: "ready" | "needs_configuration";
  agent_id: string;
  source: string;
  connection_id?: string;
  connection_label?: string;
  base_url?: string;
  embed_url?: string;
  launch_url?: string;
  allow_embed: boolean;
  resolved_fields: {
    hostname?: string;
    azure_vm_name?: string;
    public_ip?: string;
    private_ip?: string;
  };
  warnings: string[];
}

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export function useGuacamoleConfig() {
  const [data, setData] = useState<GuacamoleConfig | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchJSON<GuacamoleConfig>(`${API_BASE}/api/guacamole/config`));
    } catch (error) {
      console.error("[useGuacamoleConfig] Error:", error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, refresh };
}

export function useGuacamoleSession(agentId: string | null) {
  const [data, setData] = useState<GuacamoleSession | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!agentId) {
      setData(null);
      return;
    }

    setLoading(true);
    try {
      setData(await fetchJSON<GuacamoleSession>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole`));
    } catch (error) {
      console.error("[useGuacamoleSession] Error:", error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, refresh };
}