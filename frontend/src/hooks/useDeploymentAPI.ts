"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://192.168.1.10:8765";

export interface AgentDeployment {
  id: string;
  agent_id: string;
  hostname: string;
  source_ref: string;
  requested_by: string;
  status: string;
  commit_sha: string;
  artifact_dir: string;
  artifact_exe_path: string;
  bootstrap_path: string;
  install_script_path: string;
  error: string | null;
  build_log: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
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
  source_ref?: string;
  requested_by?: string;
}): Promise<AgentDeployment> {
  return postJSON<AgentDeployment>(`${API_BASE}/api/deployments/prepare`, body);
}

export function useDeployment(deploymentId: string | null) {
  const [data, setData] = useState<AgentDeployment | null>(null);
  const [loading, setLoading] = useState(false);

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

  return { data, loading, refresh };
}