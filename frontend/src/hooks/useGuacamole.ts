"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.10:8765";

export interface GuacamoleDisplayProfile {
  mode: "dynamic" | "fixed";
  width?: number | null;
  height?: number | null;
  dpi: number;
}

export interface GuacamoleConfig {
  enabled: boolean;
  configured: boolean;
  base_url?: string;
  request_base_url?: string;
  display: GuacamoleDisplayProfile;
  allow_embed: boolean;
  default_connection_mode: string;
  mapping_count: number;
  embed_template_configured: boolean;
  launch_template_configured: boolean;
  auth_username_configured: boolean;
  auth_password_configured: boolean;
  auth_provider: string;
  connection_type: string;
  websocket_tunnel_url?: string;
  http_tunnel_url?: string;
  notes: string[];
}

export interface GuacamoleSession {
  enabled: boolean;
  configured: boolean;
  status: "ready" | "needs_configuration" | "auth_failed";
  agent_id: string;
  source: string;
  connection_id?: string;
  connection_label?: string;
  base_url?: string;
  request_base_url?: string;
  display: GuacamoleDisplayProfile;
  allow_embed: boolean;
  connection_type: string;
  resolved_fields: {
    hostname?: string;
    azure_vm_name?: string;
    public_ip?: string;
    private_ip?: string;
  };
  tunnels: {
    websocket?: string;
    http?: string;
  };
  warnings: string[];
}

export interface GuacamoleClientSession extends GuacamoleSession {
  client_session: null | {
    auth_token: string;
    data_source: string;
    connection_id: string;
    connection_type: string;
    display: GuacamoleDisplayProfile;
    tunnels: {
      websocket?: string;
      http?: string;
    };
  };
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
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
  const [sessionLoading, setSessionLoading] = useState(false);

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

  const createClientSession = useCallback(async () => {
    if (!agentId) {
      return null;
    }

    setSessionLoading(true);
    try {
      const nextData = await fetchJSON<GuacamoleClientSession>(
        `${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole/session`,
        { method: "POST" },
      );
      setData(nextData);
      return nextData;
    } catch (error) {
      console.error("[useGuacamoleSession.createClientSession] Error:", error);
      return null;
    } finally {
      setSessionLoading(false);
    }
  }, [agentId]);

  const revokeClientSession = useCallback(async (authToken: string | null | undefined) => {
    if (!authToken) {
      return;
    }

    try {
      await fetch(`${API_BASE}/api/guacamole/session/${encodeURIComponent(authToken)}`, {
        method: "DELETE",
      });
    } catch (error) {
      console.error("[useGuacamoleSession.revokeClientSession] Error:", error);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, sessionLoading, refresh, createClientSession, revokeClientSession };
}