"use client";

import { startTransition, useEffect, useRef, useState, useCallback } from "react";
import type { AgentsMap, CommandPayload } from "@/types/agent";

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

function getWsUrl(): string {
  if (typeof window === "undefined") return "ws://192.168.1.10:8765/frontend";
  const host = "192.168.1.10";
  return `ws://${host}:8765/frontend`;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || getWsUrl();

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

export function useAgentSocket() {
  const [agents, setAgents] = useState<AgentsMap>({});
  const [connected, setConnected] = useState(false);
  const [latestScreenshotEvent, setLatestScreenshotEvent] = useState<ProcessScreenshotState | null>(null);
  const ws = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const connect = useCallback(function connectSocket() {
    if (ws.current?.readyState === WebSocket.OPEN) return;

    const socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      setConnected(true);
      console.log("[WS] Connected to backend");
    };

    socket.onmessage = (event) => {
      try {
        const message: FrontendWsMessage = JSON.parse(event.data);

        if (isAgentSnapshotMessage(message)) {
          startTransition(() => {
            setAgents(message.data);
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
            setAgents(message);
          });
          return;
        }

        console.warn("[WS] Ignoring unsupported message:", message);
      } catch (e) {
        console.error("[WS] Failed to parse message:", e);
      }
    };

    socket.onclose = () => {
      setConnected(false);
      startTransition(() => {
        setAgents((current) => stripDynamicAgentState(current));
      });
      console.log("[WS] Disconnected, reconnecting in 3s...");
      reconnectTimer.current = setTimeout(connectSocket, 3000);
    };

    socket.onerror = (err) => {
      console.error("[WS] Error:", err);
      startTransition(() => {
        setAgents((current) => stripDynamicAgentState(current));
      });
      socket.close();
    };

    ws.current = socket;
  }, []);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
      }
      ws.current?.close();
    };
  }, [connect]);

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

  return { agents, connected, sendCommand, latestScreenshotEvent, requestProcessScreenshot, requestDesktopScreenshot, watchProcessManager, unwatchProcessManager };
}
