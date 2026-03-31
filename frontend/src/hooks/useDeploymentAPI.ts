"use client";

import { useCallback, useEffect, useState } from "react";
import { useTaskLog } from "@/hooks/useTaskAPI";
import { API_BASE, fetchJSON, sendJSON, withAccessToken } from "@/lib/auth";

export interface AgentDeployment {
  id: string;
  agent_id: string;
  hostname: string;
  repo_url: string;
  source_ref: string;
  requested_by: string;
  status: string;
  task_id: string | null;
  commit_sha: string;
  artifact_dir: string;
  artifact_exe_path: string;
  package_zip_path: string;
  bootstrap_path: string;
  install_script_path: string;
  installer_copy_path: string;
  error: string | null;
  build_log: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
}

export interface DeploymentProvisioningEntity {
  action: string;
  identifier: string;
  name: string;
}

export interface DeploymentProvisioningDiagnostics {
  available: boolean;
  deployment_id: string;
  agent_id: string;
  hostname: string;
  data_source: string;
  detail: string | null;
  group: DeploymentProvisioningEntity;
  connection: DeploymentProvisioningEntity;
}

export interface DeploymentConfig {
  default_repo_url: string;
  default_source_ref: string;
  artifact_share_root: string;
  latest_installer_share_template: string;
  active_deployment: AgentDeployment | null;
}

export interface DeploymentDefaultsSettings {
  default_repo_url: string;
  default_source_ref: string;
  artifact_share_root: string;
  latest_installer_share_template: string;
}

export interface ServerSettings {
  deployment: DeploymentDefaultsSettings;
  identity: {
    provider: string;
    provider_locked: boolean;
    local_bootstrap_available: boolean;
    session_ttl_seconds: number;
    azure: {
      tenant_id: string;
      client_id: string;
      authority_url: string;
      redirect_path: string;
      scopes: string[];
      client_secret_configured: boolean;
      activated_at?: number | null;
      active: boolean;
      group_role_mappings: Array<{
        group_object_id: string;
        group_name: string;
        app_roles: string[];
      }>;
    };
  };
  guacamole: {
    display: {
      mode: "dynamic" | "fixed";
      width?: number | null;
      height?: number | null;
      dpi: number;
    };
    recording: {
      enabled: boolean;
      browse_url: string;
      path_template: string;
      name_template: string;
      create_path: boolean;
      exclude_output: boolean;
      exclude_mouse: boolean;
      exclude_touch: boolean;
      include_keys: boolean;
    };
  };
}

export interface IdentitySettingsUpdate {
  session_ttl_seconds?: number;
  azure?: {
    tenant_id?: string;
    client_id?: string;
    authority_url?: string;
    scopes?: string[];
    client_secret?: string;
    activate?: boolean;
    group_role_mappings?: Array<{
      group_object_id: string;
      group_name: string;
      app_roles: string[];
    }>;
  };
}

export interface ServerSettingsUpdate {
  deployment?: Partial<DeploymentDefaultsSettings>;
  identity?: IdentitySettingsUpdate;
  guacamole?: {
    display?: {
      mode?: "dynamic" | "fixed";
      width?: number | null;
      height?: number | null;
      dpi?: number;
    };
    recording?: {
      enabled?: boolean;
      browse_url?: string;
      path_template?: string;
      name_template?: string;
      create_path?: boolean;
      exclude_output?: boolean;
      exclude_mouse?: boolean;
      exclude_touch?: boolean;
      include_keys?: boolean;
    };
  };
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  return sendJSON<T>(url, "POST", body);
}

async function patchJSON<T>(url: string, body: unknown): Promise<T> {
  return sendJSON<T>(url, "PATCH", body);
}

export async function prepareDeployment(body: {
  agent_id?: string;
  hostname: string;
  display_name?: string;
  guacamole_target_host?: string;
  guacamole_username?: string;
  guacamole_domain?: string;
  guacamole_password?: string;
  guacamole_secret?: string;
  guacamole_group_name?: string;
  guacamole_connection_name?: string;
  repo_url?: string;
  source_ref?: string;
  requested_by?: string;
}): Promise<AgentDeployment> {
  return postJSON<AgentDeployment>(`${API_BASE}/api/deployments/prepare`, body);
}

export async function fetchServerSettings(): Promise<ServerSettings> {
  return fetchJSON<ServerSettings>(`${API_BASE}/api/settings/server`);
}

export async function updateServerSettings(body: ServerSettingsUpdate): Promise<ServerSettings> {
  return patchJSON<ServerSettings>(`${API_BASE}/api/settings/server`, body);
}

export function getDeploymentInstallerUrl(deploymentId: string): string {
  return withAccessToken(`${API_BASE}/api/deployments/${encodeURIComponent(deploymentId)}/installer`);
}

export function getDeploymentPackageUrl(deploymentId: string): string {
  return withAccessToken(`${API_BASE}/api/deployments/${encodeURIComponent(deploymentId)}/package`);
}

export function buildLocalInstallCommand(deployment: AgentDeployment): string {
  const localPackagePath = "C:\\path\\to\\extracted-package";
  const localInstallerPath = `${localPackagePath}\\install.ps1`;
  const commandParts = [
    "powershell",
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    `\"${localInstallerPath}\"`,
    "-PackagePath",
    `\"${localPackagePath}\"`,
    "-ArtifactId",
    `\"${deployment.id}\"`,
  ];
  return commandParts.join(" ");
}

export function useDeployments(agentId?: string | null, limit = 100) {
  const [data, setData] = useState<AgentDeployment[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (agentId) params.set("agent_id", agentId);
      params.set("limit", String(limit));
      setData(await fetchJSON<AgentDeployment[]>(`${API_BASE}/api/deployments?${params}`));
    } catch (error) {
      console.error("[useDeployments] Error:", error);
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [agentId, limit]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  return { data, loading, refresh };
}

export function useDeploymentConfig() {
  const [data, setData] = useState<DeploymentConfig | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchJSON<DeploymentConfig>(`${API_BASE}/api/deployments/config`));
    } catch (error) {
      console.error("[useDeploymentConfig] Error:", error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [refresh]);

  return { data, loading, refresh };
}

export function useServerSettings() {
  const [data, setData] = useState<ServerSettings | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setData(await fetchServerSettings());
    } catch (error) {
      console.error("[useServerSettings] Error:", error);
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

export function useDeployment(deploymentId: string | null) {
  const [data, setData] = useState<AgentDeployment | null>(null);
  const [loading, setLoading] = useState(false);
  const taskLog = useTaskLog(data?.task_id ?? null);

  const refresh = useCallback(async () => {
    if (!deploymentId) {
      setData(null);
      return;
    }

    setLoading(true);
    try {
      const deployment = await fetchJSON<AgentDeployment>(`${API_BASE}/api/deployments/${encodeURIComponent(deploymentId)}`);
      setData(deployment);
    } catch (error) {
      console.error("[useDeployment] Error:", error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [deploymentId]);

  useEffect(() => {
    if (!deploymentId) {
      setData(null);
      return;
    }

    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [deploymentId, refresh]);

  return { data, loading, refresh, taskLog };
}

export function useDeploymentProvisioning(deploymentId: string | null) {
  const [data, setData] = useState<DeploymentProvisioningDiagnostics | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!deploymentId) {
      setData(null);
      return;
    }

    setLoading(true);
    try {
      const diagnostics = await fetchJSON<DeploymentProvisioningDiagnostics>(
        `${API_BASE}/api/deployments/${encodeURIComponent(deploymentId)}/guacamole/provisioning`,
      );
      setData(diagnostics);
    } catch (error) {
      console.error("[useDeploymentProvisioning] Error:", error);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [deploymentId]);

  useEffect(() => {
    if (!deploymentId) {
      setData(null);
      return;
    }

    refresh();
    const interval = setInterval(refresh, 3000);
    return () => clearInterval(interval);
  }, [deploymentId, refresh]);

  return { data, loading, refresh };
}