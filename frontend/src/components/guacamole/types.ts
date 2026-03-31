import type { GuacamoleDisplayProfile } from "@/hooks/useGuacamole";

export type PersistedGuacamoleClientSession = {
  authToken: string;
  dataSource: string;
  connectionId: string;
  connectionType: string;
  resumeTunnelUuid?: string;
  display: GuacamoleDisplayProfile;
  tunnels: {
    websocket?: string;
    http?: string;
  };
};

export type WorkspaceConnection = {
  instanceId: string;
  agentId: string;
  title: string;
  readOnly: boolean;
  recorded: boolean;
  requestedConnectionId: string | null;
  requestedVmUsername: string | null;
  status: string;
  error: string | null;
  hint: string | null;
  targetHost: string | null;
  connectionName: string | null;
  connected: boolean;
  minimized: boolean;
  fullscreen: boolean;
  launchedAt: number;
  clientSession: PersistedGuacamoleClientSession | null;
};

export type GuacamoleWorkspaceContextValue = {
  session: WorkspaceConnection | null;
  openSession: (agentId: string, title?: string, options?: { readOnly?: boolean; recorded?: boolean; requestedConnectionId?: string | null; requestedVmUsername?: string | null }) => void;
  resumeSession: () => void;
  minimizeSession: () => void;
  fullscreenSession: () => void;
  exitFullscreenSession: () => void;
  closeSession: () => void;
  isCurrentAgentSession: (agentId: string) => boolean;
};

export type DockedWorkspaceRect = {
  width: number;
  height: number;
  x: number;
  y: number;
};

export type PersistedWorkspaceSession = {
  agentId: string;
  title: string;
  readOnly?: boolean;
  recorded?: boolean;
  requestedConnectionId?: string | null;
  requestedVmUsername?: string | null;
  minimized: boolean;
  fullscreen: boolean;
  launchedAt: number;
  status?: string;
  targetHost?: string | null;
  connectionName?: string | null;
  clientSession?: PersistedGuacamoleClientSession | null;
};

export type PersistedDisplayStateEnvelope = {
  authToken: string;
  resumeTunnelUuid: string;
  savedAt: number;
  state: object;
};