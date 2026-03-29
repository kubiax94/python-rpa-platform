"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { API_BASE, fetchJSON, sendJSON } from "@/lib/auth";
const MAX_RENDERED_TASK_LOG_CHARS = 200_000;

export interface Task {
  id: string;
  pipeline_run_id: string | null;
  step_index: number;
  agent_id: string;
  session: string;
  name: string;
  script: string;
  cwd: string;
  timeout_sec: number;
  config_id: string | null;
  status: string;
  pid: number | null;
  exit_code: number | null;
  error: string | null;
  requested_by: string;
  requested_from: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  kind?: string;
  payload?: Record<string, unknown>;
  components?: Array<{
    type: string;
    config: Record<string, unknown>;
  }>;
}

export interface Pipeline {
  id: string;
  name: string;
  description: string;
  created_by: string;
  created_at: number;
  updated_at: number;
  steps?: PipelineStep[];
}

export interface PipelineStep {
  id: number;
  pipeline_id: string;
  step_index: number;
  name: string;
  script: string;
  cwd: string;
  timeout_sec: number;
  on_fail: string;
  retry_count: number;
}

export interface AuditEntry {
  id: number;
  ts: number;
  entity_type: string;
  entity_id: string;
  action: string;
  actor: string;
  detail: string;
  ip_address: string;
}

export interface TaskLog {
  content: string;
  offset: number;
  size: number;
}

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  return sendJSON<T>(url, "POST", body);
}

// ── Tasks ─────────────────────────────────────────────────────────

export function useTasks(agentId?: string, status?: string) {
  const [data, setData] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (agentId) params.set("agent_id", agentId);
      if (status) params.set("status", status);
      params.set("limit", "100");
      const rows = await fetchJSON<Task[]>(`${API_BASE}/api/tasks?${params}`);
      setData(rows);
    } catch (e) {
      console.error("[useTasks] Error:", e);
    } finally {
      setLoading(false);
    }
  }, [agentId, status]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  return { data, loading, refresh };
}

export async function createTask(body: {
  agent_id: string;
  script: string;
  name?: string;
  cwd?: string;
  timeout_sec?: number;
  session?: string;
}): Promise<Task> {
  return postJSON<Task>(`${API_BASE}/api/tasks`, body);
}

export async function cancelTask(taskId: string): Promise<void> {
  await postJSON(`${API_BASE}/api/tasks/${taskId}/cancel`, {});
}

export function useTaskLog(taskId: string | null) {
  const [log, setLog] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const logSizeRef = useRef(0);

  const refresh = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const offset = logSizeRef.current;
      const result = await fetchJSON<TaskLog>(
        `${API_BASE}/api/tasks/${taskId}/log?offset=${offset}`
      );

      if (offset > result.size) {
        logSizeRef.current = 0;
        const resetResult = await fetchJSON<TaskLog>(`${API_BASE}/api/tasks/${taskId}/log`);
        const nextLog = resetResult.content.slice(-MAX_RENDERED_TASK_LOG_CHARS);
        logSizeRef.current = resetResult.size;
        setTruncated(resetResult.content.length > MAX_RENDERED_TASK_LOG_CHARS);
        setLog(nextLog);
        return;
      }

      logSizeRef.current = result.size;
      if (!result.content) {
        return;
      }

      setLog((current) => {
        const nextLog = `${current}${result.content}`;
        const croppedLog = nextLog.slice(-MAX_RENDERED_TASK_LOG_CHARS);
        setTruncated(croppedLog.length < nextLog.length);
        return croppedLog;
      });
    } catch (e) {
      console.error("[useTaskLog] Error:", e);
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    if (!taskId) {
      setLog("");
      setTruncated(false);
      logSizeRef.current = 0;
      return;
    }
    setLog("");
    setTruncated(false);
    logSizeRef.current = 0;
    refresh();
    const interval = setInterval(refresh, 2000);
    return () => clearInterval(interval);
  }, [taskId, refresh]);

  return { log, loading, refresh, truncated };
}

// ── Pipelines ─────────────────────────────────────────────────────

export function usePipelines() {
  const [data, setData] = useState<Pipeline[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await fetchJSON<Pipeline[]>(`${API_BASE}/api/pipelines`);
      setData(rows);
    } catch (e) {
      console.error("[usePipelines] Error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { data, loading, refresh };
}

export async function createPipeline(body: {
  name: string;
  description?: string;
  steps: { step_index: number; name: string; script: string; timeout_sec?: number; on_fail?: string }[];
}): Promise<Pipeline> {
  return postJSON<Pipeline>(`${API_BASE}/api/pipelines`, body);
}

export async function runPipeline(
  pipelineId: string,
  body: { agent_id: string; session?: string }
): Promise<{ run_id: string; task_id: string; sent: boolean }> {
  return postJSON(`${API_BASE}/api/pipelines/${pipelineId}/run`, body);
}
