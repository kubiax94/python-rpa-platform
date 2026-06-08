"use client";

import { startTransition, useEffect, useRef, useState, useCallback } from "react";
import type { AgentsMap, CommandPayload } from "@/types/agent";
import { BACKEND_DISCONNECTED_EVENT } from "@/components/guacamole/utils";
import { API_BASE, AUTH_SESSION_INVALID_EVENT, buildFrontendWebSocketUrl, fetchJSON, getAccessToken, withAuthHeaders } from "@/lib/auth";

type AgentRegistryRow = {
  id: string;
  hostname?: string | null;
  display_name?: string | null;
  connection_status?: string | null;
  last_seen_at?: number | null;
};

export type ScreenshotTargetType = "process" | "desktop";

export interface ProcessScreenshotState {
  agentId: string;
  targetType: ScreenshotTargetType;
  pid?: number;
  hwnd?: number;
  sessionId?: number;
  requestId: string;
  status: "pending" | "completed" | "failed";
  imageBase64?: string;
  imageFormat?: string;
  windowTitle?: string;
  error?: string;
  capturedAt?: number;
}

type FrontendWsMessage =
  | { kind: "auth_ok" }
  | { kind: "agents_snapshot"; data: AgentsMap }
  | { kind: "task_event"; data: Record<string, unknown> }
  | {
      kind: "process_screenshot";
      data: {
        agent_id?: string;
        target_type?: ScreenshotTargetType;
        pid?: number;
        hwnd?: number;
        session_id?: number;
        request_id?: string;
        status?: "completed" | "failed";
        image_base64?: string;
        image_format?: string;
        window_title?: string;
        error?: string;
        captured_at?: number;
      };
    }
  | AgentsMap;

function isAgentSnapshotMessage(message: FrontendWsMessage): message is { kind: "agents_snapshot"; data: AgentsMap } {
  return typeof message === "object" && message !== null && "kind" in message && message.kind === "agents_snapshot";
}

function isAuthOkMessage(message: FrontendWsMessage): message is { kind: "auth_ok" } {
  return typeof message === "object" && message !== null && "kind" in message && message.kind === "auth_ok";
}

function isTaskEventMessage(message: FrontendWsMessage): message is { kind: "task_event"; data: Record<string, unknown> } {
  return typeof message === "object" && message !== null && "kind" in message && message.kind === "task_event";
}

function isProcessScreenshotMessage(
  message: FrontendWsMessage
): message is Extract<FrontendWsMessage, { kind: "process_screenshot" }> {
  return typeof message === "object" && message !== null && "kind" in message && message.kind === "process_screenshot";
}

function isLegacyAgentsMap(message: FrontendWsMessage): message is AgentsMap {
  return typeof message === "object" && message !== null && !("kind" in message) && !("type" in message);
}

function stripDynamicAgentState(agents: AgentsMap): AgentsMap {
  return Object.fromEntries(
    Object.entries(agents).map(([agentId, state]) => [
      agentId,
      {
        ...(state.__agent_metrics ? { __agent_metrics: state.__agent_metrics } : {}),
        ...(state.__agent_connection
          ? {
              __agent_connection: {
                ...state.__agent_connection,
                connected: false,
              },
            }
          : {}),
      },
    ])
  );
}

function mergeRegistryAgents(agents: AgentsMap, registryRows: AgentRegistryRow[]): AgentsMap {
  if (registryRows.length === 0) {
    return agents;
  }

  const merged: AgentsMap = { ...agents };

  for (const row of registryRows) {
    const agentId = String(row.id || "").trim();
    if (!agentId) {
      continue;
    }

    const current = merged[agentId] || {};
    const hostname = String(row.hostname || row.display_name || "").trim();
    const metrics = current.__agent_metrics ? { ...current.__agent_metrics } : {};
    const connection = current.__agent_connection ? { ...current.__agent_connection } : {};

    if (!metrics.hostname && hostname) {
      metrics.hostname = hostname;
    }
    if (typeof connection.connected !== "boolean") {
      connection.connected = row.connection_status === "online";
    }
    if (typeof connection.last_seen !== "number" && typeof row.last_seen_at === "number") {
      connection.last_seen = row.last_seen_at;
    }
    if (!connection.source) {
      connection.source = "registry";
    }

    merged[agentId] = {
      ...current,
      ...(Object.keys(metrics).length > 0 ? { __agent_metrics: metrics } : {}),
      ...(Object.keys(connection).length > 0 ? { __agent_connection: connection } : {}),
    };
  }

  return merged;
}

function markRuntimeAgents(snapshot: AgentsMap): AgentsMap {
  return Object.fromEntries(
    Object.entries(snapshot).map(([agentId, state]) => {
      const connection = state.__agent_connection ? { ...state.__agent_connection, source: "runtime" as const } : { source: "runtime" as const };
      return [
        agentId,
        {
          ...state,
          __agent_connection: connection,
        },
      ];
    })
  );
}

function reconcileRegistryAgents(agents: AgentsMap, registryRows: AgentRegistryRow[]): AgentsMap {
  const merged = mergeRegistryAgents(agents, registryRows);
  const registryIds = new Set(registryRows.map((row) => String(row.id || "").trim()).filter(Boolean));

  for (const [agentId, state] of Object.entries(merged)) {
    if (registryIds.has(agentId)) {
      continue;
    }
    if (state.__agent_connection?.source === "registry") {
      delete merged[agentId];
    }
  }

  return merged;
}

async function classifyFrontendSocketClose(accessToken: string): Promise<"auth-invalid" | "backend-online" | "backend-offline"> {
  if (!accessToken) {
    return "auth-invalid";
  }

  try {
    const response = await fetch(`${API_BASE}/api/users/me`, {
      headers: withAuthHeaders(),
      cache: "no-store",
    });

    if (response.status === 401) {
      return "auth-invalid";
    }

    return response.ok ? "backend-online" : "backend-offline";
  } catch {
    return "backend-offline";
  }
}

export function useAgentSocket(enabled = true) {
  const [agents, setAgents] = useState<AgentsMap>({});
  const [connected, setConnected] = useState(false);
  const [latestScreenshotEvent, setLatestScreenshotEvent] = useState<ProcessScreenshotState | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const initialConnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const manualClose = useRef(false);
  const registryRowsRef = useRef<AgentRegistryRow[]>([]);

  const refreshRegistryAgents = useCallback(async () => {
    if (!enabled || !getAccessToken()) {
      registryRowsRef.current = [];
      return;
    }

    try {
      const rows = await fetchJSON<AgentRegistryRow[]>(`${API_BASE}/api/agent-registry`);
      registryRowsRef.current = rows;
      startTransition(() => {
        setAgents((current) => reconcileRegistryAgents(current, rows));
      });
    } catch (error) {
      console.error("[useAgentSocket] Failed to refresh agent registry:", error);
    }
  }, [enabled]);

  const closeSocket = useCallback(() => {
    const currentSocket = ws.current;
    if (!currentSocket) {
      return;
    }

    currentSocket.onopen = null;
    currentSocket.onmessage = null;
    currentSocket.onclose = null;
    currentSocket.onerror = null;

    try {
      currentSocket.close();
    } catch {
      // Ignore cleanup races during development remounts.
    }

    ws.current = null;
  }, []);

  const connect = useCallback(function connectSocket() {
    if (!enabled) {
      return;
    }

    if (ws.current?.readyState === WebSocket.OPEN) return;
    if (ws.current?.readyState === WebSocket.CONNECTING) return;

    const accessToken = getAccessToken();
    if (!accessToken) {
      setConnected(false);
      return;
    }

    const frontendWebSocketUrl = buildFrontendWebSocketUrl();
    console.log("[WS] Opening frontend websocket:", frontendWebSocketUrl);
    const socket = new WebSocket(frontendWebSocketUrl);
    manualClose.current = false;

    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "auth", access_token: accessToken }));
      console.log("[WS] Connected to backend transport, authenticating...");
    };

    socket.onmessage = (event) => {
      try {
        const message: FrontendWsMessage = JSON.parse(event.data);

        if (isAuthOkMessage(message)) {
          setConnected(true);
          void refreshRegistryAgents();
          return;
        }

        if (isAgentSnapshotMessage(message)) {
          startTransition(() => {
            setAgents(reconcileRegistryAgents(markRuntimeAgents(message.data), registryRowsRef.current));
          });
          return;
        }

        if (isTaskEventMessage(message)) {
          return;
        }

        if (isProcessScreenshotMessage(message)) {
          const agentId = message.data.agent_id;
          if (!agentId) {
            return;
          }

          startTransition(() => {
            setLatestScreenshotEvent({
              agentId,
              targetType: message.data.target_type ?? "process",
              pid: typeof message.data.pid === "number" ? message.data.pid : undefined,
              hwnd: typeof message.data.hwnd === "number" ? message.data.hwnd : undefined,
              sessionId: typeof message.data.session_id === "number" ? message.data.session_id : undefined,
              requestId: message.data.request_id ?? "",
              status: message.data.status ?? "failed",
              imageBase64: message.data.image_base64,
              imageFormat: message.data.image_format ?? "png",
              windowTitle: message.data.window_title,
              error: message.data.error,
              capturedAt: message.data.captured_at,
            });
          });
          return;
        }

        if (isLegacyAgentsMap(message)) {
          startTransition(() => {
            setAgents(reconcileRegistryAgents(markRuntimeAgents(message), registryRowsRef.current));
          });
          return;
        }

        console.warn("[WS] Ignoring unsupported message:", message);
      } catch (e) {
        console.error("[WS] Failed to parse message:", e);
      }
    };

    socket.onclose = (event) => {
      setConnected(false);
      if (manualClose.current) {
        return;
      }

      startTransition(() => {
        setAgents((current) => stripDynamicAgentState(current));
      });

      void (async () => {
        const closeKind = event.code === 4401
          ? "auth-invalid"
          : await classifyFrontendSocketClose(accessToken);

        if (manualClose.current) {
          return;
        }

        if (closeKind === "auth-invalid") {
          console.warn("[WS] Session no longer valid; sign-in required.", { code: event.code, reason: event.reason });
          window.dispatchEvent(new CustomEvent(AUTH_SESSION_INVALID_EVENT));
          return;
        }

        if (closeKind === "backend-offline") {
          window.dispatchEvent(new CustomEvent(BACKEND_DISCONNECTED_EVENT));
        }

        console.warn("[WS] Closed, reconnecting in 3s...", {
          code: event.code,
          reason: event.reason,
          backendStatus: closeKind,
        });
        reconnectTimer.current = setTimeout(connectSocket, 3000);
      })();
    };

    socket.onerror = (err) => {
      if (manualClose.current) {
        return;
      }
      console.error("[WS] Transport error:", err);
    };

    ws.current = socket;
  }, [enabled, refreshRegistryAgents]);

  useEffect(() => {
    if (!enabled) {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      if (initialConnectTimer.current) {
        clearTimeout(initialConnectTimer.current);
        initialConnectTimer.current = null;
      }
      manualClose.current = true;
      setConnected(false);
      closeSocket();
      return;
    }

    initialConnectTimer.current = setTimeout(() => {
      initialConnectTimer.current = null;
      connect();
    }, 180);

    return () => {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      if (initialConnectTimer.current) {
        clearTimeout(initialConnectTimer.current);
        initialConnectTimer.current = null;
      }
      manualClose.current = true;
      closeSocket();
    };
  }, [closeSocket, connect, enabled]);

  useEffect(() => {
    if (!enabled) {
      registryRowsRef.current = [];
      return;
    }

    void refreshRegistryAgents();
    const intervalId = window.setInterval(() => {
      void refreshRegistryAgents();
    }, 15000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [enabled, refreshRegistryAgents]);

  const sendCommand = useCallback((type: string, data: Record<string, unknown>) => {
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) {
      console.error("[WS] Cannot send — not connected");
      return;
    }
    const payload: CommandPayload = { type, data };
    ws.current.send(JSON.stringify(payload));
  }, []);

  const requestProcessScreenshot = useCallback((agentId: string, pid: number, hwnd?: number) => {
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    sendCommand("capture_process_screenshot", {
      agent_id: agentId,
      target_type: "process",
      pid,
      ...(hwnd != null ? { hwnd } : {}),
      request_id: requestId,
    });

    return {
      agentId,
      targetType: "process" as const,
      pid,
      ...(hwnd != null ? { hwnd } : {}),
      requestId,
    };
  }, [sendCommand]);

  const requestDesktopScreenshot = useCallback((agentId: string, sessionId: number) => {
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    sendCommand("capture_process_screenshot", {
      agent_id: agentId,
      target_type: "desktop",
      session_id: sessionId,
      request_id: requestId,
    });

    return {
      agentId,
      targetType: "desktop" as const,
      sessionId,
      requestId,
    };
  }, [sendCommand]);

  const watchProcessManager = useCallback((agentId: string) => {
    sendCommand("watch_process_manager", { agent_id: agentId });
  }, [sendCommand]);

  const unwatchProcessManager = useCallback((agentId: string) => {
    sendCommand("unwatch_process_manager", { agent_id: agentId });
  }, [sendCommand]);

  return { agents, connected, sendCommand, latestScreenshotEvent, requestProcessScreenshot, requestDesktopScreenshot, watchProcessManager, unwatchProcessManager, refreshAgents: refreshRegistryAgents };
}
