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
