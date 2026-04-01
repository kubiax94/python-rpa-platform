"use client";

import { useCallback, useEffect, useEffectEvent, useRef, useState } from "react";
import Guacamole from "guacamole-common-js";
import {
  createGuacamoleClientSession,
  fetchGuacamoleSessionStatus,
  fetchGuacamoleDiagnostics,
  revokeGuacamoleClientSession,
  type GuacamoleClientSession,
} from "@/hooks/useGuacamole";
import {
  clearPersistedDisplayState,
  loadPersistedDisplayState,
  loadPersistedWorkspaceSession,
  persistDisplayState,
  persistWorkspaceSession,
} from "@/components/guacamole/storage";
import type { PersistedGuacamoleClientSession, WorkspaceConnection } from "@/components/guacamole/types";
import {
  buildWorkspaceHint,
  BACKEND_DISCONNECTED_EVENT,
  getSnapshotCapableClient,
  maskDebugValue,
  resetGuacamoleKeyboard,
} from "@/components/guacamole/utils";
import { GuacamoleRequiredPrompt } from "@/components/GuacamoleRequiredPrompt";

type RequiredPromptState = {
  parameters: string[];
  values: Record<string, string>;
  submitting: boolean;
  error: string | null;
};

const pendingViewportCleanupByInstanceId = new Map<string, number>();

export function GuacamoleViewport({
  session,
  active,
  onUpdate,
}: {
  session: WorkspaceConnection;
  active: boolean;
  onUpdate: (patch: Partial<WorkspaceConnection>) => void;
}) {
  const displayHostRef = useRef<HTMLDivElement | null>(null);
  const keyboardTargetRef = useRef<HTMLElement | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const connectGenerationRef = useRef(0);
  const authTokenRef = useRef<string | null>(null);
  const resumeTunnelUuidRef = useRef<string | null>(null);
  const activeRef = useRef(active);
  const sessionSnapshotRef = useRef({
    agentId: session.agentId,
    instanceId: session.instanceId,
    connected: session.connected,
  });
  const latestSessionRef = useRef(session);
  const hasConnectedRef = useRef(false);
  const clientStateRef = useRef<number>(Guacamole.Client.State.IDLE);
  const diagnosticsRefreshAtRef = useRef(0);
  const pageUnloadingRef = useRef(false);
  const sendResizeRef = useRef<() => void>(() => undefined);
  const forceFreshOnNextConnectRef = useRef(false);
  const refreshTunnelOnNextConnectRef = useRef(false);
  const connectInFlightRef = useRef(false);
  const handledClosureAuthTokenRef = useRef<string | null>(null);
  const hydratedPersistedSessionRef = useRef(Boolean(session.clientSession));
  const latestPersistedClientSessionRef = useRef<PersistedGuacamoleClientSession | null>(session.clientSession ?? null);
  const skipStoredTunnelResumeRef = useRef(false);
  const keyboardCaptureEnabledRef = useRef(false);
  const keyboardRef = useRef<InstanceType<typeof Guacamole.Keyboard> | null>(null);
  const clientRef = useRef<InstanceType<typeof Guacamole.Client> | null>(null);
  const tunnelRef = useRef<InstanceType<typeof Guacamole.HTTPTunnel> | InstanceType<typeof Guacamole.WebSocketTunnel> | InstanceType<typeof Guacamole.ChainedTunnel> | null>(null);
  const exportingDisplayStateRef = useRef(false);
  const [reconnectRequestId, setReconnectRequestId] = useState(0);
  const [requiredPrompt, setRequiredPrompt] = useState<RequiredPromptState | null>(null);

  useEffect(() => {
    sessionSnapshotRef.current = {
      agentId: session.agentId,
      instanceId: session.instanceId,
      connected: session.connected,
    };
  }, [session.agentId, session.connected, session.instanceId]);

  useEffect(() => {
    latestSessionRef.current = session;
  }, [session]);

  const persistedClientAuthToken = session.clientSession?.authToken ?? "";
  const persistedClientResumeTunnel = session.clientSession?.resumeTunnelUuid ?? "";

  const debugLog = useCallback((event: string, details?: Record<string, unknown>) => {
    const snapshot = sessionSnapshotRef.current;
    console.info("[GuacamoleWorkspace]", event, {
      agentId: snapshot.agentId,
      instanceId: snapshot.instanceId,
      connected: snapshot.connected,
      active: activeRef.current,
      ...details,
    });
  }, []);

  useEffect(() => {
    const pendingCleanupId = pendingViewportCleanupByInstanceId.get(session.instanceId);
    if (pendingCleanupId != null) {
      window.clearTimeout(pendingCleanupId);
      pendingViewportCleanupByInstanceId.delete(session.instanceId);
      debugLog("cancel-pending-cleanup", {
        instanceId: session.instanceId,
      });
    }
  }, [debugLog, session.instanceId]);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  useEffect(() => {
    latestPersistedClientSessionRef.current = session.clientSession ?? null;
  }, [session.clientSession]);

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

  const waitForRenderableHost = useEffectEvent(async (host: HTMLDivElement) => {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      if (host.clientWidth > 0 && host.clientHeight > 0) {
        return true;
      }

      await new Promise<void>((resolve) => {
        window.requestAnimationFrame(() => {
          resolve();
        });
      });
    }

    return host.clientWidth > 0 && host.clientHeight > 0;
  });

  const fitDisplayToHost = useEffectEvent((client: InstanceType<typeof Guacamole.Client>, host: HTMLDivElement) => {
    const display = client.getDisplay();
    const displayWidth = display.getWidth();
    const displayHeight = display.getHeight();
    const displayElement = display.getElement() as HTMLElement;
    if (!displayWidth || !displayHeight || !host.clientWidth || !host.clientHeight) {
      return;
    }

    if (session.fullscreen && session.clientSession?.display?.mode === "fixed") {
      const scale = Math.max(
        host.clientWidth / displayWidth,
        host.clientHeight / displayHeight,
        0.1,
      );
      const scaledWidth = displayWidth * scale;
      const scaledHeight = displayHeight * scale;
      displayElement.style.left = `${Math.round((host.clientWidth - scaledWidth) / 2)}px`;
      displayElement.style.top = `${Math.round((host.clientHeight - scaledHeight) / 2)}px`;
      displayElement.style.right = "auto";
      displayElement.style.bottom = "auto";
      displayElement.style.transform = "";
      display.scale(scale);
      return;
    }

    displayElement.style.left = "auto";
    displayElement.style.top = "auto";
    displayElement.style.right = "0";
    displayElement.style.bottom = "0";
    displayElement.style.transform = "";

    const scale = Math.max(
      Math.min(host.clientWidth / displayWidth, host.clientHeight / displayHeight),
      0.1,
    );
    display.scale(scale);
  });

  const captureDisplayState = useEffectEvent((reason: string) => {
    const client = getSnapshotCapableClient(clientRef.current);
    const authToken = authTokenRef.current;
    const resumeTunnelUuid = resumeTunnelUuidRef.current;
    if (!client || !authToken || !resumeTunnelUuid || !hasConnectedRef.current || exportingDisplayStateRef.current) {
      return;
    }

    exportingDisplayStateRef.current = true;
    try {
      client.exportState((state) => {
        exportingDisplayStateRef.current = false;
        if (clientRef.current !== client) {
          return;
        }

        const persisted = persistDisplayState(authToken, resumeTunnelUuid, state as object);
        debugLog("display-state-exported", {
          reason,
          authToken: maskDebugValue(authToken),
          resumeTunnelUuid,
          persisted,
        });
      });
    } catch (error) {
      exportingDisplayStateRef.current = false;
      debugLog("display-state-export-failed", {
        reason,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  });

  useEffect(() => {
    const markPageUnloading = () => {
      pageUnloadingRef.current = true;
      const authToken = authTokenRef.current;
      const resumeTunnelUuid = resumeTunnelUuidRef.current;
      const persistedClientSession = latestPersistedClientSessionRef.current
        ? {
            ...latestPersistedClientSessionRef.current,
            authToken: authToken || latestPersistedClientSessionRef.current.authToken,
            resumeTunnelUuid: resumeTunnelUuid || latestPersistedClientSessionRef.current.resumeTunnelUuid,
          }
        : null;

      captureDisplayState("page-unloading");
      debugLog("page-unloading", {
        authToken: maskDebugValue(authToken),
        resumeTunnelUuid: resumeTunnelUuid ?? "<none>",
      });
      setRequiredPrompt(null);
      persistWorkspaceSession({
        ...session,
        connected: false,
        status: "queued",
        error: null,
        hint: null,
        clientSession: persistedClientSession,
      });
      authTokenRef.current = null;
      resumeTunnelUuidRef.current = null;
    };

    window.addEventListener("beforeunload", markPageUnloading);
    window.addEventListener("pagehide", markPageUnloading);
    return () => {
      window.removeEventListener("beforeunload", markPageUnloading);
      window.removeEventListener("pagehide", markPageUnloading);
    };
  }, [debugLog, session]);



  const focusRemoteDisplay = useCallback(() => {
    const focusTarget = keyboardTargetRef.current ?? displayHostRef.current;
    debugLog("focus-remote-display", {
      focusTarget: focusTarget?.tagName ?? "<none>",
      activeElement: document.activeElement instanceof HTMLElement ? document.activeElement.tagName : "<none>",
      activeRef: activeRef.current,
    });

    if (!activeRef.current) {
      return;
    }

    focusTarget?.focus({ preventScroll: true });
  }, [debugLog]);

  const maintainCaptureAfterBlur = useCallback((reason: string) => {
    if (!activeRef.current || !hasConnectedRef.current || !keyboardCaptureEnabledRef.current) {
      return;
    }

    debugLog("maintain-capture-after-blur", { reason });
    window.requestAnimationFrame(() => {
      if (!activeRef.current || !hasConnectedRef.current) {
        return;
      }
      keyboardCaptureEnabledRef.current = true;
      focusRemoteDisplay();
    });
  }, [debugLog, focusRemoteDisplay]);

  const setKeyboardCaptureEnabled = useCallback((enabled: boolean, reason: string) => {
    if (keyboardCaptureEnabledRef.current === enabled) {
      return;
    }

    keyboardCaptureEnabledRef.current = enabled;
    debugLog("keyboard-capture", { enabled, reason });
    if (!enabled) {
      resetGuacamoleKeyboard(keyboardRef.current);
    }
  }, [debugLog]);

  const disconnectClient = useCallback((options?: { revoke?: boolean; disconnectTransport?: boolean }) => {
    debugLog("disconnect-client", {
      revoke: options?.revoke ?? true,
      disconnectTransport: options?.disconnectTransport ?? true,
      authToken: maskDebugValue(authTokenRef.current),
    });
    connectGenerationRef.current += 1;
    connectInFlightRef.current = false;
    hasConnectedRef.current = false;
    clientStateRef.current = Guacamole.Client.State.IDLE;
    setKeyboardCaptureEnabled(false, "disconnect");
    const authToken = authTokenRef.current;
    const resumeTunnelUuid = resumeTunnelUuidRef.current;
    authTokenRef.current = null;
    resumeTunnelUuidRef.current = null;
    exportingDisplayStateRef.current = false;
    setRequiredPrompt(null);
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
    resetGuacamoleKeyboard(keyboardRef.current);
    keyboardRef.current = null;
    keyboardTargetRef.current = null;

    if (displayHostRef.current) {
      displayHostRef.current.replaceChildren();
    }

    if (shouldRevoke) {
      clearPersistedDisplayState(authToken, resumeTunnelUuid);
    }

    if (authToken && shouldRevoke) {
      void revokeGuacamoleClientSession(authToken);
    }
  }, [debugLog, setKeyboardCaptureEnabled]);

  useEffect(() => {
    const handleBackendDisconnected = () => {
      debugLog("backend-disconnected");
      setRequiredPrompt(null);
      persistWorkspaceSession({
        ...session,
        connected: false,
        status: "server_disconnected",
        error: "The control server connection was lost. The remote desktop session was closed.",
        hint: null,
        clientSession: null,
      });
      disconnectClient({ revoke: false, disconnectTransport: true });
      onUpdate({
        clientSession: null,
        connected: false,
        status: "server_disconnected",
        error: "The control server connection was lost. The remote desktop session was closed.",
        hint: null,
      });
    };

    window.addEventListener(BACKEND_DISCONNECTED_EVENT, handleBackendDisconnected);
    return () => {
      window.removeEventListener(BACKEND_DISCONNECTED_EVENT, handleBackendDisconnected);
    };
  }, [debugLog, disconnectClient, onUpdate, session]);
  
  const createPersistedClientSession = (
    clientSession: NonNullable<GuacamoleClientSession["client_session"]>,
  ): PersistedGuacamoleClientSession => ({
    authToken: clientSession.auth_token,
    dataSource: clientSession.data_source,
    connectionId: clientSession.connection_id,
    connectionType: clientSession.connection_type,
    resumeTunnelUuid: clientSession.resume_tunnel_uuid,
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

  const persistLatestSessionPatch = useEffectEvent((patch: Partial<WorkspaceConnection>) => {
    persistWorkspaceSession({
      ...latestSessionRef.current,
      ...patch,
    });
  });

  const resolveCloseReason = useEffectEvent(async (authToken: string | null) => {
    if (!authToken || handledClosureAuthTokenRef.current === authToken) {
      return "";
    }

    handledClosureAuthTokenRef.current = authToken;
    try {
      const status = await fetchGuacamoleSessionStatus(authToken);
      if (status.active) {
        handledClosureAuthTokenRef.current = null;
        return "";
      }
      return status.close_reason?.trim() || "";
    } catch {
      handledClosureAuthTokenRef.current = null;
      return "";
    }
  });

  const handleUnexpectedClosure = useEffectEvent(async ({
    authToken,
    fallbackStatus,
    fallbackError,
    fallbackTargetHost,
  }: {
    authToken: string | null;
    fallbackStatus: string;
    fallbackError?: string | null;
    fallbackTargetHost: string | null;
  }) => {
    const closeReason = await resolveCloseReason(authToken);
    disconnectClient({ revoke: false, disconnectTransport: false });
    if (!closeReason) {
      void refreshDiagnostics(fallbackTargetHost);
    }
    onUpdate({
      status: closeReason ? "session_closed" : fallbackStatus,
      connected: false,
      error: closeReason || fallbackError || null,
      clientSession: null,
    });
  });

  const updateRequiredPromptValue = useCallback((name: string, value: string) => {
    setRequiredPrompt((current) => {
      if (!current) {
        return current;
      }

      return {
        ...current,
        values: {
          ...current.values,
          [name]: value,
        },
      };
    });
  }, []);

  const cancelRequiredPrompt = useCallback(() => {
    setRequiredPrompt(null);
    disconnectClient({ revoke: true, disconnectTransport: true });
    onUpdate({
      clientSession: null,
      connected: false,
      status: "credentials_required",
      error: "Remote desktop login was cancelled before the required credentials were provided.",
    });
  }, [disconnectClient, onUpdate]);

  const submitRequiredPrompt = useCallback(() => {
    const client = clientRef.current;
    const prompt = requiredPrompt;
    if (!client || !prompt) {
      return;
    }

    setRequiredPrompt((current) => current ? { ...current, submitting: true, error: null } : current);

    try {
      for (const parameter of prompt.parameters) {
        const stream = client.createArgumentValueStream("text/plain", parameter);
        const writer = new Guacamole.StringWriter(stream);
        writer.sendText(prompt.values[parameter] ?? "");
        writer.sendEnd();
      }

      setRequiredPrompt(null);
      onUpdate({
        status: "credentials_submitted",
        error: null,
      });
    } catch (error) {
      setRequiredPrompt((current) => current ? {
        ...current,
        submitting: false,
        error: error instanceof Error ? error.message : String(error),
      } : current);
    }
  }, [onUpdate, requiredPrompt]);

  const connectClient = useEffectEvent(async (options?: { forceFresh?: boolean }) => {
    const host = displayHostRef.current;
    if (!host) {
      debugLog("connect-skipped-no-host");
      return;
    }

    if (connectInFlightRef.current) {
      debugLog("connect-skipped-in-flight", {
        status: session.status,
        persistedAuthToken: maskDebugValue(session.clientSession?.authToken),
      });
      return;
    }

    connectInFlightRef.current = true;

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
    let retriedFreshSession = false;
    let clientSession: NonNullable<GuacamoleClientSession["client_session"]> | null = null;
    let reusedPersistedSession = false;
    let attemptedStoredTunnelResume = false;
    let usingStoredTunnelResume = false;
    const storedSessionCandidate = loadPersistedWorkspaceSession();
    const storageClientSession = (
      storedSessionCandidate
      && storedSessionCandidate.agentId === session.agentId
      && (storedSessionCandidate.requestedConnectionId || null) === (session.requestedConnectionId || null)
      && (storedSessionCandidate.requestedVmUsername || null) === (session.requestedVmUsername || null)
    )
      ? storedSessionCandidate.clientSession
      : null;
    const reusableClientSession = session.clientSession || storageClientSession;
    debugLog("connect-start", {
      forceFresh: !!options?.forceFresh,
      readOnly: session.readOnly,
      recorded: session.recorded,
      requestedConnectionId: session.requestedConnectionId ?? "<none>",
      requestedVmUsername: session.requestedVmUsername ?? "<none>",
      persistedAuthToken: maskDebugValue(session.clientSession?.authToken),
      persistedResumeTunnel: session.clientSession?.resumeTunnelUuid ?? "<none>",
      storageCandidateAuthToken: maskDebugValue(storageClientSession?.authToken),
    });
    const canReusePersistedSession = Boolean(reusableClientSession && !options?.forceFresh && !refreshTunnelOnNextConnectRef.current);
    const canDirectResumePersistedTunnel = Boolean(
      reusableClientSession
      && reusableClientSession.authToken
      && reusableClientSession.resumeTunnelUuid
      && reusableClientSession.tunnels.http
      && !options?.forceFresh
      && !refreshTunnelOnNextConnectRef.current
      && !skipStoredTunnelResumeRef.current,
    );
    if (canDirectResumePersistedTunnel && reusableClientSession) {
      usingStoredTunnelResume = true;
      clientSession = {
        auth_token: reusableClientSession.authToken,
        data_source: reusableClientSession.dataSource,
        connection_id: reusableClientSession.connectionId,
        connection_type: reusableClientSession.connectionType,
        resume_tunnel_uuid: reusableClientSession.resumeTunnelUuid,
        display: reusableClientSession.display,
        tunnels: {
          websocket: reusableClientSession.tunnels.websocket,
          http: reusableClientSession.tunnels.http,
        },
      };
      sessionData = {
        enabled: true,
        configured: true,
        status: "ready",
        read_only: session.readOnly,
        agent_id: session.agentId,
        source: "persisted",
        connection_id: reusableClientSession.connectionId,
        connection_label: session.connectionName || session.title,
        display: reusableClientSession.display,
        allow_embed: true,
        connection_type: reusableClientSession.connectionType,
        resolved_fields: {
          guacamole_target_host: session.targetHost || undefined,
          guacamole_connection_name: session.connectionName || undefined,
        },
        tunnels: {
          websocket: reusableClientSession.tunnels.websocket,
          http: reusableClientSession.tunnels.http,
        },
        warnings: [],
        client_session: clientSession,
      };
      reusedPersistedSession = true;
      attemptedStoredTunnelResume = true;
      debugLog("connect-session-reused", {
        source: session.clientSession ? "props+direct-resume" : "storage+direct-resume",
        authToken: maskDebugValue(clientSession.auth_token),
        resumeTunnelUuid: clientSession.resume_tunnel_uuid ?? "<none>",
        connectionId: clientSession.connection_id ?? "<none>",
        reusedExistingAuthToken: true,
      });
    } else if (canReusePersistedSession && reusableClientSession) {
      try {
        sessionData = await createGuacamoleClientSession(session.agentId, {
          refreshTunnel: refreshTunnelOnNextConnectRef.current || skipStoredTunnelResumeRef.current,
          resumeAuthToken: reusableClientSession.authToken,
          connectionId: session.requestedConnectionId ?? undefined,
          vmUsername: session.requestedVmUsername ?? undefined,
          readOnly: session.readOnly,
          recorded: session.recorded,
        });
        skipStoredTunnelResumeRef.current = false;
        refreshTunnelOnNextConnectRef.current = false;
        clientSession = sessionData.client_session;
        reusedPersistedSession = Boolean(
          clientSession
          && reusableClientSession.authToken
          && clientSession.auth_token === reusableClientSession.authToken,
        );
        debugLog("connect-session-reused", {
          source: session.clientSession ? "props+backend-refresh" : "storage+backend-refresh",
          authToken: maskDebugValue(clientSession?.auth_token),
          resumeTunnelUuid: clientSession?.resume_tunnel_uuid ?? "<none>",
          connectionId: clientSession?.connection_id ?? "<none>",
          reusedExistingAuthToken: reusedPersistedSession,
        });
      } catch (error) {
        connectInFlightRef.current = false;
        debugLog("connect-session-reuse-failed", {
          source: session.clientSession ? "props" : "storage",
          error: error instanceof Error ? error.message : String(error),
        });
        onUpdate({
          status: "connect_failed",
          error: error instanceof Error ? error.message : String(error),
          connected: false,
        });
        return;
      }
    } else {
      try {
        sessionData = await createGuacamoleClientSession(session.agentId, {
          forceFresh: options?.forceFresh,
          refreshTunnel: refreshTunnelOnNextConnectRef.current,
          resumeAuthToken: reusableClientSession?.authToken,
          connectionId: session.requestedConnectionId ?? undefined,
          vmUsername: session.requestedVmUsername ?? undefined,
          readOnly: session.readOnly,
          recorded: session.recorded,
        });
        refreshTunnelOnNextConnectRef.current = false;
        clientSession = sessionData.client_session;
        debugLog("connect-session-fetched", {
          status: sessionData.status,
          authToken: maskDebugValue(clientSession?.auth_token),
          resumeTunnelUuid: clientSession?.resume_tunnel_uuid ?? "<none>",
          connectionId: clientSession?.connection_id ?? "<none>",
        });
      } catch (error) {
        connectInFlightRef.current = false;
        refreshTunnelOnNextConnectRef.current = false;
        debugLog("connect-session-fetch-failed", {
          error: error instanceof Error ? error.message : String(error),
        });
        onUpdate({
          status: "connect_failed",
          error: error instanceof Error ? error.message : String(error),
          connected: false,
        });
        return;
      }
    }

    const hostReady = await waitForRenderableHost(host);
    if (!hostReady) {
      debugLog("connect-host-layout-pending", {
        clientWidth: host.clientWidth,
        clientHeight: host.clientHeight,
      });
    }

    if (connectGenerationRef.current !== connectGeneration) {
      connectInFlightRef.current = false;
      debugLog("connect-stale-generation", {
        authToken: maskDebugValue(clientSession?.auth_token),
      });
      return;
    }

    if (!clientSession) {
      connectInFlightRef.current = false;
      debugLog("connect-missing-client-session", {
        status: sessionData?.status ?? "<none>",
      });
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
    const resolvedUsername = sessionData?.resolved_fields?.guacamole_username || "";
    const resolvedDomain = sessionData?.resolved_fields?.guacamole_domain || "";
    authTokenRef.current = clientSession.auth_token;
    handledClosureAuthTokenRef.current = null;
    debugLog("connect-session-ready", {
      authToken: maskDebugValue(clientSession.auth_token),
      resumeTunnelUuid: clientSession.resume_tunnel_uuid ?? "<none>",
      resolvedTargetHost: resolvedTargetHost ?? "<none>",
      resolvedConnectionName: resolvedConnectionName ?? "<none>",
    });
    onUpdate({
      title: resolvedTitle,
      readOnly: Boolean(sessionData?.read_only ?? session.readOnly),
      error: null,
      hint: null,
      targetHost: resolvedTargetHost,
      connectionName: resolvedConnectionName,
      clientSession: createPersistedClientSession(clientSession),
    });
    latestPersistedClientSessionRef.current = createPersistedClientSession(clientSession);
    persistLatestSessionPatch({
      title: resolvedTitle,
      readOnly: Boolean(sessionData?.read_only ?? session.readOnly),
      error: null,
      hint: null,
      targetHost: resolvedTargetHost,
      connectionName: resolvedConnectionName,
      clientSession: latestPersistedClientSessionRef.current,
    });

    const websocketTunnelUrl = clientSession.tunnels.websocket;
    const httpTunnelUrl = clientSession.tunnels.http;
    const resumeTunnelUuid = clientSession.resume_tunnel_uuid;
    const shouldUseHttpResume = Boolean(usingStoredTunnelResume && resumeTunnelUuid && httpTunnelUrl);
    resumeTunnelUuidRef.current = resumeTunnelUuid ?? null;
    if (!websocketTunnelUrl && !httpTunnelUrl) {
      connectInFlightRef.current = false;
      debugLog("connect-missing-tunnel");
      onUpdate({
        status: "needs_configuration",
        error: "No Guacamole tunnel endpoint is configured.",
        clientSession: null,
        connected: false,
      });
      return;
    }

    const configuredTunnels: Array<InstanceType<typeof Guacamole.HTTPTunnel> | InstanceType<typeof Guacamole.WebSocketTunnel>> = [];
    if (shouldUseHttpResume && httpTunnelUrl) {
      const httpTunnel = new Guacamole.HTTPTunnel(httpTunnelUrl);
      httpTunnel.receiveTimeout = 120000;
      httpTunnel.unstableThreshold = 10000;
      configuredTunnels.push(httpTunnel);
    } else if (websocketTunnelUrl) {
      const websocketTunnel = new Guacamole.WebSocketTunnel(websocketTunnelUrl);
      websocketTunnel.receiveTimeout = 120000;
      websocketTunnel.unstableThreshold = 10000;
      configuredTunnels.push(websocketTunnel);
    }
    if (httpTunnelUrl && !shouldUseHttpResume) {
      const httpTunnel = new Guacamole.HTTPTunnel(httpTunnelUrl);
      httpTunnel.receiveTimeout = 120000;
      httpTunnel.unstableThreshold = 10000;
      configuredTunnels.push(httpTunnel);
    }

    const tunnel = configuredTunnels.length === 1
      ? configuredTunnels[0]
      : new Guacamole.ChainedTunnel(...configuredTunnels);

    debugLog("connect-tunnel-selected", {
      websocket: websocketTunnelUrl || "<none>",
      http: httpTunnelUrl || "<none>",
      resumeTunnelUuid: resumeTunnelUuid ?? "<none>",
      mode: shouldUseHttpResume
        ? "http-resume"
        : websocketTunnelUrl && httpTunnelUrl
          ? "websocket+http-fallback"
          : websocketTunnelUrl
            ? "websocket"
            : "http",
    });

    const client = new Guacamole.Client(tunnel);
    const isCurrentConnection = () => (
      connectGenerationRef.current === connectGeneration
      && clientRef.current === client
      && tunnelRef.current === tunnel
    );

    const displayElement = client.getDisplay().getElement() as HTMLElement;
    displayElement.tabIndex = 0;
    displayElement.setAttribute("aria-label", "Remote desktop session");
    keyboardTargetRef.current = displayElement;
    displayElement.addEventListener("focus", () => {
      if (!isCurrentConnection()) {
        return;
      }
      debugLog("display-focus", {
        activeElement: document.activeElement instanceof HTMLElement ? document.activeElement.tagName : "<none>",
      });
    });
    displayElement.addEventListener("blur", () => {
      if (!isCurrentConnection()) {
        return;
      }
      const activeElementTagName = document.activeElement instanceof HTMLElement ? document.activeElement.tagName : "<none>";
      debugLog("display-blur", {
        activeElement: activeElementTagName,
      });

      if (activeElementTagName === "BODY") {
        maintainCaptureAfterBlur("display-blur-to-body");
      }
    });

    host.replaceChildren(displayElement);
    displayElement.classList.add("block", "max-w-none");
    displayElement.style.position = "absolute";
    displayElement.style.left = "auto";
    displayElement.style.top = "auto";
    displayElement.style.right = "0";
    displayElement.style.bottom = "0";
    displayElement.style.transform = "";
    displayElement.style.margin = "0";

    const persistedDisplayState = resumeTunnelUuid
      ? loadPersistedDisplayState(clientSession.auth_token, resumeTunnelUuid)
      : null;
    if (persistedDisplayState) {
      try {
        const snapshotCapableClient = getSnapshotCapableClient(client);
        if (!snapshotCapableClient) {
          throw new Error("Guacamole client state import is unavailable");
        }
        await new Promise<void>((resolve) => {
          snapshotCapableClient.importState(persistedDisplayState, () => {
            resolve();
          });
        });
        fitDisplayToHost(client, host);
        debugLog("display-state-imported", {
          authToken: maskDebugValue(clientSession.auth_token),
          resumeTunnelUuid,
        });
      } catch (error) {
        debugLog("display-state-import-failed", {
          authToken: maskDebugValue(clientSession.auth_token),
          resumeTunnelUuid,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    const stateLabels: Record<number, string> = {
      [Guacamole.Client.State.IDLE]: "idle",
      [Guacamole.Client.State.CONNECTING]: "connecting",
      [Guacamole.Client.State.WAITING]: "waiting",
      [Guacamole.Client.State.CONNECTED]: "connected",
      [Guacamole.Client.State.DISCONNECTING]: "disconnecting",
      [Guacamole.Client.State.DISCONNECTED]: "disconnected",
    };

    const retryWithoutResume = () => {
      if (!isCurrentConnection() || !resumeTunnelUuid || retriedFreshSession || hasConnectedRef.current) {
        return false;
      }

      retriedFreshSession = true;
      debugLog("retry-without-resume", {
        authToken: maskDebugValue(clientSession.auth_token),
        resumeTunnelUuid,
        nextAttempt: attemptedStoredTunnelResume ? "backend-refresh-tunnel" : "fresh-session",
      });
      onUpdate({
        clientSession: attemptedStoredTunnelResume ? latestPersistedClientSessionRef.current : null,
        status: "restarting_session",
        error: null,
        connected: false,
      });
      skipStoredTunnelResumeRef.current = attemptedStoredTunnelResume;
      forceFreshOnNextConnectRef.current = !attemptedStoredTunnelResume;
      refreshTunnelOnNextConnectRef.current = attemptedStoredTunnelResume;
      setReconnectRequestId((current) => current + 1);
      disconnectClient({ revoke: false, disconnectTransport: true });
      return true;
    };

    client.onstatechange = (state) => {
      if (!isCurrentConnection()) {
        return;
      }
      debugLog("client-state-change", {
        state,
        label: stateLabels[state] || `state:${state}`,
        hasConnected: hasConnectedRef.current,
      });
      if (state === Guacamole.Client.State.CONNECTED) {
        hasConnectedRef.current = true;
        setRequiredPrompt(null);
        captureDisplayState("connected");
        window.requestAnimationFrame(() => {
          focusRemoteDisplay();
        });
      }
      clientStateRef.current = state;
      if (state === Guacamole.Client.State.DISCONNECTED) {
        void handleUnexpectedClosure({
          authToken: authTokenRef.current,
          fallbackStatus: "disconnected",
          fallbackError: "The remote desktop session was disconnected.",
          fallbackTargetHost: resolvedTargetHost,
        });
        return;
      }
      if (state === Guacamole.Client.State.DISCONNECTING) {
        void refreshDiagnostics(resolvedTargetHost);
      }
      onUpdate({
        status: stateLabels[state] || `state:${state}`,
        connected: state === Guacamole.Client.State.CONNECTED,
        error: state === Guacamole.Client.State.CONNECTED ? null : undefined,
      });
    };

    client.onerror = (status) => {
      if (!isCurrentConnection()) {
        return;
      }
      debugLog("client-error", {
        code: status.code ?? "unknown",
        message: status.message || "<none>",
      });
      if (retryWithoutResume()) {
        return;
      }
      void handleUnexpectedClosure({
        authToken: authTokenRef.current,
        fallbackStatus: "connect_failed",
        fallbackError: status.message || `Guacamole error ${status.code ?? "unknown"}`,
        fallbackTargetHost: resolvedTargetHost,
      });
    };

    client.onrequired = (parameters) => {
      if (!isCurrentConnection()) {
        return;
      }

      const nextParameters = parameters.filter((parameter) => Boolean(parameter?.trim()));
      const nextValues: Record<string, string> = {};
      for (const parameter of nextParameters) {
        const normalizedName = parameter.toLowerCase();
        if (normalizedName.includes("user")) {
          nextValues[parameter] = resolvedUsername;
        } else if (normalizedName.includes("domain")) {
          nextValues[parameter] = resolvedDomain;
        } else {
          nextValues[parameter] = "";
        }
      }

      debugLog("client-required", {
        parameters: nextParameters,
      });
      setRequiredPrompt({
        parameters: nextParameters,
        values: nextValues,
        submitting: false,
        error: null,
      });
      onUpdate({
        status: "credentials_required",
        connected: false,
        error: "The remote desktop server requested additional credentials.",
      });
    };

    tunnel.onstatechange = (state) => {
      if (!isCurrentConnection()) {
        return;
      }
      debugLog("tunnel-state-change", {
        state,
        hasConnected: hasConnectedRef.current,
      });
      if (state === 2 && !hasConnectedRef.current) {
        if (retryWithoutResume()) {
          return;
        }
        void handleUnexpectedClosure({
          authToken: authTokenRef.current,
          fallbackStatus: "tunnel_closed",
          fallbackError: "The remote desktop tunnel was closed.",
          fallbackTargetHost: resolvedTargetHost,
        });
        return;
      }
      if (state === 2 && hasConnectedRef.current) {
        void handleUnexpectedClosure({
          authToken: authTokenRef.current,
          fallbackStatus: "tunnel_closed",
          fallbackError: "The remote desktop tunnel was closed.",
          fallbackTargetHost: resolvedTargetHost,
        });
      }
    };

    tunnel.onerror = (status) => {
      if (!isCurrentConnection()) {
        return;
      }
      debugLog("tunnel-error", {
        code: status.code ?? "unknown",
        message: status.message || "<none>",
        hasConnected: hasConnectedRef.current,
      });
      if (!hasConnectedRef.current) {
        if (retryWithoutResume()) {
          return;
        }
        void handleUnexpectedClosure({
          authToken: authTokenRef.current,
          fallbackStatus: "tunnel_closed",
          fallbackError: status.message || `Tunnel error ${status.code ?? "unknown"}`,
          fallbackTargetHost: resolvedTargetHost,
        });
        return;
      }

      void handleUnexpectedClosure({
        authToken: authTokenRef.current,
        fallbackStatus: "tunnel_closed",
        fallbackError: status.message || `Tunnel error ${status.code ?? "unknown"}`,
        fallbackTargetHost: resolvedTargetHost,
      });
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
      if (!isCurrentConnection()) {
        return;
      }
      fitDisplayToHost(client, host);
    };

    const mouse = new Guacamole.Mouse(displayElement);
    mouse.onmousedown = mouse.onmouseup = mouse.onmousemove = (state) => {
      if (!isCurrentConnection() || !activeRef.current || session.readOnly) {
        return;
      }
      setKeyboardCaptureEnabled(true, "mouse-interaction");
      client.sendMouseState(state, true);
    };

    const keyboard = new Guacamole.Keyboard(document);
    keyboardRef.current = keyboard;
    keyboard.onkeydown = (keysym) => {
      if (!isCurrentConnection() || !activeRef.current || session.readOnly || !keyboardCaptureEnabledRef.current) {
        debugLog("keyboard-keydown-ignored", {
          keysym,
          activeElement: document.activeElement instanceof HTMLElement ? document.activeElement.tagName : "<none>",
          readOnly: session.readOnly,
          captureEnabled: keyboardCaptureEnabledRef.current,
        });
        return true;
      }
      client.sendKeyEvent(1, keysym);
      return false;
    };
    keyboard.onkeyup = (keysym) => {
      if (!isCurrentConnection() || !activeRef.current || session.readOnly || !keyboardCaptureEnabledRef.current) {
        debugLog("keyboard-keyup-ignored", {
          keysym,
          activeElement: document.activeElement instanceof HTMLElement ? document.activeElement.tagName : "<none>",
          readOnly: session.readOnly,
          captureEnabled: keyboardCaptureEnabledRef.current,
        });
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
      connectInFlightRef.current = false;
      debugLog("connect-generation-changed-after-init", {
        authToken: maskDebugValue(clientSession.auth_token),
      });
      client.disconnect();
      tunnel.disconnect();
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
      if ((shouldUseHttpResume || !websocketTunnelUrl) && resumeTunnelUuid) {
        params.set("GUAC_RESUME_TUNNEL", resumeTunnelUuid);
      }

      debugLog("client-connect", {
        authToken: maskDebugValue(clientSession.auth_token),
        resumeTunnelUuid: resumeTunnelUuid ?? "<none>",
        width: connectWidth,
        height: connectHeight,
        dpi: connectDpi,
      });
      client.connect(params.toString());
      connectInFlightRef.current = false;
      sendResize();
    } catch (error) {
      connectInFlightRef.current = false;
      debugLog("client-connect-failed", {
        error: error instanceof Error ? error.message : String(error),
      });
      onUpdate({
        status: "connect_failed",
        error: error instanceof Error ? error.message : String(error),
        clientSession: null,
        connected: false,
      });
    }
  });

  useEffect(() => {
    if (!session.connected) {
      return;
    }

    const intervalId = window.setInterval(() => {
      captureDisplayState("interval");
    }, 5000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [session.connected, session.instanceId]);

  useEffect(() => {
    const blockedStatuses = new Set([
      "session_closed",
      "connect_failed",
      "tunnel_closed",
      "disconnected",
      "credentials_required",
      "server_disconnected",
    ]);
    const shouldAutoConnect = !blockedStatuses.has(session.status);
    const shouldReconnectInBackground = shouldAutoConnect && !active && Boolean(persistedClientAuthToken);

    if (!shouldAutoConnect) {
      debugLog("connect-blocked-status", {
        status: session.status,
      });
      return;
    }

    if (!active && !shouldReconnectInBackground) {
      debugLog("connect-deferred-inactive");
      return;
    }

    if (shouldReconnectInBackground) {
      debugLog("connect-background-resume", {
        persistedAuthToken: maskDebugValue(persistedClientAuthToken),
        persistedResumeTunnel: persistedClientResumeTunnel || "<none>",
      });
    }

    if (
      clientRef.current
      && tunnelRef.current
      && clientStateRef.current !== Guacamole.Client.State.DISCONNECTED
      && clientStateRef.current !== Guacamole.Client.State.IDLE
    ) {
      debugLog("connect-skipped-existing-live-session", {
        clientState: clientStateRef.current,
      });
      window.requestAnimationFrame(() => {
        focusRemoteDisplay();
        sendResizeRef.current();
      });
      return;
    }

    const forceFresh = forceFreshOnNextConnectRef.current;
    forceFreshOnNextConnectRef.current = false;
    hydratedPersistedSessionRef.current = false;
    void connectClient({ forceFresh });
  }, [active, debugLog, focusRemoteDisplay, persistedClientAuthToken, persistedClientResumeTunnel, reconnectRequestId, session.instanceId, session.status]);

  useEffect(() => {
    return () => {
      const shouldRevoke = !pageUnloadingRef.current;

      if (!shouldRevoke) {
        disconnectClient({
          revoke: false,
          disconnectTransport: false,
        });
        return;
      }

      const cleanupTimerId = window.setTimeout(() => {
        pendingViewportCleanupByInstanceId.delete(session.instanceId);
        disconnectClient({
          revoke: true,
          disconnectTransport: true,
        });
      }, 700);

      pendingViewportCleanupByInstanceId.set(session.instanceId, cleanupTimerId);
    };
  }, [disconnectClient, session.instanceId]);

  useEffect(() => {
    if (!active) {
      setKeyboardCaptureEnabled(false, "inactive-session");
      return;
    }

    if (!displayHostRef.current) {
      return;
    }

    const handle = window.requestAnimationFrame(() => {
      focusRemoteDisplay();
      sendResizeRef.current();
    });

    return () => {
      window.cancelAnimationFrame(handle);
    };
  }, [active, focusRemoteDisplay, session.connected, session.instanceId, setKeyboardCaptureEnabled]);

  useEffect(() => {
    if (!active || !session.connected) {
      return;
    }

    const timeouts = [0, 180, 520].map((delay) => window.setTimeout(() => {
      sendResizeRef.current();
    }, delay));

    return () => {
      for (const timeout of timeouts) {
        window.clearTimeout(timeout);
      }
    };
  }, [active, session.connected, session.fullscreen, session.minimized]);

  useEffect(() => {
    if (!active) {
      return;
    }

    const handlePointerDown = (event: PointerEvent) => {
      const host = displayHostRef.current;
      if (!host) {
        return;
      }

      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }

      if (host.contains(target)) {
        setKeyboardCaptureEnabled(true, "pointer-inside-display");
        return;
      }

      if (document.activeElement === document.body && hasConnectedRef.current) {
        debugLog("pointer-outside-display-ignored", {
          activeElement: "BODY",
        });
        maintainCaptureAfterBlur("pointer-outside-while-body-focused");
        return;
      }

      setKeyboardCaptureEnabled(false, "pointer-outside-display");
    };

    document.addEventListener("pointerdown", handlePointerDown, true);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown, true);
    };
  }, [active, debugLog, maintainCaptureAfterBlur, setKeyboardCaptureEnabled]);

  return (
    <div className="relative h-full w-full">
      <div
        ref={displayHostRef}
        tabIndex={0}
        onMouseDown={() => {
          if (active) {
            setKeyboardCaptureEnabled(true, "viewport-mousedown");
            focusRemoteDisplay();
          }
        }}
        className="absolute inset-0 overflow-hidden bg-slate-950 select-none outline-none"
      />
      {requiredPrompt && (
        <GuacamoleRequiredPrompt
          parameters={requiredPrompt.parameters}
          values={requiredPrompt.values}
          submitting={requiredPrompt.submitting}
          error={requiredPrompt.error}
          targetHost={session.targetHost}
          onValueChange={updateRequiredPromptValue}
          onSubmit={submitRequiredPrompt}
          onCancel={cancelRequiredPrompt}
        />
      )}
    </div>
  );
}