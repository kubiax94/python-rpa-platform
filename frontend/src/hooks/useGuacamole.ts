"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE, fetchJSON, withAccessToken } from "@/lib/auth";

export interface GuacamoleDisplayProfile {
  mode: "dynamic" | "fixed";
  width?: number | null;
  height?: number | null;
  dpi: number;
}

export type GuacamoleAccessRole = "viewer" | "operator" | "admin";

export type GuacamolePermissionKey = "view" | "interact" | "clipboard" | "upload" | "download" | "recording" | "session_kick";

export interface GuacamoleAccessRule {
  enabled: boolean;
  minimum_role: GuacamoleAccessRole;
  users: string[];
  groups: string[];
}

export interface GuacamoleAccessPolicy {
  permissions: Record<GuacamolePermissionKey, GuacamoleAccessRule>;
  effective_permissions?: Partial<Record<GuacamolePermissionKey, boolean>>;
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
  recording?: {
    enabled: boolean;
    configured: boolean;
    create_path: boolean;
    browse_url?: string;
    path_template?: string;
    name_template?: string;
    exclude_output?: boolean;
    exclude_mouse?: boolean;
    exclude_touch?: boolean;
    include_keys?: boolean;
  };
  websocket_tunnel_url?: string;
  http_tunnel_url?: string;
  notes: string[];
}

export interface GuacamoleSession {
  enabled: boolean;
  configured: boolean;
  status: "ready" | "needs_configuration" | "auth_failed";
  read_only?: boolean;
  access: GuacamoleAccessPolicy;
  agent_id: string;
  source: string;
  connection_id?: string;
  connection_label?: string;
  base_url?: string;
  request_base_url?: string;
  display: GuacamoleDisplayProfile;
  allow_embed: boolean;
  connection_type: string;
  recording?: {
    enabled: boolean;
    configured: boolean;
    create_path: boolean;
    browse_url?: string;
    path_template?: string;
    name_template?: string;
    exclude_output?: boolean;
    exclude_mouse?: boolean;
    exclude_touch?: boolean;
    include_keys?: boolean;
  };
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
  owner?: {
    subject: string;
    username: string;
    display_name: string;
    email: string;
    avatar_url: string;
    avatar_initials: string;
    auth_provider: string;
  } | null;
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

export interface GuacamoleRecordingEntry {
  agent_id: string;
  username: string;
  owner?: {
    subject: string;
    username: string;
    display_name: string;
    email: string;
    avatar_url: string;
    avatar_initials: string;
    auth_provider: string;
  } | null;
  name: string;
  relative_path: string;
  size_bytes?: number | null;
  modified_at?: number | null;
  download_url: string;
}

export interface GuacamoleRecordingsResponse {
  enabled: boolean;
  configured: boolean;
  browse_url?: string;
  entry_count: number;
  entries: GuacamoleRecordingEntry[];
  warnings: string[];
}

export interface GuacamoleVmUserSession {
  session_key: string;
  session_id: number;
  session_name: string;
  username: string;
  status: string;
  type: string;
  process_count: number;
  is_preferred: boolean;
  is_active: boolean;
  is_in_use: boolean;
  in_use_by?: {
    subject: string;
    username: string;
    display_name: string;
    email: string;
    avatar_url: string;
    avatar_initials: string;
    auth_provider: string;
  } | null;
  in_use_by_users?: Array<{
    subject: string;
    username: string;
    display_name: string;
    email: string;
    avatar_url: string;
    avatar_initials: string;
    auth_provider: string;
  }>;
  identity?: {
    subject: string;
    username: string;
    display_name: string;
    email: string;
    avatar_url: string;
    avatar_initials: string;
    auth_provider: string;
  } | null;
  guacamole: {
    group_identifier: string;
    group_name: string;
    connection_id: string;
    connection_name: string;
  };
}

export interface GuacamoleVmUserSessionsResponse {
  agent_id: string;
  sessions: GuacamoleVmUserSession[];
}

export interface GuacamoleKillTrackedSessionsResponse {
  ok: boolean;
  closed_count: number;
}

export interface GuacamoleSessionStatusResponse {
  active: boolean;
  close_reason: string;
}

export interface GuacamoleKickOwnerSessionResponse {
  ok: boolean;
  revoked?: boolean | null;
  detail?: string | null;
  error?: string | null;
}

export async function fetchGuacamoleConfig(): Promise<GuacamoleConfig> {
  return fetchJSON<GuacamoleConfig>(`${API_BASE}/api/guacamole/config`);
}

export async function fetchGuacamoleSession(agentId: string): Promise<GuacamoleSession> {
  return fetchJSON<GuacamoleSession>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole`);
}

export async function fetchGuacamoleVmUserSessions(agentId: string): Promise<GuacamoleVmUserSessionsResponse> {
  return fetchJSON<GuacamoleVmUserSessionsResponse>(`${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole/user-sessions`);
}

export async function createGuacamoleClientSession(
  agentId: string,
  options?: { forceFresh?: boolean; refreshTunnel?: boolean; resumeAuthToken?: string; connectionId?: string; vmUsername?: string; readOnly?: boolean; recorded?: boolean },
): Promise<GuacamoleClientSession> {
  const params = new URLSearchParams();
  if (options?.forceFresh) {
    params.set("force_fresh", "true");
  }
  if (options?.refreshTunnel) {
    params.set("refresh_tunnel", "true");
  }
  if (options?.resumeAuthToken) {
    params.set("resume_auth_token", options.resumeAuthToken);
  }
  if (options?.connectionId) {
    params.set("connection_id", options.connectionId);
  }
  if (options?.vmUsername) {
    params.set("vm_username", options.vmUsername);
  }
  if (options?.readOnly) {
    params.set("read_only", "true");
  }
  if (options?.recorded) {
    params.set("recorded", "true");
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

export async function fetchGuacamoleRecordings(options?: { agentId?: string; username?: string }): Promise<GuacamoleRecordingsResponse> {
  const params = new URLSearchParams();
  if (options?.agentId) {
    params.set("agent_id", options.agentId);
  }
  if (options?.username) {
    params.set("username", options.username);
  }
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return fetchJSON<GuacamoleRecordingsResponse>(`${API_BASE}/api/guacamole/recordings${query}`);
}

export async function killAllTrackedGuacamoleSessions(): Promise<GuacamoleKillTrackedSessionsResponse> {
  return fetchJSON<GuacamoleKillTrackedSessionsResponse>(`${API_BASE}/api/guacamole/tracked-sessions/kill-all`, {
    method: "POST",
  });
}

export async function kickGuacamoleOwnerSession(agentId: string, ownerSubject: string): Promise<GuacamoleKickOwnerSessionResponse> {
  return fetchJSON<GuacamoleKickOwnerSessionResponse>(
    `${API_BASE}/api/agents/${encodeURIComponent(agentId)}/guacamole/tracked-sessions/${encodeURIComponent(ownerSubject)}/kick`,
    { method: "POST" },
  );
}

export async function fetchGuacamoleSessionStatus(authToken: string): Promise<GuacamoleSessionStatusResponse> {
  return fetchJSON<GuacamoleSessionStatusResponse>(`${API_BASE}/api/guacamole/session/${encodeURIComponent(authToken)}/status`);
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

  const createClientSession = useCallback(async (options?: { forceFresh?: boolean; refreshTunnel?: boolean; connectionId?: string; vmUsername?: string; readOnly?: boolean; recorded?: boolean }) => {
    if (!agentId) {
      return null;
    }

    setSessionLoading(true);
    try {
      const nextData = await createGuacamoleClientSession(agentId, options);
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

export function useGuacamoleRecordings(options?: { agentId?: string; username?: string }) {
  const [data, setData] = useState<GuacamoleRecordingsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const agentId = options?.agentId ?? "";
  const username = options?.username ?? "";

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchGuacamoleRecordings({ agentId, username }));
    } catch (error) {
      console.error("[useGuacamoleRecordings] Error:", error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [agentId, username]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { data, loading, refresh, setData };
}

export function useGuacamoleVmUserSessions(agentId: string | null) {
  const [data, setData] = useState<GuacamoleVmUserSessionsResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!agentId) {
      setData(null);
      return;
    }

    setLoading(true);
    try {
      setData(await fetchGuacamoleVmUserSessions(agentId));
    } catch (error) {
      console.error("[useGuacamoleVmUserSessions] Error:", error);
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

    void refresh();
    const intervalId = window.setInterval(() => {
      void refresh();
    }, 5000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [agentId, refresh]);

  return { data, loading, refresh };
}