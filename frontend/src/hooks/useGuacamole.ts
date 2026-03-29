"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, fetchJSON, withAccessToken } from "@/lib/auth";

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
    guacamole_domain?: string;
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
    resume_tunnel_uuid?: string;
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

export interface GuacamoleConnectionSummary {
  data_source: string;
  identifier: string;
  name: string;
  protocol: string;
  parent_identifier: string;
  active_connections?: number | null;
}

export interface GuacamoleConnectionsResponse {
  enabled: boolean;
  configured: boolean;
  base_url?: string;
  default_data_source?: string;
  available_data_sources?: string[];
  connection_count: number;
  connections: GuacamoleConnectionSummary[];
  warnings: string[];
}

export interface GuacamoleTrackedSessionSummary {
  auth_token: string;
  agent_id: string;
  connection_id: string;
  data_source: string;
  created_at: number;
  last_activity_at: number;
  idle_seconds: number;
  tunnel_count: number;
}

export interface GuacamoleTrackedSessionsResponse {
  tracked_count: number;
  idle_timeout_seconds: number;
  sessions: GuacamoleTrackedSessionSummary[];
}

export interface GuacamoleKillTrackedSessionsResponse {
  ok: boolean;
  closed_count: number;
}

export async function fetchGuacamoleConfig(): Promise<GuacamoleConfig> {
  return fetchJSON<GuacamoleConfig>(`${API_BASE}/api/guacamole/config`);
}

export async function fetchGuacamoleSession(agentId: string): Promise<GuacamoleSession> {
  return fetchJSON<GuacamoleSession>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole`);
}

export async function createGuacamoleClientSession(
  agentId: string,
  options?: { forceFresh?: boolean; refreshTunnel?: boolean },
): Promise<GuacamoleClientSession> {
  const params = new URLSearchParams();
  if (options?.forceFresh) {
    params.set("force_fresh", "true");
  }
  if (options?.refreshTunnel) {
    params.set("refresh_tunnel", "true");
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return fetchJSON<GuacamoleClientSession>(
    `${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole/session${query}`,
    { method: "POST" },
  );
}

export async function fetchGuacamoleDiagnostics(agentId: string): Promise<GuacamoleConnectionDiagnostics> {
  return fetchJSON<GuacamoleConnectionDiagnostics>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole/diagnostics`);
}

export async function fetchGuacamoleConnections(): Promise<GuacamoleConnectionsResponse> {
  return fetchJSON<GuacamoleConnectionsResponse>(`${API_BASE}/api/guacamole/connections`);
}

export async function fetchGuacamoleTrackedSessions(): Promise<GuacamoleTrackedSessionsResponse> {
  return fetchJSON<GuacamoleTrackedSessionsResponse>(`${API_BASE}/api/guacamole/tracked-sessions`);
}

export async function killAllTrackedGuacamoleSessions(): Promise<GuacamoleKillTrackedSessionsResponse> {
  return fetchJSON<GuacamoleKillTrackedSessionsResponse>(`${API_BASE}/api/guacamole/tracked-sessions/kill-all`, {
    method: "POST",
  });
}

export async function revokeGuacamoleClientSession(authToken: string, options?: { keepalive?: boolean }): Promise<void> {
  await fetch(withAccessToken(`${API_BASE}/api/guacamole/session/${encodeURIComponent(authToken)}`), {
    method: "DELETE",
    keepalive: options?.keepalive,
  });
}

export function closeGuacamoleClientSessionOnPageUnload(authToken: string, delaySeconds = 5): boolean {
  if (!authToken) {
    return false;
  }

  const closeUrl = withAccessToken(`${API_BASE}/api/guacamole/session/${encodeURIComponent(authToken)}/close?delay_seconds=${encodeURIComponent(String(delaySeconds))}`);
  if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
    return navigator.sendBeacon(closeUrl, new Blob([], { type: "text/plain;charset=UTF-8" }));
  }

  void fetch(closeUrl, {
    method: "POST",
    body: "",
    keepalive: true,
  });
  return true;
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

export function useGuacamoleConnections() {
  const [data, setData] = useState<GuacamoleConnectionsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchGuacamoleConnections());
    } catch (error) {
      console.error("[useGuacamoleConnections] Error:", error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, refresh };
}

export function useGuacamoleTrackedSessions() {
  const [data, setData] = useState<GuacamoleTrackedSessionsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchGuacamoleTrackedSessions());
    } catch (error) {
      console.error("[useGuacamoleTrackedSessions] Error:", error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, refresh, setData };
}