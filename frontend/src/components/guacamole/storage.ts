import type {
  DockedWorkspaceRect,
  PersistedDisplayStateEnvelope,
  PersistedWorkspaceSession,
  WorkspaceConnection,
} from "@/components/guacamole/types";
import { createPersistedInstanceId } from "@/components/guacamole/utils";

export const DOCKED_WORKSPACE_STORAGE_KEY = "my-orciestra.guacamole.workspace.v1";
export const ACTIVE_SESSION_STORAGE_KEY = "my-orciestra.guacamole.session.v1";
export const ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY = "my-orciestra.guacamole.session.display-state.v1";
export const DEFAULT_DOCKED_WORKSPACE_RECT: DockedWorkspaceRect = { width: 1120, height: 620, x: 24, y: 24 };

let dockedWorkspaceRectSnapshotCache: {
  raw: string | null;
  value: DockedWorkspaceRect;
} = {
  raw: null,
  value: DEFAULT_DOCKED_WORKSPACE_RECT,
};

let persistedWorkspaceSessionSnapshotCache: {
  raw: string | null;
  value: WorkspaceConnection | null;
} = {
  raw: null,
  value: null,
};

function debugWorkspaceStorage(event: string, details: Record<string, unknown>): void {
  if (typeof window === "undefined") {
    return;
  }

  console.info("[GuacamoleStorage]", event, details);
}

export function getDefaultDockedWorkspaceRect(): DockedWorkspaceRect {
  return DEFAULT_DOCKED_WORKSPACE_RECT;
}

export function loadDockedWorkspaceRect(): DockedWorkspaceRect {
  if (typeof window === "undefined") {
    return getDefaultDockedWorkspaceRect();
  }

  const raw = window.localStorage.getItem(DOCKED_WORKSPACE_STORAGE_KEY);
  if (raw === dockedWorkspaceRectSnapshotCache.raw) {
    return dockedWorkspaceRectSnapshotCache.value;
  }

  try {
    if (!raw) {
      dockedWorkspaceRectSnapshotCache = {
        raw: null,
        value: DEFAULT_DOCKED_WORKSPACE_RECT,
      };
      return dockedWorkspaceRectSnapshotCache.value;
    }

    const parsed = JSON.parse(raw) as Partial<DockedWorkspaceRect>;
    if (
      typeof parsed.width !== "number"
      || typeof parsed.height !== "number"
      || typeof parsed.x !== "number"
      || typeof parsed.y !== "number"
    ) {
      dockedWorkspaceRectSnapshotCache = {
        raw,
        value: DEFAULT_DOCKED_WORKSPACE_RECT,
      };
      return dockedWorkspaceRectSnapshotCache.value;
    }

    dockedWorkspaceRectSnapshotCache = {
      raw,
      value: {
        width: parsed.width,
        height: parsed.height,
        x: parsed.x,
        y: parsed.y,
      },
    };
    return dockedWorkspaceRectSnapshotCache.value;
  } catch {
    dockedWorkspaceRectSnapshotCache = {
      raw,
      value: DEFAULT_DOCKED_WORKSPACE_RECT,
    };
    return dockedWorkspaceRectSnapshotCache.value;
  }
}

export function subscribeToWorkspaceStorage(onStoreChange: () => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }

  const handleStorage = (event: StorageEvent) => {
    if (!event.key || event.key === DOCKED_WORKSPACE_STORAGE_KEY || event.key === ACTIVE_SESSION_STORAGE_KEY) {
      onStoreChange();
    }
  };

  window.addEventListener("storage", handleStorage);
  return () => {
    window.removeEventListener("storage", handleStorage);
  };
}

export function loadPersistedWorkspaceSession(): WorkspaceConnection | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.sessionStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  if (raw === persistedWorkspaceSessionSnapshotCache.raw) {
    return persistedWorkspaceSessionSnapshotCache.value;
  }

  try {
    if (!raw) {
      persistedWorkspaceSessionSnapshotCache = {
        raw: null,
        value: null,
      };
      return null;
    }

    const parsed = JSON.parse(raw) as Partial<PersistedWorkspaceSession>;
    const parsedClientSession = parsed.clientSession;
    const hydratedClientSession = (
      parsedClientSession
      && typeof parsedClientSession.authToken === "string"
      && typeof parsedClientSession.dataSource === "string"
      && typeof parsedClientSession.connectionId === "string"
      && typeof parsedClientSession.connectionType === "string"
      && typeof parsedClientSession.display === "object"
      && parsedClientSession.display !== null
      && typeof parsedClientSession.tunnels === "object"
      && parsedClientSession.tunnels !== null
    )
      ? {
          authToken: parsedClientSession.authToken,
          dataSource: parsedClientSession.dataSource,
          connectionId: parsedClientSession.connectionId,
          connectionType: parsedClientSession.connectionType,
          resumeTunnelUuid: typeof parsedClientSession.resumeTunnelUuid === "string" ? parsedClientSession.resumeTunnelUuid : undefined,
          display: parsedClientSession.display,
          tunnels: {
            websocket: typeof parsedClientSession.tunnels.websocket === "string" ? parsedClientSession.tunnels.websocket : undefined,
            http: typeof parsedClientSession.tunnels.http === "string" ? parsedClientSession.tunnels.http : undefined,
          },
        }
      : null;

    if (
      typeof parsed.agentId !== "string"
      || !parsed.agentId.trim()
      || typeof parsed.title !== "string"
      || typeof parsed.minimized !== "boolean"
      || typeof parsed.fullscreen !== "boolean"
      || typeof parsed.launchedAt !== "number"
    ) {
      persistedWorkspaceSessionSnapshotCache = {
        raw,
        value: null,
      };
      return null;
    }

    persistedWorkspaceSessionSnapshotCache = {
      raw,
      value: {
        instanceId: createPersistedInstanceId(parsed.agentId, parsed.launchedAt),
        agentId: parsed.agentId,
        title: parsed.title,
        readOnly: parsed.readOnly === true,
        recorded: parsed.recorded === true,
        accessPolicy: typeof parsed.accessPolicy === "object" && parsed.accessPolicy !== null ? parsed.accessPolicy as WorkspaceConnection["accessPolicy"] : null,
        requestedConnectionId: typeof parsed.requestedConnectionId === "string" && parsed.requestedConnectionId.trim() ? parsed.requestedConnectionId : null,
        requestedVmUsername: typeof parsed.requestedVmUsername === "string" && parsed.requestedVmUsername.trim() ? parsed.requestedVmUsername : null,
        status: hydratedClientSession ? "resuming" : typeof parsed.status === "string" && parsed.status.trim() ? parsed.status : "queued",
        error: null,
        hint: null,
        targetHost: typeof parsed.targetHost === "string" && parsed.targetHost.trim() ? parsed.targetHost : null,
        connectionName: typeof parsed.connectionName === "string" && parsed.connectionName.trim() ? parsed.connectionName : null,
        connected: false,
        minimized: parsed.minimized,
        fullscreen: parsed.fullscreen,
        launchedAt: parsed.launchedAt,
        clientSession: hydratedClientSession,
      },
    };
    debugWorkspaceStorage("load-session", {
      agentId: parsed.agentId,
      status: persistedWorkspaceSessionSnapshotCache.value?.status,
      hasClientSession: Boolean(hydratedClientSession),
      source: hydratedClientSession ? "storage-reuse-candidate" : "storage-no-client-session",
    });
    return persistedWorkspaceSessionSnapshotCache.value;
  } catch {
    persistedWorkspaceSessionSnapshotCache = {
      raw,
      value: null,
    };
    return null;
  }
}

export function persistWorkspaceSession(session: WorkspaceConnection | null): void {
  if (typeof window === "undefined") {
    return;
  }

  if (!session) {
    window.sessionStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    window.sessionStorage.removeItem(ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY);
    persistedWorkspaceSessionSnapshotCache = {
      raw: null,
      value: null,
    };
    return;
  }

  const payload: PersistedWorkspaceSession = {
    agentId: session.agentId,
    title: session.title,
    readOnly: session.readOnly,
    recorded: session.recorded,
    accessPolicy: session.accessPolicy,
    requestedConnectionId: session.requestedConnectionId,
    requestedVmUsername: session.requestedVmUsername,
    minimized: session.minimized,
    fullscreen: session.fullscreen,
    launchedAt: session.launchedAt,
    status: session.status,
    targetHost: session.targetHost,
    connectionName: session.connectionName,
    clientSession: session.clientSession,
  };
  const raw = JSON.stringify(payload);
  persistedWorkspaceSessionSnapshotCache = {
    raw,
    value: {
      instanceId: createPersistedInstanceId(payload.agentId, payload.launchedAt),
      agentId: payload.agentId,
      title: payload.title,
      readOnly: payload.readOnly === true,
      recorded: payload.recorded === true,
      accessPolicy: payload.accessPolicy || null,
      requestedConnectionId: payload.requestedConnectionId || null,
      requestedVmUsername: payload.requestedVmUsername || null,
      status: payload.status || session.status,
      error: null,
      hint: null,
      targetHost: payload.targetHost || null,
      connectionName: payload.connectionName || null,
      connected: false,
      minimized: payload.minimized,
      fullscreen: payload.fullscreen,
      launchedAt: payload.launchedAt,
      clientSession: payload.clientSession || null,
    },
  };
  window.sessionStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, raw);
  debugWorkspaceStorage("persist-session", {
    agentId: payload.agentId,
    status: payload.status,
    hasClientSession: Boolean(payload.clientSession),
    authToken: payload.clientSession?.authToken ? `${payload.clientSession.authToken.slice(0, 6)}...${payload.clientSession.authToken.slice(-6)}` : "<none>",
  });
}

export function clearPersistedWorkspaceSession(): void {
  persistWorkspaceSession(null);
}

export function loadPersistedDisplayState(authToken: string, resumeTunnelUuid: string): object | null {
  if (typeof window === "undefined" || !authToken || !resumeTunnelUuid) {
    return null;
  }

  try {
    const raw = window.sessionStorage.getItem(ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as Partial<PersistedDisplayStateEnvelope>;
    if (
      parsed.authToken !== authToken
      || parsed.resumeTunnelUuid !== resumeTunnelUuid
      || !parsed.state
      || typeof parsed.state !== "object"
    ) {
      return null;
    }

    return parsed.state as object;
  } catch {
    return null;
  }
}

export function persistDisplayState(authToken: string, resumeTunnelUuid: string, state: object): boolean {
  if (typeof window === "undefined" || !authToken || !resumeTunnelUuid) {
    return false;
  }

  try {
    const payload: PersistedDisplayStateEnvelope = {
      authToken,
      resumeTunnelUuid,
      savedAt: Date.now(),
      state,
    };
    window.sessionStorage.setItem(ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY, JSON.stringify(payload));
    return true;
  } catch {
    window.sessionStorage.removeItem(ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY);
    return false;
  }
}

export function clearPersistedDisplayState(authToken?: string | null, resumeTunnelUuid?: string | null): void {
  if (typeof window === "undefined") {
    return;
  }

  if (!authToken || !resumeTunnelUuid) {
    window.sessionStorage.removeItem(ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY);
    return;
  }

  try {
    const raw = window.sessionStorage.getItem(ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY);
    if (!raw) {
      return;
    }

    const parsed = JSON.parse(raw) as Partial<PersistedDisplayStateEnvelope>;
    if (parsed.authToken === authToken && parsed.resumeTunnelUuid === resumeTunnelUuid) {
      window.sessionStorage.removeItem(ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY);
    }
  } catch {
    window.sessionStorage.removeItem(ACTIVE_SESSION_DISPLAY_STATE_STORAGE_KEY);
  }
}