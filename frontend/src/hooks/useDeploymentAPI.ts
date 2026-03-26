"use client";

import { useCallback, useEffect, useState } from "react";
import { useTaskLog } from "@/hooks/useTaskAPI";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.10:8765";

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
  bootstrap_path: string;
  install_script_path: string;
  installer_copy_path: string;
  error: string | null;
  build_log: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
}

export interface DeploymentConfig {
  default_repo_url: string;
  default_source_ref: string;
  artifact_share_root: string;
  latest_installer_share_template: string;
  active_deployment: AgentDeployment | null;
}

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function prepareDeployment(body: {
  agent_id?: string;
  hostname: string;
  display_name?: string;
  repo_url?: string;
  source_ref?: string;
  requested_by?: string;
}): Promise<AgentDeployment> {
  return postJSON<AgentDeployment>(`${API_BASE}/api/deployments/prepare`, body);
}

export function getDeploymentInstallerUrl(deploymentId: string): string {
  return `${API_BASE}/api/deployments/${encodeURIComponent(deploymentId)}/installer`;
}

export function buildInstallCommand(deployment: AgentDeployment, config: DeploymentConfig | null): string {
  const installerTemplate = config?.latest_installer_share_template || "";
  const installerPath = installerTemplate
    ? installerTemplate.replace("{deployment_id}", deployment.id)
    : deployment.installer_copy_path || deployment.install_script_path;
  const commandParts = [
    "powershell",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    `\"${installerPath}\"`,
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