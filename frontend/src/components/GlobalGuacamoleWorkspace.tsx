"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useSyncExternalStore } from "react";
import { GuacamoleViewport } from "@/components/GuacamoleViewport";
import {
  getDefaultDockedWorkspaceRect,
  loadDockedWorkspaceRect,
  subscribeToWorkspaceStorage,
} from "@/components/guacamole/storage";
import type { DockedWorkspaceRect, WorkspaceConnection } from "@/components/guacamole/types";
import {
  AUTH_SESSION_CHANGED_EVENT,
  AUTH_SESSION_INVALID_EVENT,
  loadAuthSession,
  type AuthUser,
} from "@/lib/auth";

function getUserLabel(user: AuthUser | null): string {
  if (!user) {
    return "Unknown user";
  }

  return user.display_name || user.username || user.email || user.subject;
}

function getUserInitials(user: AuthUser | null): string {
  if (!user) {
    return "?";
  }

  if (user.avatar_initials) {
    return user.avatar_initials;
  }

  const parts = getUserLabel(user).trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "?") + (parts[1]?.[0] || "")).toUpperCase();
}

function UserProfileChip({ user }: { user: AuthUser | null }) {
  const label = getUserLabel(user);

  return (
    <span className="inline-flex max-w-full items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-[11px] text-emerald-100">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center overflow-hidden rounded-full border border-emerald-400/20 bg-emerald-500/15 text-[10px] font-semibold text-emerald-100">
        {user?.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={user.avatar_url} alt={label} className="h-full w-full object-cover" />
        ) : (
          getUserInitials(user)
        )}
      </span>
      <span className="min-w-0 truncate">
        <span className="text-emerald-200/80">In use by </span>
        <span className="font-medium text-emerald-50">{label}</span>
      </span>
    </span>
  );
}

export function GlobalGuacamoleWorkspace({
  session,
  onUpdate,
  onResume,
  onMinimize,
  onFullscreen,
  onExitFullscreen,
  onReconnect,
  onClose,
}: {
  session: WorkspaceConnection | null;
  onUpdate: (patch: Partial<WorkspaceConnection>) => void;
  onResume: () => void;
  onMinimize: () => void;
  onFullscreen: () => void;
  onExitFullscreen: () => void;
  onReconnect: () => void;
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
  const [activeUser, setActiveUser] = useState<AuthUser | null>(() => loadAuthSession()?.user ?? null);
  const [fullscreenChromeVisible, setFullscreenChromeVisible] = useState(true);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const dockedRect = dockedRectOverride ?? persistedDockedRect;
  const fullscreenChromeHideTimerRef = useRef<number | null>(null);
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

  const clearFullscreenChromeHideTimer = useCallback(() => {
    if (fullscreenChromeHideTimerRef.current != null) {
      window.clearTimeout(fullscreenChromeHideTimerRef.current);
      fullscreenChromeHideTimerRef.current = null;
    }
  }, []);

  const scheduleFullscreenChromeHide = useCallback(() => {
    clearFullscreenChromeHideTimer();
    if (!session?.fullscreen) {
      return;
    }

    fullscreenChromeHideTimerRef.current = window.setTimeout(() => {
      setFullscreenChromeVisible(false);
      fullscreenChromeHideTimerRef.current = null;
    }, 2200);
  }, [clearFullscreenChromeHideTimer, session?.fullscreen]);

  const revealFullscreenChrome = useCallback(() => {
    setFullscreenChromeVisible(true);
    scheduleFullscreenChromeHide();
  }, [scheduleFullscreenChromeHide]);

  const requestBrowserFullscreen = useCallback(async () => {
    const shellElement = shellRef.current;
    if (!shellElement || document.fullscreenElement === shellElement || typeof shellElement.requestFullscreen !== "function") {
      return;
    }

    try {
      await shellElement.requestFullscreen();
    } catch {
      // Fall back to app-level fullscreen if the browser blocks the request.
    }
  }, []);

  const exitBrowserFullscreen = useCallback(async () => {
    if (document.fullscreenElement !== shellRef.current || typeof document.exitFullscreen !== "function") {
      return;
    }

    try {
      await document.exitFullscreen();
    } catch {
      // Ignore browser exit errors and still update app state.
    }
  }, []);

  const handleEnterFullscreen = useCallback(() => {
    onFullscreen();
    void requestBrowserFullscreen();
  }, [onFullscreen, requestBrowserFullscreen]);

  const handleExitFullscreen = useCallback(() => {
    onExitFullscreen();
    void exitBrowserFullscreen();
  }, [exitBrowserFullscreen, onExitFullscreen]);

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
    window.localStorage.setItem("my-orciestra.guacamole.workspace.v1", JSON.stringify(dockedRect));
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

  useEffect(() => {
    const syncActiveUser = () => {
      setActiveUser(loadAuthSession()?.user ?? null);
    };

    const handleStorage = (event: StorageEvent) => {
      if (!event.key || event.key === "my-orciestra.auth-session") {
        syncActiveUser();
      }
    };

    syncActiveUser();
    window.addEventListener("storage", handleStorage);
    window.addEventListener(AUTH_SESSION_CHANGED_EVENT, syncActiveUser);
    window.addEventListener(AUTH_SESSION_INVALID_EVENT, syncActiveUser);
    return () => {
      window.removeEventListener("storage", handleStorage);
      window.removeEventListener(AUTH_SESSION_CHANGED_EVENT, syncActiveUser);
      window.removeEventListener(AUTH_SESSION_INVALID_EVENT, syncActiveUser);
    };
  }, []);

  useEffect(() => {
    if (!session?.fullscreen) {
      clearFullscreenChromeHideTimer();
      const frameId = window.requestAnimationFrame(() => {
        setFullscreenChromeVisible(true);
      });
      return () => {
        window.cancelAnimationFrame(frameId);
      };
    }

    const frameId = window.requestAnimationFrame(() => {
      revealFullscreenChrome();
    });
    return () => {
      window.cancelAnimationFrame(frameId);
      clearFullscreenChromeHideTimer();
    };
  }, [clearFullscreenChromeHideTimer, revealFullscreenChrome, session?.fullscreen]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      if (!session?.fullscreen) {
        return;
      }
      if (document.fullscreenElement === shellRef.current) {
        return;
      }
      onExitFullscreen();
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
    };
  }, [onExitFullscreen, session?.fullscreen]);

  useEffect(() => {
    if (!session || session.status !== "session_closed") {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      onClose();
    }, 2400);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [onClose, session]);

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
  const shouldAllowReconnect = session.status !== "session_closed";
  const headerClassName = session.fullscreen
    ? `absolute inset-x-0 top-0 z-30 flex items-center justify-between gap-3 border-b border-slate-700/70 bg-slate-900/88 px-4 py-3 transition-all duration-200 ${fullscreenChromeVisible ? "translate-y-0 opacity-100" : "-translate-y-full opacity-0 pointer-events-none"}`
    : "flex items-center justify-between gap-3 border-b border-slate-700/70 bg-slate-900/88 px-4 py-3";
  const shouldShowFullscreenChromeHandle = session.fullscreen && !fullscreenChromeVisible;

  return (
    <>
      <div
        ref={shellRef}
        className={shellClassName}
        style={session.fullscreen || session.minimized ? undefined : dockedStyle}
      >
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
          onPointerEnter={() => {
            if (session.fullscreen) {
              revealFullscreenChrome();
            }
          }}
          className={headerClassName}
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
                {session.recorded && (
                  <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-amber-200">
                    Recorded
                  </span>
                )}
                {session.readOnly && <span>Read-only</span>}
                {session.targetHost && <span>Target {session.targetHost}</span>}
                <UserProfileChip user={activeUser} />
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {!session.fullscreen && (
              <button
                onClick={handleEnterFullscreen}
                className="rounded-md border border-slate-600 bg-slate-900/70 px-3 py-1.5 text-xs font-medium text-slate-300 hover:border-slate-500"
              >
                Fullscreen
              </button>
            )}
            <button
              onClick={session.fullscreen ? handleExitFullscreen : onMinimize}
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
        {shouldShowFullscreenChromeHandle && (
          <button
            type="button"
            aria-label="Show fullscreen controls"
            onClick={revealFullscreenChrome}
            className="absolute left-1/2 top-2 z-20 flex h-7 w-7 -translate-x-1/2 items-center justify-center rounded-full border border-slate-700/80 bg-slate-900/72 text-slate-300 shadow-lg backdrop-blur hover:border-cyan-500/50 hover:text-cyan-200"
          >
            <span className="block h-1.5 w-1.5 rounded-full bg-current opacity-90" aria-hidden="true" />
          </button>
        )}
        <div className="relative min-h-0 flex-1">
          <GuacamoleViewport session={session} active={isVisible} onUpdate={onUpdate} />
          {!session.connected && (
            <div className="absolute inset-0 flex items-center justify-center bg-slate-950/55">
              <div className="pointer-events-auto max-w-[min(92%,34rem)] rounded-md border border-slate-700 bg-slate-900/90 px-4 py-3 text-xs text-slate-300 shadow-2xl">
                <p className="font-medium text-slate-100">{session.error || session.status || "Connecting"}</p>
                {session.hint && <p className="mt-2 text-slate-300/90">{session.hint}</p>}
                {(session.targetHost || session.connectionName) && (
                  <div className="mt-3 space-y-1 text-[11px] text-slate-400">
                    {session.targetHost && <p>Target host: {session.targetHost}</p>}
                    {session.connectionName && <p>Guacamole connection: {session.connectionName}</p>}
                  </div>
                )}
                <div className="mt-4 flex items-center justify-end gap-2">
                  {shouldAllowReconnect ? (
                    <button
                      onClick={onReconnect}
                      className="rounded-md border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:border-cyan-400"
                    >
                      Reconnect
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          )}
        </div>
        {!session.fullscreen && (
          <div className="flex items-center justify-between gap-3 border-t border-slate-800 bg-slate-950/95 px-4 py-2 text-[11px] text-slate-500">
            <span>Docked global workspace · drag the header to move, top or left edge to resize</span>
            <span>{session.minimized ? "Minimized" : session.readOnly ? "Read-only view" : session.connected ? "Ready for input" : "Connecting"}</span>
          </div>
        )}
      </div>

      {session.minimized && (
        <div className="pointer-events-none fixed bottom-4 right-4 z-40 flex max-w-[min(92vw,28rem)] flex-wrap justify-end gap-2">
          <div className="pointer-events-auto min-w-56 rounded-lg border border-slate-700/80 bg-slate-900/92 px-3 py-2 shadow-2xl backdrop-blur">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-100">{session.title}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                  <span>{session.connected ? "Connected" : session.status}</span>
                  {session.recorded && (
                    <span className="rounded-full border border-amber-500/25 bg-amber-500/10 px-2 py-0.5 text-amber-200">
                      Recorded
                    </span>
                  )}
                  <UserProfileChip user={activeUser} />
                </div>
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
                Show
              </button>
              <button
                onClick={handleEnterFullscreen}
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