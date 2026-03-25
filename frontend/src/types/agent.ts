export interface ProcessWindowReplica {
  hwnd: number;
  window_title?: string;
  window_class?: string;
  window_kind?: string;
  width?: number;
  height?: number;
  is_primary?: boolean;
}

export interface ProcessReplica {
  pid: number;
  task_id?: string;
  exe: string;
  exe_path: string;
  args: string;
  cmd: string;
  cwd: string;
  user: string;
  ppid?: number;
  sessionid?: number;
  creation_time?: number;
  is_monitored?: boolean;
  is_running?: boolean;
  exit_code?: number | null;
  cpu_usage?: number;
  memory_usage?: {
    working_set_size?: number;
    private_bytes?: number;
  };
  handle_count?: number;
  has_window?: boolean | null;
  window_title?: string;
  window_hwnd?: number | null;
  windows?: ProcessWindowReplica[];
  capture_target_pid?: number | null;
  capture_target_kind?: string;
  io_counters?: {
    read_bytes?: number;
    write_bytes?: number;
    other_bytes?: number;
    read_bps?: number;
    write_bps?: number;
    other_bps?: number;
  };
}

export interface SessionReplica {
  session_id?: number;
  session_name?: string;
  username?: string;
  status?: string;
  type?: string;
  process_count?: number;
  processes: Record<string, ProcessReplica>;
}

export interface AgentMetrics {
  cpu_usage?: number;
}

export interface AgentMeta {
  cpu_usage?: number;
  hostname?: string;
  os_name?: string;
  os_version?: string;
  os_build?: string;
  cpu_model?: string;
  logical_cores?: number;
  total_ram_bytes?: number;
  uptime_seconds?: number;
  system_drive?: string;
  disk_total_bytes?: number;
  disk_free_bytes?: number;
  disk_read_bps?: number;
  disk_write_bps?: number;
  network_recv_bps?: number;
  network_sent_bps?: number;
  is_azure?: boolean;
  azure_vm_name?: string;
  azure_vm_size?: string;
  azure_location?: string;
  azure_resource_group?: string;
  azure_subscription_id?: string;
  azure_zone?: string;
  azure_offer?: string;
  azure_sku?: string;
  azure_private_ip?: string;
  azure_public_ip?: string;
  maintenance_state?: string;
  maintenance_event_type?: string;
  maintenance_not_before?: string;
  maintenance_summary?: string;
}

export interface AgentConnectionMeta {
  connected?: boolean;
  last_seen?: number;
}

export interface AgentState {
  __agent_metrics?: AgentMeta;
  __agent_connection?: AgentConnectionMeta;
  [sessionKey: string]: SessionReplica | AgentMeta | AgentConnectionMeta | undefined;
}

export interface AgentsMap {
  [agentId: string]: AgentState;
}

export interface CommandPayload {
  type: string;
  data: Record<string, unknown>;
}

export function isSessionReplica(value: SessionReplica | AgentMeta | AgentConnectionMeta | undefined): value is SessionReplica {
  return Boolean(value && typeof value === "object" && "processes" in value);
}

export function getAgentSessions(state: AgentState): Array<[string, SessionReplica]> {
  return Object.entries(state).filter(
    ([key, value]) => !key.startsWith("__") && isSessionReplica(value)
  ) as Array<[string, SessionReplica]>;
}

export function getAgentMetrics(state: AgentState): AgentMeta | undefined {
  return state.__agent_metrics;
}

export function getAgentConnection(state: AgentState): AgentConnectionMeta | undefined {
  return state.__agent_connection;
}

export function isAgentOnline(state: AgentState): boolean {
  return state.__agent_connection?.connected === true;
}

export function getSessionProcessCount(session: SessionReplica): number {
  const processEntries = Object.keys(session.processes || {});
  if (processEntries.length > 0) {
    return processEntries.length;
  }

  return session.process_count ?? 0;
}
