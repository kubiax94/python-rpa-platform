import Guacamole from "guacamole-common-js";
import type { GuacamoleConnectionDiagnostics } from "@/hooks/useGuacamole";

export const BACKEND_DISCONNECTED_EVENT = "my-orciestra:backend-disconnected";

export function createPersistedInstanceId(agentId: string, launchedAt: number): string {
  return `${agentId}:${launchedAt}`;
}

export function createInstanceId(agentId: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${agentId}:${crypto.randomUUID()}`;
  }

  return `${agentId}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
}

export function buildWorkspaceHint(
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

export function maskDebugValue(value: string | null | undefined): string {
  if (!value) {
    return "<none>";
  }

  if (value.length <= 12) {
    return value;
  }

  return `${value.slice(0, 6)}...${value.slice(-6)}`;
}

export function resetGuacamoleKeyboard(keyboard: InstanceType<typeof Guacamole.Keyboard> | null): void {
  const maybeResettableKeyboard = keyboard as (InstanceType<typeof Guacamole.Keyboard> & { reset?: () => void }) | null;
  maybeResettableKeyboard?.reset?.();
}

export function getSnapshotCapableClient(
  client: InstanceType<typeof Guacamole.Client> | null,
): (InstanceType<typeof Guacamole.Client> & {
  exportState: (callback: (state: object) => void) => void;
  importState: (state: object, callback?: () => void) => void;
}) | null {
  return client as ((InstanceType<typeof Guacamole.Client> & {
    exportState: (callback: (state: object) => void) => void;
    importState: (state: object, callback?: () => void) => void;
  }) | null);
}