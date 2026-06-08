"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { GlobalGuacamoleWorkspace } from "@/components/GlobalGuacamoleWorkspace";
import {
  loadPersistedWorkspaceSession,
  persistWorkspaceSession,
  subscribeToWorkspaceStorage,
} from "@/components/guacamole/storage";
import type { GuacamoleWorkspaceContextValue, WorkspaceConnection } from "@/components/guacamole/types";
import { createInstanceId } from "@/components/guacamole/utils";

const GuacamoleWorkspaceContext = createContext<GuacamoleWorkspaceContextValue | null>(null);

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

  const openSession = (
    agentId: string,
    title = "Remote Desktop",
    options?: { readOnly?: boolean; recorded?: boolean; requestedConnectionId?: string | null; requestedVmUsername?: string | null },
  ) => {
    setSessionOverride((current) => {
      const base = current === undefined ? persistedSession : current;
      const requestedConnectionId = options?.requestedConnectionId || null;
      const requestedVmUsername = options?.requestedVmUsername || null;
      const readOnly = options?.readOnly === true;
      const recorded = options?.recorded === true;

      if (
        base
        && base.agentId === agentId
        && base.requestedConnectionId === requestedConnectionId
        && base.requestedVmUsername === requestedVmUsername
        && base.readOnly === readOnly
        && base.recorded === recorded
      ) {
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
        readOnly,
        recorded,
        accessPolicy: null,
        requestedConnectionId,
        requestedVmUsername,
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

  const exitFullscreenSession = () => {
    setSessionOverride((current) => {
      const base = current === undefined ? persistedSession : current;
      return base ? { ...base, minimized: false, fullscreen: false } : base;
    });
  };

  const closeSession = () => {
    setSessionOverride(null);
  };

  const reconnectSession = () => {
    setSessionOverride((current) => {
      const base = current === undefined ? persistedSession : current;
      if (!base) {
        return base;
      }

      return {
        ...base,
        instanceId: createInstanceId(base.agentId),
        readOnly: base.readOnly,
        recorded: base.recorded,
        accessPolicy: base.accessPolicy,
        requestedConnectionId: base.requestedConnectionId,
        requestedVmUsername: base.requestedVmUsername,
        status: "queued",
        error: null,
        hint: null,
        connected: false,
        minimized: false,
        fullscreen: false,
        launchedAt: Date.now(),
        clientSession: null,
      };
    });
  };

  return (
    <GuacamoleWorkspaceContext.Provider
      value={{
        session,
        openSession,
        resumeSession,
        minimizeSession,
        fullscreenSession,
        exitFullscreenSession,
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
        onExitFullscreen={exitFullscreenSession}
        onReconnect={reconnectSession}
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
