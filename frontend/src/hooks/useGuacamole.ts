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
    guacamole_target_host?: string;
    guacamole_group?: string;
    guacamole_connection_name?: string;
    guacamole_username?: string;
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

export interface GuacamoleConnectionDiagnostics extends GuacamoleSession {
  data_source?: string;
  connection: null | {
    identifier?: string;
    name?: string;
    protocol?: string;
    parent_identifier?: string;
    active_connections?: number;
    last_active?: number | null;
    attributes?: Record<string, string>;
  };
  parameters: Record<string, string>;
  analysis: {
    findings: string[];
    positives: string[];
    finding_count: number;
    likely_upstream_bottleneck: boolean;
  };
  timings_ms?: Record<string, number>;
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.json();
}

export async function fetchGuacamoleConfig(): Promise<GuacamoleConfig> {
  return fetchJSON<GuacamoleConfig>(`${API_BASE}/api/guacamole/config`);
}

export async function fetchGuacamoleSession(agentId: string): Promise<GuacamoleSession> {
  return fetchJSON<GuacamoleSession>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole`);
}

export async function createGuacamoleClientSession(agentId: string): Promise<GuacamoleClientSession> {
  return fetchJSON<GuacamoleClientSession>(
    `${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole/session`,
    { method: "POST" },
  );
}

export async function fetchGuacamoleDiagnostics(agentId: string): Promise<GuacamoleConnectionDiagnostics> {
  return fetchJSON<GuacamoleConnectionDiagnostics>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole/diagnostics`);
}

export async function revokeGuacamoleClientSession(authToken: string): Promise<void> {
  await fetch(`${API_BASE}/api/guacamole/session/${encodeURIComponent(authToken)}`, {
    method: "DELETE",
  });
}

export function useGuacamoleConfig() {
  const [data, setData] = useState<GuacamoleConfig | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchGuacamoleConfig());
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
      setData(await fetchGuacamoleSession(agentId));
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
      const nextData = await createGuacamoleClientSession(agentId);
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
      await revokeGuacamoleClientSession(authToken);
    } catch (error) {
      console.error("[useGuacamoleSession.revokeClientSession] Error:", error);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, sessionLoading, refresh, createClientSession, revokeClientSession };
}