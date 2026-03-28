"use client";

import { useEffect, useEffectEvent, useMemo, useRef, useState } from "react";
import Guacamole from "guacamole-common-js";
import {
  useGuacamoleSession,
  type GuacamoleClientSession,
} from "@/hooks/useGuacamole";

interface GuacamolePanelProps {
  agentId: string;
  active?: boolean;
}

type WorkspaceSession = {
  id: string;
  title: string;
  status: string;
  error: string | null;
  connected: boolean;
  minimized: boolean;
  fullscreen: boolean;
  launchedAt: number;
};

interface SessionViewportProps {
  agentId: string;
  workspaceSession: WorkspaceSession;
  active: boolean;
  createClientSession: () => Promise<GuacamoleClientSession | null>;
  revokeClientSession: (authToken: string | null | undefined) => Promise<void>;
  onUpdate: (sessionId: string, patch: Partial<WorkspaceSession>) => void;
}

function InfoRow({ label, value }: { label: string; value?: string }) {
  return (
    <div className="flex items-center justify-between gap-4 text-sm">
      <span className="text-slate-400">{label}</span>
      <span className="font-mono text-slate-200 text-right break-all">{value || "-"}</span>
    </div>
  );
}

function getStatusBadgeClasses(session: WorkspaceSession) {
  if (session.connected) {
    return "bg-emerald-500/15 text-emerald-300";
  }
  if (session.status === "connecting" || session.status === "waiting" || session.status === "preparing") {
    return "bg-blue-500/15 text-blue-300";
  }
  if (session.error) {
    return "bg-rose-500/15 text-rose-300";
  }
  return "bg-amber-500/15 text-amber-300";
}

function createWorkspaceSession(agentId: string, title: string): WorkspaceSession {
  const randomId = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${agentId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  return {
    id: randomId,
    title,
    status: "queued",
    error: null,
    connected: false,
    minimized: false,
    fullscreen: true,
    launchedAt: Date.now(),
  };
}

function GuacamoleSessionViewport({
  agentId,
  workspaceSession,
  active,
  createClientSession,
  revokeClientSession,
  onUpdate,
}: SessionViewportProps) {
  const displayHostRef = useRef<HTMLDivElement | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const connectGenerationRef = useRef(0);
  const authTokenRef = useRef<string | null>(null);
  const activeRef = useRef(active);
  const hasConnectedRef = useRef(false);
  const sendResizeRef = useRef<() => void>(() => undefined);
  const clientRef = useRef<InstanceType<typeof Guacamole.Client> | null>(null);
  const tunnelRef = useRef<InstanceType<typeof Guacamole.HTTPTunnel> | InstanceType<typeof Guacamole.WebSocketTunnel> | InstanceType<typeof Guacamole.ChainedTunnel> | null>(null);
  const keyboardRef = useRef<InstanceType<typeof Guacamole.Keyboard> | null>(null);
  const mouseRef = useRef<InstanceType<typeof Guacamole.Mouse> | null>(null);

  useEffect(() => {
    activeRef.current = active;
  }, [active]);

  const getDisplayProfile = (session: NonNullable<GuacamoleClientSession["client_session"]>) => {
    const profile = session.display;
    if (profile.mode === "fixed" && profile.width && profile.height) {
      return {
        width: profile.width,
        height: profile.height,
        dpi: profile.dpi || 96,
      };
    }

    return null;
  };

  const disconnectClient = useEffectEvent(() => {
    connectGenerationRef.current += 1;
    hasConnectedRef.current = false;
    const authToken = authTokenRef.current;
    authTokenRef.current = null;
    resizeObserverRef.current?.disconnect();
    resizeObserverRef.current = null;
    keyboardRef.current = null;
    mouseRef.current = null;

    if (clientRef.current) {
      clientRef.current.disconnect();
      clientRef.current = null;
    }

    if (tunnelRef.current) {
      tunnelRef.current.disconnect();
      tunnelRef.current = null;
    }

    if (displayHostRef.current) {
      displayHostRef.current.replaceChildren();
    }

    if (authToken) {
      void revokeClientSession(authToken);
    }
  });

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

  const connectClient = useEffectEvent(async () => {
    const host = displayHostRef.current;
    if (!host) {
      return;
    }

    const connectGeneration = connectGenerationRef.current + 1;
    connectGenerationRef.current = connectGeneration;
    hasConnectedRef.current = false;
    onUpdate(workspaceSession.id, {
      status: "preparing",
      error: null,
      connected: false,
    });

    const session = await createClientSession();
    if (connectGenerationRef.current !== connectGeneration) {
      if (session?.client_session?.auth_token) {
        await revokeClientSession(session.client_session.auth_token);
      }
      return;
    }

    if (!session?.client_session) {
      onUpdate(workspaceSession.id, {
        status: session?.status ?? "needs_configuration",
        error: session?.warnings?.[0] ?? "Brak skonfigurowanej sesji Guacamole.",
        connected: false,
      });
      return;
    }

    const clientSession = session.client_session;
    authTokenRef.current = clientSession.auth_token;
    onUpdate(workspaceSession.id, {
      title: session.connection_label || workspaceSession.title,
    });

    const websocketTunnelUrl = clientSession.tunnels.websocket;
    const httpTunnelUrl = clientSession.tunnels.http;
    if (!websocketTunnelUrl && !httpTunnelUrl) {
      onUpdate(workspaceSession.id, {
        status: "needs_configuration",
        error: "Brak skonfigurowanego endpointu tunelu Guacamole.",
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
      onUpdate(workspaceSession.id, {
        status: stateLabels[state] || `state:${state}`,
        connected: state === Guacamole.Client.State.CONNECTED,
        error: state === Guacamole.Client.State.CONNECTED ? null : undefined,
      });
    };

    client.onerror = (status) => {
      onUpdate(workspaceSession.id, {
        error: status.message || `Guacamole error ${status.code ?? "unknown"}`,
        connected: false,
      });
    };

    tunnel.onstatechange = (state) => {
      if (state === 2 && !hasConnectedRef.current) {
        onUpdate(workspaceSession.id, {
          status: "tunnel_closed",
          connected: false,
        });
      }
    };

    tunnel.onerror = (status) => {
      if (!hasConnectedRef.current) {
        onUpdate(workspaceSession.id, {
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

    const keyboard = new Guacamole.Keyboard(document);
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
    mouseRef.current = mouse;
    keyboardRef.current = keyboard;

    if (connectGenerationRef.current !== connectGeneration) {
      client.disconnect();
      tunnel.disconnect();
      await revokeClientSession(clientSession.auth_token);
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
      onUpdate(workspaceSession.id, {
        status: "connect_failed",
        error: error instanceof Error ? error.message : String(error),
        connected: false,
      });
    }
  });

  useEffect(() => {
    void connectClient();
    return () => {
      disconnectClient();
    };
  }, [agentId, workspaceSession.id]);

  useEffect(() => {
    if (!active) {
      return;
    }

    const handle = window.requestAnimationFrame(() => {
      sendResizeRef.current();
    });

    return () => {
      window.cancelAnimationFrame(handle);
    };
  }, [active]);

  return (
    <div className="relative h-full w-full overflow-hidden rounded-lg border border-slate-700/80 bg-slate-950/95">
      <div ref={displayHostRef} className="flex h-full w-full items-center justify-center overflow-hidden bg-slate-950 select-none" />
      {!workspaceSession.connected && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-slate-950/55">
          <div className="rounded-md border border-slate-700 bg-slate-900/90 px-3 py-2 text-xs text-slate-300">
            {workspaceSession.error || workspaceSession.status || "Connecting"}
          </div>
        </div>
      )}
    </div>
  );
}

export function GuacamolePanel({ agentId, active = false }: GuacamolePanelProps) {
  const {
    data,
    loading,
    sessionLoading,
    createClientSession,
    revokeClientSession,
  } = useGuacamoleSession(agentId);
  const [workspaceSessions, setWorkspaceSessions] = useState<WorkspaceSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  const sessionsById = useMemo(
    () => Object.fromEntries(workspaceSessions.map((session) => [session.id, session])),
    [workspaceSessions],
  );
  const activeSession = activeSessionId ? sessionsById[activeSessionId] ?? null : null;
  const hasOpenSessions = workspaceSessions.length > 0;

  const patchSession = (sessionId: string, patch: Partial<WorkspaceSession>) => {
    setWorkspaceSessions((current) =>
      current.map((session) => (session.id === sessionId ? { ...session, ...patch } : session)),
    );
  };

  const focusSession = (sessionId: string, fullscreen = false) => {
    setActiveSessionId(sessionId);
    setWorkspaceSessions((current) =>
      current.map((session) =>
        session.id === sessionId
          ? { ...session, minimized: false, fullscreen }
          : fullscreen
            ? { ...session, fullscreen: false }
            : session,
      ),
    );
  };

  const minimizeSession = (sessionId: string) => {
    setWorkspaceSessions((current) =>
      current.map((session) =>
        session.id === sessionId
          ? { ...session, minimized: true, fullscreen: false }
          : session,
      ),
    );
    setActiveSessionId((current) => (current === sessionId ? null : current));
  };

  const closeSession = (sessionId: string) => {
    setWorkspaceSessions((current) => current.filter((session) => session.id !== sessionId));
    setActiveSessionId((current) => (current === sessionId ? null : current));
  };

  const openSession = () => {
    const title = data?.connection_label || "Remote Desktop";
    const nextSession = createWorkspaceSession(agentId, title);
    setWorkspaceSessions((current) => [...current, nextSession]);
    setActiveSessionId(nextSession.id);
  };

  const visibleWorkspaceSessionId = active && activeSession && !activeSession.minimized && !activeSession.fullscreen
    ? activeSession.id
    : null;
  const fullscreenSessionId = workspaceSessions.find((session) => session.fullscreen)?.id ?? null;
  const shouldRenderWorkspaceViewport = Boolean(visibleWorkspaceSessionId || fullscreenSessionId);

  if (!active && !hasOpenSessions) {
    return null;
  }

  return (
    <>
      <div className={active ? "space-y-4" : "hidden"}>
          <div className="rounded-xl border border-slate-700 bg-slate-800/30 overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-slate-700/70 px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold text-slate-100">Remote Desktop Workspace</h2>
                <p className="text-xs text-slate-500 mt-1">
                  Workspace sessions persist beyond the active tab. Exit from fullscreen minimizes the session instead of disconnecting it.
                </p>
              </div>
              <button
                onClick={openSession}
                disabled={!data?.connection_id}
                className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:border-cyan-400 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {sessionLoading ? "Connecting..." : "Connect"}
              </button>
            </div>

            <div className="grid gap-4 p-4 lg:grid-cols-[360px_minmax(0,1fr)]">
              <div className="space-y-4">
                <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4 space-y-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Available Connection</span>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${
                      data?.connection_id ? "bg-emerald-500/15 text-emerald-300" : "bg-amber-500/15 text-amber-300"
                    }`}>
                      {loading ? "Loading" : data?.connection_id ? "Ready" : "Unavailable"}
                    </span>
                  </div>
                  <InfoRow label="Connection" value={data?.connection_label} />
                  <InfoRow label="Source" value={data?.source} />
                  <InfoRow label="Display" value={data?.display?.mode === "fixed"
                    ? `${data.display.width}x${data.display.height} @ ${data.display.dpi} DPI`
                    : `Dynamic @ ${data?.display?.dpi ?? 96} DPI`} />
                  <InfoRow label="Hostname" value={data?.resolved_fields?.hostname} />
                  <InfoRow label="WebSocket tunnel" value={data?.tunnels?.websocket} />
                  <InfoRow label="HTTP tunnel" value={data?.tunnels?.http} />
                </div>

                <div className="rounded-lg border border-slate-700/80 bg-slate-900/60 p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Workspace Sessions</h3>
                    <span className="rounded-full bg-slate-800 px-2 py-1 text-[11px] text-slate-300">{workspaceSessions.length}</span>
                  </div>
                  <div className="space-y-2">
                    {workspaceSessions.length === 0 && (
                      <p className="text-sm text-slate-500">No open sessions yet. Click Connect to launch the first remote workspace session.</p>
                    )}
                    {workspaceSessions.map((session) => (
                      <div key={session.id} className="rounded-lg border border-slate-700 bg-slate-950/70 p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="text-sm font-medium text-slate-100">{session.title}</p>
                            <p className="mt-1 text-xs text-slate-500">Opened {new Date(session.launchedAt).toLocaleTimeString("pl-PL")}</p>
                          </div>
                          <span className={`rounded-full px-2 py-1 text-[11px] font-medium ${getStatusBadgeClasses(session)}`}>
                            {session.connected ? "Connected" : session.status}
                          </span>
                        </div>
                        {session.error && <p className="mt-2 text-xs text-rose-300">{session.error}</p>}
                        <div className="mt-3 flex flex-wrap gap-2">
                          <button
                            onClick={() => focusSession(session.id, false)}
                            className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                          >
                            Open In Workspace
                          </button>
                          <button
                            onClick={() => focusSession(session.id, true)}
                            className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                          >
                            Fullscreen
                          </button>
                          <button
                            onClick={() => minimizeSession(session.id)}
                            className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                          >
                            Minimize
                          </button>
                          <button
                            onClick={() => closeSession(session.id)}
                            className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-200 hover:border-rose-400"
                          >
                            Close
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {(!!data?.warnings?.length) && (
                  <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-4">
                    <h3 className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-300">Warnings</h3>
                    <div className="mt-3 space-y-2 text-sm text-amber-100/90">
                      {data?.warnings?.map((warning) => (
                        <p key={warning}>{warning}</p>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              <div className="rounded-lg border border-slate-700/80 bg-slate-950/95 min-h-[72vh] lg:min-h-[calc(100vh-14rem)] overflow-hidden">
                {shouldRenderWorkspaceViewport ? (
                  <div className="relative h-full w-full">
                    {workspaceSessions.map((session) => {
                      const isVisibleInWorkspace = session.id === visibleWorkspaceSessionId;
                      const isVisibleFullscreen = session.id === fullscreenSessionId && session.fullscreen;
                      const isMountedOffscreen = !isVisibleInWorkspace && !isVisibleFullscreen;
                      const isActiveSession = isVisibleInWorkspace || isVisibleFullscreen;

                      return (
                        <div
                          key={session.id}
                          className={isVisibleFullscreen
                            ? "fixed inset-0 z-50 bg-slate-950/98"
                            : isVisibleInWorkspace
                              ? "absolute inset-0"
                              : "fixed -left-[200vw] top-0 h-px w-px overflow-hidden"
                          }
                        >
                          {(isVisibleInWorkspace || isVisibleFullscreen) && (
                            <div className="flex h-full flex-col">
                              <div className="flex items-center justify-between gap-3 border-b border-slate-700/70 px-4 py-3">
                                <div>
                                  <p className="text-sm font-semibold text-slate-100">{session.title}</p>
                                  <p className="text-xs text-slate-500">Session stays alive when minimized.</p>
                                </div>
                                <div className="flex items-center gap-2">
                                  {!isVisibleFullscreen && (
                                    <button
                                      onClick={() => focusSession(session.id, true)}
                                      className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                                    >
                                      Fullscreen
                                    </button>
                                  )}
                                  <button
                                    onClick={() => minimizeSession(session.id)}
                                    className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                                  >
                                    {isVisibleFullscreen ? "Exit Fullscreen" : "Minimize"}
                                  </button>
                                  {isVisibleFullscreen && (
                                    <button
                                      onClick={() => minimizeSession(session.id)}
                                      className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
                                    >
                                      Minimize
                                    </button>
                                  )}
                                  <button
                                    onClick={() => closeSession(session.id)}
                                    className="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-200 hover:border-rose-400"
                                  >
                                    Close
                                  </button>
                                </div>
                              </div>
                              <div className="min-h-0 flex-1 p-3">
                                <GuacamoleSessionViewport
                                  agentId={agentId}
                                  workspaceSession={session}
                                  active={isActiveSession}
                                  createClientSession={createClientSession}
                                  revokeClientSession={revokeClientSession}
                                  onUpdate={patchSession}
                                />
                              </div>
                            </div>
                          )}
                          {isMountedOffscreen && (
                            <GuacamoleSessionViewport
                              agentId={agentId}
                              workspaceSession={session}
                              active={false}
                              createClientSession={createClientSession}
                              revokeClientSession={revokeClientSession}
                              onUpdate={patchSession}
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center px-6 text-center text-sm text-slate-500">
                    Choose a session from the workspace list or the dock. Fullscreen sessions minimize instead of disconnecting, so you can jump back into the app without losing context.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

      {workspaceSessions.length > 0 && (
        <div className="pointer-events-none fixed bottom-4 right-4 z-40 flex max-w-[min(92vw,40rem)] flex-wrap justify-end gap-2">
          {workspaceSessions.map((session) => (
            <div key={session.id} className="pointer-events-auto min-w-52 rounded-lg border border-slate-700/80 bg-slate-900/92 px-3 py-2 shadow-2xl backdrop-blur">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-100">{session.title}</p>
                  <p className="text-[11px] text-slate-500">{session.connected ? "Connected" : session.status}</p>
                </div>
                <span className={`rounded-full px-2 py-1 text-[11px] font-medium ${getStatusBadgeClasses(session)}`}>
                  {session.fullscreen ? "Fullscreen" : session.minimized ? "Minimized" : "Open"}
                </span>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={() => focusSession(session.id, false)}
                  className="rounded-md border border-slate-600 bg-slate-950/70 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:border-slate-500"
                >
                  Resume
                </button>
                <button
                  onClick={() => focusSession(session.id, true)}
                  className="rounded-md border border-slate-600 bg-slate-950/70 px-2.5 py-1 text-[11px] font-medium text-slate-300 hover:border-slate-500"
                >
                  Fullscreen
                </button>
                <button
                  onClick={() => closeSession(session.id)}
                  className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-[11px] font-medium text-rose-200 hover:border-rose-400"
                >
                  Close
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

    </>
  );
}
