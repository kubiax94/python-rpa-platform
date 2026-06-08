import type { GuacamoleAccessPolicy, GuacamolePermissionKey } from "@/hooks/useGuacamole";

export const GUACAMOLE_PERMISSION_ROWS: Array<{
  key: GuacamolePermissionKey;
  label: string;
  description: string;
}> = [
  { key: "view", label: "Remote View", description: "Open the remote desktop in read-only mode." },
  { key: "interact", label: "Interactive Input", description: "Send keyboard and mouse input into the remote session." },
  { key: "clipboard", label: "Clipboard", description: "Allow browser and remote clipboard sync." },
  { key: "upload", label: "File Upload", description: "Send files from the browser into the VM." },
  { key: "download", label: "File Download", description: "Receive files from the VM into the browser." },
  { key: "recording", label: "Recording", description: "Start recorded Guacamole sessions." },
  { key: "session_kick", label: "Session Kick", description: "Close another user's tracked remote session." },
];

export function splitPrincipalList(value: string): string[] {
  return Array.from(new Set(value
    .split(/[\n,;]/)
    .map((entry) => entry.trim())
    .filter(Boolean)));
}

export function joinPrincipalList(values: string[] | undefined): string {
  return (values || []).join("\n");
}

export function createDefaultGuacamoleAccessPolicy(): GuacamoleAccessPolicy {
  return {
    permissions: {
      view: { enabled: true, minimum_role: "operator", users: [], groups: [] },
      interact: { enabled: true, minimum_role: "admin", users: [], groups: [] },
      clipboard: { enabled: true, minimum_role: "operator", users: [], groups: [] },
      upload: { enabled: true, minimum_role: "admin", users: [], groups: [] },
      download: { enabled: true, minimum_role: "admin", users: [], groups: [] },
      recording: { enabled: true, minimum_role: "operator", users: [], groups: [] },
      session_kick: { enabled: true, minimum_role: "admin", users: [], groups: [] },
    },
  };
}