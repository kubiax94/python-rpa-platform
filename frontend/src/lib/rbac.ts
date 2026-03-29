export type AppRole = "viewer" | "operator" | "admin";

const ROLE_ORDER: Record<AppRole, number> = {
  viewer: 0,
  operator: 1,
  admin: 2,
};

export function normalizeRoles(roles: string[] | null | undefined): AppRole[] {
  const normalized = Array.from(new Set((roles || [])
    .map((role) => role.trim().toLowerCase())
    .filter((role): role is AppRole => role === "viewer" || role === "operator" || role === "admin")));

  return normalized.length > 0 ? normalized : ["viewer"];
}

export function getHighestRole(roles: string[] | null | undefined): AppRole {
  return normalizeRoles(roles).reduce((highest, current) => (
    ROLE_ORDER[current] > ROLE_ORDER[highest] ? current : highest
  ), "viewer" as AppRole);
}

export function hasMinimumRole(roles: string[] | null | undefined, minimumRole: AppRole): boolean {
  return ROLE_ORDER[getHighestRole(roles)] >= ROLE_ORDER[minimumRole];
}

export function formatRoleLabel(role: string): string {
  const normalized = role.trim().toLowerCase();
  if (normalized === "admin") {
    return "Admin";
  }
  if (normalized === "operator") {
    return "Operator";
  }
  return "Viewer";
}