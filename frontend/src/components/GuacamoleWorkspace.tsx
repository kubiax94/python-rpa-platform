"use client";

import {
  useCallback,
  createContext,
  useContext,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  useSyncExternalStore,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import Guacamole from "guacamole-common-js";
import {
  createGuacamoleClientSession,
  fetchGuacamoleDiagnostics,
  revokeGuacamoleClientSession,
  type GuacamoleConnectionDiagnostics,
  type GuacamoleClientSession,
  type GuacamoleDisplayProfile,
} from "@/hooks/useGuacamole";

type PersistedGuacamoleClientSession = {
  authToken: string;
  dataSource: string;
  connectionId: string;
  connectionType: string;
  display: GuacamoleDisplayProfile;
  tunnels: {
    websocket?: string;
    http?: string;
  };
};

type WorkspaceConnection = {
  instanceId: string;
  agentId: string;
  title: string;
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

type GuacamoleWorkspaceContextValue = {
  session: WorkspaceConnection | null;
  openSession: (agentId: string, title?: string) => void;
  resumeSession: () => void;
  minimizeSession: () => void;
  fullscreenSession: () => void;
  closeSession: () => void;
  isCurrentAgentSession: (agentId: string) => boolean;
};

const GuacamoleWorkspaceContext = createContext<GuacamoleWorkspaceContextValue | null>(null);

const DOCKED_WORKSPACE_STORAGE_KEY = "my-orciestra.guacamole.workspace.v1";
const ACTIVE_SESSION_STORAGE_KEY = "my-orciestra.guacamole.session.v1";
const DEFAULT_DOCKED_WORKSPACE_RECT: DockedWorkspaceRect = { width: 1120, height: 620, x: 24, y: 24 };

type DockedWorkspaceRect = {
  width: number;
  height: number;
  x: number;
  y: number;
};

type PersistedWorkspaceSession = {
  agentId: string;
  title: string;
  minimized: boolean;
  fullscreen: boolean;
  launchedAt: number;
  status?: string;
  targetHost?: string | null;
  connectionName?: string | null;
  clientSession?: PersistedGuacamoleClientSession | null;
};

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

function getDefaultDockedWorkspaceRect(): DockedWorkspaceRect {
  return DEFAULT_DOCKED_WORKSPACE_RECT;
}

function createPersistedInstanceId(agentId: string, launchedAt: number): string {
  return `${agentId}:${launchedAt}`;
}

function buildWorkspaceHint(
  diagnostics: GuacamoleConnectionDiagnostics | null,
  fallbackTargetHost: string | null,
): string | null {
  const targetHost = diagnostics?.resolved_fields?.guacamole_target_host
    || diagnostics?.resolved_fields?.hostname
    || fallbackTargetHost
    || "the configured RDP target";
  const warnings = diagnostics?.warnings || [];
  const findings = diagnostics?.analysis?.findings || [];

  if (diagnostics?.connection || diagnostics?.connection_id) {
    const detail = warnings[0] || findings[0];
    return detail
      ? `The Guacamole bridge is responding, but the upstream RDP session to ${targetHost} is failing or unstable. ${detail}`
      : `The Guacamole bridge is responding, but the upstream RDP session to ${targetHost} is failing or unstable.`;
  }

  if (warnings[0]) {
    return warnings[0];
  }

  return fallbackTargetHost
    ? `Guacamole could not keep the remote desktop stream alive for ${fallbackTargetHost}.`
    : null;
}

function loadDockedWorkspaceRect(): DockedWorkspaceRect {
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

function subscribeToWorkspaceStorage(onStoreChange: () => void): () => void {
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

function loadPersistedWorkspaceSession(): WorkspaceConnection | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
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
        status: typeof parsed.status === "string" && parsed.status.trim() ? parsed.status : "queued",
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
    return persistedWorkspaceSessionSnapshotCache.value;
  } catch {
    persistedWorkspaceSessionSnapshotCache = {
      raw,
      value: null,
    };
    return null;
  }
}

function persistWorkspaceSession(session: WorkspaceConnection | null): void {
  if (typeof window === "undefined") {
    return;
  }

  if (!session) {
    window.localStorage.removeItem(ACTIVE_SESSION_STORAGE_KEY);
    persistedWorkspaceSessionSnapshotCache = {
      raw: null,
      value: null,
    };
    return;
  }

  const payload: PersistedWorkspaceSession = {
    agentId: session.agentId,
    title: session.title,
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
  window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, raw);
}

function createInstanceId(agentId: string) {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${agentId}:${crypto.randomUUID()}`;
  }
  return `${agentId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

function GuacamoleViewport({
  session,
  active,
  onUpdate,
}: {
  session: WorkspaceConnection;
  active: boolean;
  onUpdate: (patch: Partial<WorkspaceConnection>) => void;
}) {
  const displayHostRef = useRef<HTMLDivElement | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const connectGenerationRef = useRef(0);
  const authTokenRef = useRef<string | null>(null);
  const activeRef = useRef(active);
  const hasConnectedRef = useRef(false);
  const diagnosticsRefreshAtRef = useRef(0);
  const pageUnloadingRef = useRef(false);
  const sendResizeRef = useRef<() => void>(() => undefined);
  const clientRef = useRef<InstanceType<typeof Guacamole.Client> | null>(null);
  const tunnelRef = useRef<InstanceType<typeof Guacamole.HTTPTunnel> | InstanceType<typeof Guacamole.WebSocketTunnel> | InstanceType<typeof Guacamole.ChainedTunnel> | null>(null);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    const markPageUnloading = () => {
      pageUnloadingRef.current = true;
    };

    window.addEventListener("beforeunload", markPageUnloading);
    window.addEventListener("pagehide", markPageUnloading);
    return () => {
      window.removeEventListener("beforeunload", markPageUnloading);
      window.removeEventListener("pagehide", markPageUnloading);
    };
  }, []);

  const getDisplayProfile = (clientSession: NonNullable<GuacamoleClientSession["client_session"]>) => {
    const profile = clientSession.display;
    if (profile.mode === "fixed" && profile.width && profile.height) {
      return {
        width: profile.width,
        height: profile.height,
        dpi: profile.dpi || 96,
      };
    }

    return null;
  };

  const fitDisplayToHost = useEffectEvent((client: InstanceType<typeof Guacamole.Client>, host: HTMLDivElement) => {
    const display = client.getDisplay();
    const displayWidth = display.getWidth();
    const displayHeight = display.getHeight();
    if (!displayWidth || !displayHeight || !host.clientWidth || !host.clientHeight) {
      return;
    }

    const scale = Math.max(
      Math.min(host.clientWidth / displayWidth, host.clientHeight / displayHeight),
      0.1,
    );
    display.scale(scale);
  });

  const disconnectClient = useEffectEvent((options?: { revoke?: boolean; disconnectTransport?: boolean }) => {
    connectGenerationRef.current += 1;
    hasConnectedRef.current = false;
    const authToken = authTokenRef.current;
    authTokenRef.current = null;
    const shouldRevoke = options?.revoke ?? true;
    const shouldDisconnectTransport = options?.disconnectTransport ?? true;
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;

    if (clientRef.current && shouldDisconnectTransport) {
      clientRef.current.disconnect();
    }
    clientRef.current = null;

    if (tunnelRef.current && shouldDisconnectTransport) {
      tunnelRef.current.disconnect();
    }
    tunnelRef.current = null;

    if (displayHostRef.current) {
      displayHostRef.current.replaceChildren();
    }

    if (authToken && shouldRevoke) {
      void revokeGuacamoleClientSession(authToken);
    }
  });

  const createPersistedClientSession = (
    clientSession: NonNullable<GuacamoleClientSession["client_session"]>,
  ): PersistedGuacamoleClientSession => ({
    authToken: clientSession.auth_token,
    dataSource: clientSession.data_source,
    connectionId: clientSession.connection_id,
    connectionType: clientSession.connection_type,
    display: clientSession.display,
    tunnels: {
      websocket: clientSession.tunnels.websocket,
      http: clientSession.tunnels.http,
    },
  });

  const refreshDiagnostics = useEffectEvent(async (fallbackTargetHost: string | null) => {
    const now = Date.now();
    if (now - diagnosticsRefreshAtRef.current < 5000) {
      return;
    }
    diagnosticsRefreshAtRef.current = now;

    try {
      const diagnostics = await fetchGuacamoleDiagnostics(session.agentId);
      onUpdate({
        targetHost: diagnostics.resolved_fields?.guacamole_target_host || diagnostics.resolved_fields?.hostname || fallbackTargetHost,
        connectionName: diagnostics.connection?.name || diagnostics.resolved_fields?.guacamole_connection_name || diagnostics.connection_label || null,
        hint: buildWorkspaceHint(diagnostics, fallbackTargetHost),
      });
    } catch {
      onUpdate({
        hint: buildWorkspaceHint(null, fallbackTargetHost),
      });
    }
  });

  const connectClient = useEffectEvent(async () => {
    const host = displayHostRef.current;
    if (!host) {
      return;
    }

    const connectGeneration = connectGenerationRef.current + 1;
    connectGenerationRef.current = connectGeneration;
    hasConnectedRef.current = false;
    onUpdate({
      status: "preparing",
      error: null,
      hint: null,
      connected: false,
    });

    let sessionData: GuacamoleClientSession | null = null;
    let clientSession: NonNullable<GuacamoleClientSession["client_session"]> | null = session.clientSession
      ? {
          auth_token: session.clientSession.authToken,
          data_source: session.clientSession.dataSource,
          connection_id: session.clientSession.connectionId,
          connection_type: session.clientSession.connectionType,
          display: session.clientSession.display,
          tunnels: {
            websocket: session.clientSession.tunnels.websocket ?? undefined,
            http: session.clientSession.tunnels.http ?? undefined,
          },
        }
      : null;
    try {
      if (!clientSession) {
        sessionData = await createGuacamoleClientSession(session.agentId);
        clientSession = sessionData.client_session;
      }
    } catch (error) {
      onUpdate({
        status: "connect_failed",
        error: error instanceof Error ? error.message : String(error),
        connected: false,
      });
      return;
    }

    if (connectGenerationRef.current !== connectGeneration) {
      if (clientSession?.auth_token) {
        await revokeGuacamoleClientSession(clientSession.auth_token);
      }
      return;
    }

    if (!clientSession) {
      onUpdate({
        status: sessionData?.status ?? "needs_configuration",
        error: sessionData?.warnings?.[0] ?? "No Guacamole session is configured for this agent.",
        clientSession: null,
        connected: false,
      });
      return;
    }

    const resolvedTargetHost = sessionData?.resolved_fields?.guacamole_target_host || sessionData?.resolved_fields?.hostname || session.targetHost || null;
    const resolvedConnectionName = sessionData?.resolved_fields?.guacamole_connection_name || sessionData?.connection_label || session.connectionName || null;
    const resolvedTitle = sessionData?.connection_label || session.title;
    authTokenRef.current = clientSession.auth_token;
    onUpdate({
      title: resolvedTitle,
      error: null,
      hint: null,
      targetHost: resolvedTargetHost,
      connectionName: resolvedConnectionName,
      clientSession: createPersistedClientSession(clientSession),
    });

    const websocketTunnelUrl = clientSession.tunnels.websocket;
    const httpTunnelUrl = clientSession.tunnels.http;
    if (!websocketTunnelUrl && !httpTunnelUrl) {
      onUpdate({
        status: "needs_configuration",
        error: "No Guacamole tunnel endpoint is configured.",
        clientSession: null,
        connected: false,
      });
      return;
    }

    const tunnel = window.WebSocket && websocketTunnelUrl
      ? new Guacamole.ChainedTunnel(
          new Guacamole.WebSocketTunnel(websocketTunnelUrl),
          ...(httpTunnelUrl ? [new Guacamole.HTTPTunnel(httpTunnelUrl)] : []),
        )
      : new Guacamole.HTTPTunnel(httpTunnelUrl || "");
    tunnel.receiveTimeout = 120000;
    tunnel.unstableThreshold = 10000;

    const client = new Guacamole.Client(tunnel);
    const displayElement = client.getDisplay().getElement();

    host.replaceChildren(displayElement);
    displayElement.classList.add("block", "max-w-none");

    const stateLabels: Record<number, string> = {
      [Guacamole.Client.State.IDLE]: "idle",
      [Guacamole.Client.State.CONNECTING]: "connecting",
      [Guacamole.Client.State.WAITING]: "waiting",
      [Guacamole.Client.State.CONNECTED]: "connected",
      [Guacamole.Client.State.DISCONNECTING]: "disconnecting",
      [Guacamole.Client.State.DISCONNECTED]: "disconnected",
    };

    client.onstatechange = (state) => {
      if (state === Guacamole.Client.State.CONNECTED) {
        hasConnectedRef.current = true;
      }
      if (state === Guacamole.Client.State.DISCONNECTED || state === Guacamole.Client.State.DISCONNECTING) {
        void refreshDiagnostics(resolvedTargetHost);
      }
      onUpdate({
        status: stateLabels[state] || `state:${state}`,
        connected: state === Guacamole.Client.State.CONNECTED,
        error: state === Guacamole.Client.State.CONNECTED ? null : undefined,
      });
    };

    client.onerror = (status) => {
      void refreshDiagnostics(resolvedTargetHost);
      onUpdate({
        error: status.message || `Guacamole error ${status.code ?? "unknown"}`,
        connected: false,
      });
    };

    tunnel.onstatechange = (state) => {
      if (state === 2 && !hasConnectedRef.current) {
        void refreshDiagnostics(resolvedTargetHost);
        onUpdate({
          status: "tunnel_closed",
          connected: false,
        });
      }
    };

    tunnel.onerror = (status) => {
      if (!hasConnectedRef.current) {
        void refreshDiagnostics(resolvedTargetHost);
        onUpdate({
          error: status.message || `Tunnel error ${status.code ?? "unknown"}`,
          connected: false,
        });
      }
    };

    const sendResize = () => {
      const displayProfile = getDisplayProfile(clientSession);
      if (displayProfile) {
        fitDisplayToHost(client, host);
        return;
      }

      const pixelRatio = window.devicePixelRatio || 1;
      client.sendSize(
        Math.max(640, Math.floor(host.clientWidth * pixelRatio)),
        Math.max(360, Math.floor(host.clientHeight * pixelRatio)),
        Math.max(96, Math.floor(pixelRatio * 96)),
      );
      fitDisplayToHost(client, host);
    };

    sendResizeRef.current = sendResize;

    client.getDisplay().onresize = () => {
      fitDisplayToHost(client, host);
    };

    const mouse = new Guacamole.Mouse(displayElement);
    mouse.onmousedown = mouse.onmouseup = mouse.onmousemove = (state) => {
      if (!activeRef.current) {
        return;
      }
      client.sendMouseState(state, true);
    };

    const keyboard = new Guacamole.Keyboard(host);
    keyboard.onkeydown = (keysym) => {
      if (!activeRef.current) {
        return true;
      }
      client.sendKeyEvent(1, keysym);
      return false;
    };
    keyboard.onkeyup = (keysym) => {
      if (!activeRef.current) {
        return true;
      }
      client.sendKeyEvent(0, keysym);
      return false;
    };

    resizeObserverRef.current = new ResizeObserver(() => {
      if (activeRef.current) {
        sendResize();
      }
    });
    resizeObserverRef.current.observe(host);

    clientRef.current = client;
    tunnelRef.current = tunnel;

    if (connectGenerationRef.current !== connectGeneration) {
      client.disconnect();
      tunnel.disconnect();
      await revokeGuacamoleClientSession(clientSession.auth_token);
      return;
    }

    try {
      const displayProfile = getDisplayProfile(clientSession);
      const pixelRatio = window.devicePixelRatio || 1;
      const connectWidth = displayProfile?.width ?? Math.max(640, Math.floor(host.clientWidth * pixelRatio));
      const connectHeight = displayProfile?.height ?? Math.max(360, Math.floor(host.clientHeight * pixelRatio));
      const connectDpi = displayProfile?.dpi ?? Math.max(96, Math.floor(pixelRatio * 96));
      const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
      const params = new URLSearchParams({
        token: clientSession.auth_token,
        GUAC_DATA_SOURCE: clientSession.data_source,
        GUAC_ID: clientSession.connection_id,
        GUAC_TYPE: clientSession.connection_type,
        GUAC_WIDTH: String(connectWidth),
        GUAC_HEIGHT: String(connectHeight),
        GUAC_DPI: String(connectDpi),
        GUAC_TIMEZONE: timezone,
      });

      client.connect(params.toString());
      sendResize();
    } catch (error) {
      onUpdate({
        status: "connect_failed",
        error: error instanceof Error ? error.message : String(error),
        clientSession: null,
        connected: false,
      });
    }
  });

  useEffect(() => {
    void connectClient();
    return () => {
      disconnectClient({
        revoke: !pageUnloadingRef.current,
        disconnectTransport: !pageUnloadingRef.current,
      });
    };
  }, [session.instanceId]);

  useEffect(() => {
    if (!active) {
      return;
    }

    const host = displayHostRef.current;
    if (!host) {
      return;
    }

    const handle = window.requestAnimationFrame(() => {
      host.focus({ preventScroll: true });
      sendResizeRef.current();
    });

    return () => {
      window.cancelAnimationFrame(handle);
    };
  }, [active, session.instanceId]);

  return (
    <div
      ref={displayHostRef}
      tabIndex={0}
      onMouseDown={() => {
        if (active) {
          displayHostRef.current?.focus({ preventScroll: true });
        }
      }}
      className="flex h-full w-full items-center justify-center overflow-hidden bg-slate-950 select-none outline-none"
    />
  );
}

function GlobalGuacamoleWorkspace({
  session,
  onUpdate,
  onResume,
  onMinimize,
  onFullscreen,
  onClose,
}: {
  session: WorkspaceConnection | null;
  onUpdate: (patch: Partial<WorkspaceConnection>) => void;
  onResume: () => void;
  onMinimize: () => void;
  onFullscreen: () => void;
  onClose: () => void;
}) {
  const minDockedWidth = 720;
  const maxDockedWidth = 1440;
  const minDockedHeight = 380;
  const maxDockedHeight = 900;
  const persistedDockedRect = useSyncExternalStore(
    subscribeToWorkspaceStorage,
    loadDockedWorkspaceRect,
    getDefaultDockedWorkspaceRect,
  );
  const [dockedRectOverride, setDockedRectOverride] = useState<DockedWorkspaceRect | undefined>(undefined);
  const [isInteracting, setIsInteracting] = useState(false);
  const dockedRect = dockedRectOverride ?? persistedDockedRect;
  const interactionStateRef = useRef<{
    mode: "move" | "resize";
    edge: "left" | "top" | "corner";
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
    startLeft: number;
    startTop: number;
  } | null>(null);

  const clampRect = useCallback((width: number, height: number, x: number, y: number) => {
    const viewportWidth = typeof window !== "undefined" ? window.innerWidth : maxDockedWidth;
    const viewportHeight = typeof window !== "undefined" ? window.innerHeight : maxDockedHeight;
    const clampedWidth = Math.min(Math.max(width, minDockedWidth), Math.min(maxDockedWidth, Math.max(minDockedWidth, viewportWidth - 48)));
    const clampedHeight = Math.min(Math.max(height, minDockedHeight), Math.min(maxDockedHeight, Math.max(minDockedHeight, viewportHeight - 48)));

    return {
      width: clampedWidth,
      height: clampedHeight,
      x: Math.min(Math.max(x, 16), Math.max(16, viewportWidth - clampedWidth - 16)),
      y: Math.min(Math.max(y, 16), Math.max(16, viewportHeight - clampedHeight - 16)),
    };
  }, [maxDockedHeight, maxDockedWidth]);

  const stopInteraction = useCallback(() => {
    interactionStateRef.current = null;
    setIsInteracting(false);
    document.body.classList.remove("select-none");
    document.body.style.cursor = "";
  }, []);

  const setDockedRect = useCallback((next: DockedWorkspaceRect | ((current: DockedWorkspaceRect) => DockedWorkspaceRect)) => {
    setDockedRectOverride((current) => {
      const base = current ?? persistedDockedRect;
      return typeof next === "function" ? next(base) : next;
    });
  }, [persistedDockedRect]);

  const startResize = useCallback((edge: "left" | "top" | "corner", event: ReactPointerEvent<HTMLDivElement>) => {
    if (!session || session.fullscreen || session.minimized) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    interactionStateRef.current = {
      mode: "resize",
      edge,
      startX: event.clientX,
      startY: event.clientY,
      startWidth: dockedRect.width,
      startHeight: dockedRect.height,
      startLeft: dockedRect.x,
      startTop: dockedRect.y,
    };
    setIsInteracting(true);
    document.body.classList.add("select-none");
    document.body.style.cursor = edge === "left" ? "ew-resize" : edge === "top" ? "ns-resize" : "nwse-resize";
  }, [dockedRect.height, dockedRect.width, dockedRect.x, dockedRect.y, session]);

  const startMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    if (!session || session.fullscreen || session.minimized) {
      return;
    }

    const target = event.target;
    if (target instanceof HTMLElement && target.closest("button")) {
      return;
    }

    event.preventDefault();
    interactionStateRef.current = {
      mode: "move",
      edge: "corner",
      startX: event.clientX,
      startY: event.clientY,
      startWidth: dockedRect.width,
      startHeight: dockedRect.height,
      startLeft: dockedRect.x,
      startTop: dockedRect.y,
    };
    setIsInteracting(true);
    document.body.classList.add("select-none");
    document.body.style.cursor = "grabbing";
  }, [dockedRect.height, dockedRect.width, dockedRect.x, dockedRect.y, session]);

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      const current = interactionStateRef.current;
      if (!current) {
        return;
      }

      if (current.mode === "move") {
        setDockedRect(
          clampRect(
            current.startWidth,
            current.startHeight,
            current.startLeft + (event.clientX - current.startX),
            current.startTop + (event.clientY - current.startY),
          ),
        );
        return;
      }

      const widthDelta = current.startX - event.clientX;
      const heightDelta = current.startY - event.clientY;
      const nextWidth = current.edge === "top" ? current.startWidth : current.startWidth + widthDelta;
      const nextHeight = current.edge === "left" ? current.startHeight : current.startHeight + heightDelta;
      const nextLeft = current.edge === "top" ? current.startLeft : current.startLeft - (nextWidth - current.startWidth);
      const nextTop = current.edge === "left" ? current.startTop : current.startTop - (nextHeight - current.startHeight);
      setDockedRect(clampRect(nextWidth, nextHeight, nextLeft, nextTop));
    };

    const handlePointerUp = () => {
      stopInteraction();
    };

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      stopInteraction();
    };
  }, [clampRect, setDockedRect, stopInteraction]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (isInteracting) {
      return;
    }
    const raw = JSON.stringify(dockedRect);
    dockedWorkspaceRectSnapshotCache = {
      raw,
      value: dockedRect,
    };
    window.localStorage.setItem(DOCKED_WORKSPACE_STORAGE_KEY, raw);
  }, [dockedRect, isInteracting]);

  useEffect(() => {
    const handleWindowResize = () => {
      setDockedRect((current) => clampRect(current.width, current.height, current.x, current.y));
    };

    window.addEventListener("resize", handleWindowResize);
    return () => {
      window.removeEventListener("resize", handleWindowResize);
    };
  }, [clampRect, setDockedRect]);

  if (!session) {
    return null;
  }

  const isVisible = !session.minimized;
  const dockedStyle = {
    width: `${dockedRect.width}px`,
    height: `${dockedRect.height}px`,
    left: `${dockedRect.x}px`,
    top: `${dockedRect.y}px`,
  };
  const shellClassName = session.fullscreen
    ? "fixed inset-0 z-50 flex flex-col border border-slate-700/80 bg-slate-950/98 shadow-2xl"
    : session.minimized
      ? "fixed -left-[200vw] top-0 h-px w-px overflow-hidden"
      : "fixed z-40 flex flex-col overflow-hidden rounded-2xl border border-slate-700/80 bg-slate-950/97 shadow-[0_24px_90px_rgba(2,6,23,0.72)] backdrop-blur";

  return (
    <>
      <div className={shellClassName} style={session.fullscreen || session.minimized ? undefined : dockedStyle}>
        {!session.fullscreen && !session.minimized && (
          <>
            <div
              onPointerDown={(event) => startResize("top", event)}
              className="absolute inset-x-12 top-0 z-20 h-2 cursor-ns-resize"
              aria-hidden="true"
            />
            <div
              onPointerDown={(event) => startResize("left", event)}
              className="absolute inset-y-12 left-0 z-20 w-2 cursor-ew-resize"
              aria-hidden="true"
            />
            <div
              onPointerDown={(event) => startResize("corner", event)}
              className="absolute left-0 top-0 z-20 h-4 w-4 cursor-nwse-resize"
              aria-hidden="true"
            />
          </>
        )}
        <div
          onPointerDown={startMove}
          className="flex items-center justify-between gap-3 border-b border-slate-700/70 bg-slate-900/88 px-4 py-3"
        >
          <div className="flex min-w-0 items-center gap-3">
            <div className="hidden h-1.5 w-14 rounded-full bg-slate-700/90 sm:block" />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-100">{session.title}</p>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                <span className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-0.5 text-cyan-200">
                  {session.agentId}
                </span>
                <span>{session.connected ? "Connected" : session.status}</span>
                <span>{session.fullscreen ? "Fullscreen" : "Docked workspace"}</span>
                {session.targetHost && <span>Target {session.targetHost}</span>}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!session.fullscreen && (
              <button
                onClick={onFullscreen}
                className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
              >
                Fullscreen
              </button>
            )}
            <button
              onClick={onMinimize}
              className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
            >
              {session.fullscreen ? "Exit Fullscreen" : "Minimize"}
            </button>
            <button
              onClick={onClose}
              className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-200 hover:border-rose-400"
            >
              Close
            </button>
          </div>
        </div>
        <div className="relative min-h-0 flex-1">
          <GuacamoleViewport session={session} active={isVisible} onUpdate={onUpdate} />
          {!session.connected && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-slate-950/55">
              <div className="max-w-[min(92%,34rem)] rounded-md border border-slate-700 bg-slate-900/90 px-4 py-3 text-xs text-slate-300 shadow-2xl">
                <p className="font-medium text-slate-100">{session.error || session.status || "Connecting"}</p>
                {session.hint && <p className="mt-2 text-slate-300/90">{session.hint}</p>}
                {(session.targetHost || session.connectionName) && (
                  <div className="mt-3 space-y-1 text-[11px] text-slate-400">
                    {session.targetHost && <p>Target host: {session.targetHost}</p>}
                    {session.connectionName && <p>Guacamole connection: {session.connectionName}</p>}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
        {!session.fullscreen && (
          <div className="flex items-center justify-between gap-3 border-t border-slate-800 bg-slate-950/95 px-4 py-2 text-[11px] text-slate-500">
            <span>Docked global workspace · drag the header to move, top or left edge to resize</span>
            <span>{session.minimized ? "Minimized" : session.connected ? "Ready for input" : "Connecting"}</span>
          </div>
        )}
      </div>

      {session.minimized && (
        <div className="pointer-events-none fixed bottom-4 right-4 z-40 flex max-w-[min(92vw,28rem)] flex-wrap justify-end gap-2">
          <div className="pointer-events-auto min-w-56 rounded-lg border border-slate-700/80 bg-slate-900/92 px-3 py-2 shadow-2xl backdrop-blur">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-100">{session.title}</p>
                <p className="text-[11px] text-slate-500">{session.connected ? "Connected" : session.status}</p>
              </div>
              <span className={`rounded-full px-2 py-1 text-[11px] font-medium ${
                session.connected
                  ? "bg-emerald-500/15 text-emerald-300"
                  : session.error
                    ? "bg-rose-500/15 text-rose-300"
                    : "bg-blue-500/15 text-blue-300"
              }`}>
                Minimized
              </span>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={onResume}
                className="rounded-md border border-slate-600 bg-slate-950/70 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:border-slate-500"
              >
                Resume
              </button>
              <button
                onClick={onFullscreen}
                className="rounded-md border border-slate-600 bg-slate-950/70 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:border-slate-500"
              >
                Fullscreen
              </button>
              <button
                onClick={onClose}
                className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-[11px] font-medium text-rose-200 hover:border-rose-400"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export function GuacamoleWorkspaceProvider({ children }: { children: ReactNode }) {
  const persistedSession = useSyncExternalStore(
    subscribeToWorkspaceStorage,
    loadPersistedWorkspaceSession,
    () => null,
  );
  const [sessionOverride, setSessionOverride] = useState<WorkspaceConnection | null | undefined>(undefined);
  const session = sessionOverride === undefined ? persistedSession : sessionOverride;

  useEffect(() => {
    if (sessionOverride === undefined) {
      return;
    }
    persistWorkspaceSession(session);
  }, [session, sessionOverride]);

  const patchSession = (patch: Partial<WorkspaceConnection>) => {
    setSessionOverride((current) => {
      const base = current === undefined ? persistedSession : current;
      return base ? { ...base, ...patch } : base;
    });
  };

  const openSession = (agentId: string, title = "Remote Desktop") => {
    setSessionOverride((current) => {
      const base = current === undefined ? persistedSession : current;
      if (base && base.agentId === agentId) {
        return {
          ...base,
          minimized: false,
          fullscreen: false,
          title: base.title || title,
        };
      }

      return {
        instanceId: createInstanceId(agentId),
        agentId,
        title,
        status: "queued",
        error: null,
        hint: null,
        targetHost: null,
        connectionName: null,
        connected: false,
        minimized: false,
        fullscreen: false,
        launchedAt: Date.now(),
        clientSession: null,
      };
    });
  };

  const resumeSession = () => {
    setSessionOverride((current) => {
      const base = current === undefined ? persistedSession : current;
      return base ? { ...base, minimized: false, fullscreen: false } : base;
    });
  };

  const minimizeSession = () => {
    setSessionOverride((current) => {
      const base = current === undefined ? persistedSession : current;
      return base ? { ...base, minimized: true, fullscreen: false } : base;
    });
  };

  const fullscreenSession = () => {
    setSessionOverride((current) => {
      const base = current === undefined ? persistedSession : current;
      return base ? { ...base, minimized: false, fullscreen: true } : base;
    });
  };

  const closeSession = () => {
    setSessionOverride(null);
  };

  return (
    <GuacamoleWorkspaceContext.Provider
      value={{
        session,
        openSession,
        resumeSession,
        minimizeSession,
        fullscreenSession,
        closeSession,
        isCurrentAgentSession: (agentId: string) => session?.agentId === agentId,
      }}
    >
      {children}
      <GlobalGuacamoleWorkspace
        session={session}
        onUpdate={patchSession}
        onResume={resumeSession}
        onMinimize={minimizeSession}
        onFullscreen={fullscreenSession}
        onClose={closeSession}
      />
    </GuacamoleWorkspaceContext.Provider>
  );
}

export function useGuacamoleWorkspace() {
  const context = useContext(GuacamoleWorkspaceContext);
  if (!context) {
    throw new Error("useGuacamoleWorkspace must be used within GuacamoleWorkspaceProvider");
  }
  return context;
}