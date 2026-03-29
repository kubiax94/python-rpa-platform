"use client";

import { useCallback, useEffect, useState } from "react";
import {
  API_BASE,
  AUTH_SESSION_INVALID_EVENT,
  ApiError,
  type AuthSession,
  clearAuthSession,
  consumeAuthTokenFromUrlHash,
  fetchJSON,
  getAccessToken,
  loadAuthSession,
  saveAccessToken,
  saveAuthSession,
  sendJSON,
  type PublicAuthConfig,
} from "@/lib/auth";
import { BACKEND_DISCONNECTED_EVENT } from "@/components/guacamole/utils";

type BackendAvailability = "unknown" | "online" | "offline";

export function useUserAuth() {
  const [session, setSession] = useState<AuthSession | null>(() => loadAuthSession());
  const [authConfig, setAuthConfig] = useState<PublicAuthConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [backendAvailability, setBackendAvailability] = useState<BackendAvailability>("unknown");
  const [authNotice, setAuthNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    const urlToken = consumeAuthTokenFromUrlHash();
    if (urlToken) {
      saveAccessToken(urlToken);
    }

    let backendOnline = false;
    try {
      const config = await fetchJSON<PublicAuthConfig>(`${API_BASE}/api/users/auth-config`, undefined, { auth: false });
      setAuthConfig(config);
      setBackendAvailability("online");
      backendOnline = true;
    } catch (error) {
      console.error("[useUserAuth] Failed to load auth config", error);
      setAuthConfig(null);
      setBackendAvailability("offline");
    }

    if (!backendOnline) {
      setLoading(false);
      return;
    }

    if (!getAccessToken()) {
      setSession(null);
      setLoading(false);
      return;
    }

    try {
      const activeSession = await fetchJSON<AuthSession>(`${API_BASE}/api/users/me`);
      saveAuthSession(activeSession);
      setSession(activeSession);
      setAuthNotice(null);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearAuthSession();
        setSession(null);
        setAuthNotice((current) => current || "Your server session is no longer valid. Sign in again.");
      } else {
        console.error("[useUserAuth] Failed to refresh session", error);
        setBackendAvailability("offline");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const handleBackendDisconnected = () => {
      clearAuthSession();
      setSession(null);
      setBackendAvailability("offline");
      setAuthNotice("The control server disconnected and in-memory user sessions were lost. Sign in again after the server comes back.");
    };

    const handleInvalidSession = () => {
      clearAuthSession();
      setSession(null);
      setBackendAvailability("online");
      setAuthNotice("Your server session was lost or expired. Sign in again.");
    };

    window.addEventListener(BACKEND_DISCONNECTED_EVENT, handleBackendDisconnected);
    window.addEventListener(AUTH_SESSION_INVALID_EVENT, handleInvalidSession);
    return () => {
      window.removeEventListener(BACKEND_DISCONNECTED_EVENT, handleBackendDisconnected);
      window.removeEventListener(AUTH_SESSION_INVALID_EVENT, handleInvalidSession);
    };
  }, []);

  useEffect(() => {
    if (session || backendAvailability !== "offline") {
      return;
    }

    const interval = window.setInterval(() => {
      void refresh();
    }, 5000);

    return () => {
      window.clearInterval(interval);
    };
  }, [backendAvailability, refresh, session]);

  const loginLocal = useCallback(async (username: string, password: string) => {
    const nextSession = await sendJSON<AuthSession>(`${API_BASE}/api/users/login/local`, "POST", { username, password }, { auth: false });
    saveAuthSession(nextSession);
    setSession(nextSession);
    setBackendAvailability("online");
    setAuthNotice(null);
    await refresh();
  }, [refresh]);

  const beginMicrosoftLogin = useCallback(async () => {
    const returnTo = typeof window === "undefined"
      ? "/"
      : `${window.location.origin}${window.location.pathname}${window.location.search}`;
    const result = await sendJSON<{ authorize_url: string }>(
      `${API_BASE}/api/users/login/microsoft`,
      "POST",
      { return_to: returnTo },
      { auth: false },
    );
    if (typeof window !== "undefined") {
      window.location.assign(result.authorize_url);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await sendJSON(`${API_BASE}/api/users/logout`, "POST", {});
    } catch (error) {
      console.error("[useUserAuth] Logout failed", error);
    } finally {
      clearAuthSession();
      setSession(null);
      await refresh();
    }
  }, [refresh]);

  return {
    session,
    authConfig,
    loading,
    backendAvailability,
    authNotice,
    refresh,
    loginLocal,
    beginMicrosoftLogin,
    logout,
  };
}