"use client";

const AUTH_SESSION_STORAGE_KEY = "my-orciestra.auth-session";
const AUTH_ACCESS_TOKEN_STORAGE_KEY = "my-orciestra.auth-access-token";
export const AUTH_SESSION_INVALID_EVENT = "my-orciestra:auth-session-invalid";
export const AUTH_SESSION_CHANGED_EVENT = "my-orciestra:auth-session-changed";

const CONFIGURED_API_BASE = (process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");

export const API_BASE = CONFIGURED_API_BASE;

function resolveConfiguredWebSocketUrl(configured: string): string {
  const cleaned = configured.trim();
  if (!cleaned) {
    return "";
  }

  if (typeof window !== "undefined" && window.location.protocol === "https:") {
    try {
      const parsed = new URL(cleaned);
      if (parsed.protocol === "ws:") {
        return `wss://${window.location.host}/frontend`;
      }
    } catch {
      return `wss://${window.location.host}/frontend`;
    }
  }

  return cleaned;
}

export interface AuthUser {
  subject: string;
  username: string;
  display_name: string;
  email: string;
  avatar_url: string;
  avatar_initials: string;
  auth_provider: string;
  roles: string[];
  agent_visibility: "all" | "none";
  group_ids: string[];
  group_names: string[];
  claims: Record<string, unknown>;
}

export interface AuthSession {
  access_token: string;
  expires_at: number;
  user: AuthUser;
}

export interface PublicAuthConfig {
  provider: string;
  provider_locked: boolean;
  local_bootstrap_available: boolean;
  azure_configured: boolean;
  azure_active: boolean;
  microsoft_login_available: boolean;
  client_id_configured: boolean;
  tenant_id_configured: boolean;
  client_secret_configured: boolean;
  group_mapping_count: number;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

function canUsePersistentStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function loadStoredValue(key: string): string {
  if (canUsePersistentStorage()) {
    const persistent = window.localStorage.getItem(key);
    if (persistent) {
      return persistent;
    }
  }

  if (canUseStorage()) {
    return window.sessionStorage.getItem(key) || "";
  }

  return "";
}

function saveStoredValue(key: string, value: string): void {
  if (canUsePersistentStorage()) {
    window.localStorage.setItem(key, value);
  }
  if (canUseStorage()) {
    window.sessionStorage.setItem(key, value);
  }
}

function clearStoredValue(key: string): void {
  if (canUsePersistentStorage()) {
    window.localStorage.removeItem(key);
  }
  if (canUseStorage()) {
    window.sessionStorage.removeItem(key);
  }
}

export function loadAuthSession(): AuthSession | null {
  if (!canUseStorage() && !canUsePersistentStorage()) {
    return null;
  }

  const raw = loadStoredValue(AUTH_SESSION_STORAGE_KEY);
  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as AuthSession;
    if (!parsed?.access_token) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveAuthSession(session: AuthSession): void {
  if (!canUseStorage() && !canUsePersistentStorage()) {
    return;
  }
  saveStoredValue(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session));
  saveStoredValue(AUTH_ACCESS_TOKEN_STORAGE_KEY, session.access_token);
  dispatchAuthSessionChanged();
}

export function saveAccessToken(accessToken: string): void {
  if (!canUseStorage() && !canUsePersistentStorage()) {
    return;
  }
  saveStoredValue(AUTH_ACCESS_TOKEN_STORAGE_KEY, accessToken);
}

export function clearAuthSession(): void {
  if (!canUseStorage() && !canUsePersistentStorage()) {
    return;
  }
  clearStoredValue(AUTH_SESSION_STORAGE_KEY);
  clearStoredValue(AUTH_ACCESS_TOKEN_STORAGE_KEY);
  dispatchAuthSessionChanged();
}

function dispatchAuthSessionInvalid(detail?: { reason?: string; status?: number }): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_INVALID_EVENT, { detail }));
}

function dispatchAuthSessionChanged(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.dispatchEvent(new CustomEvent(AUTH_SESSION_CHANGED_EVENT));
}

export function getAccessToken(): string {
  if (!canUseStorage() && !canUsePersistentStorage()) {
    return "";
  }
  return loadStoredValue(AUTH_ACCESS_TOKEN_STORAGE_KEY) || loadAuthSession()?.access_token || "";
}

export function consumeAuthTokenFromUrlHash(): string {
  if (typeof window === "undefined" || !window.location.hash) {
    return "";
  }

  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  const params = new URLSearchParams(hash);
  const token = params.get("auth_token") || "";
  if (!token) {
    return "";
  }

  params.delete("auth_token");
  const nextHash = params.toString();
  const nextUrl = `${window.location.pathname}${window.location.search}${nextHash ? `#${nextHash}` : ""}`;
  window.history.replaceState({}, "", nextUrl);
  return token;
}

export function withAccessToken(url: string): string {
  const token = getAccessToken();
  if (!token) {
    return url;
  }

  const parsed = new URL(url, typeof window !== "undefined" ? window.location.origin : undefined);
  parsed.searchParams.set("access_token", token);
  return parsed.toString();
}

export function withAuthHeaders(headers?: HeadersInit): Headers {
  const nextHeaders = new Headers(headers || {});
  const token = getAccessToken();
  if (token) {
    nextHeaders.set("Authorization", `Bearer ${token}`);
  }
  return nextHeaders;
}

export async function fetchJSON<T>(url: string, init?: RequestInit, options?: { auth?: boolean }): Promise<T> {
  const auth = options?.auth ?? true;
  const requestInit: RequestInit = {
    ...init,
    headers: auth ? withAuthHeaders(init?.headers) : new Headers(init?.headers || {}),
  };

  const response = await fetch(url, requestInit);
  if (!response.ok) {
    if (auth && response.status === 401) {
      clearAuthSession();
      dispatchAuthSessionInvalid({ reason: "unauthorized", status: 401 });
    }
    const payload = await response.json().catch(() => ({}));
    const message = typeof payload?.error === "string" ? payload.error : `HTTP ${response.status}`;
    throw new ApiError(response.status, message);
  }
  return response.json();
}

export async function sendJSON<T>(url: string, method: string, body: unknown, options?: { auth?: boolean }): Promise<T> {
  return fetchJSON<T>(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }, options);
}

export function buildFrontendWebSocketUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured) {
    return resolveConfiguredWebSocketUrl(configured);
  }

  if (typeof window === "undefined") {
    return "ws://127.0.0.1:8765/frontend";
  }

  if (CONFIGURED_API_BASE) {
    const parsed = new URL(CONFIGURED_API_BASE);
    const protocol = parsed.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${parsed.host}/frontend`;
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}/frontend`;
}

export function describeFrontendWebSocketUrl(): string {
  const configured = process.env.NEXT_PUBLIC_WS_URL;
  if (configured) {
    return resolveConfiguredWebSocketUrl(configured);
  }

  if (CONFIGURED_API_BASE) {
    const parsed = new URL(CONFIGURED_API_BASE);
    const protocol = parsed.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${parsed.host}/frontend`;
  }

  return "Current browser origin + /frontend (wss under https)";
}