export type AdminRole =
  | "admin"
  | "lead"
  | "developer"
  | "auditor"
  | "viewer"
  | "reviewer"
  | "approver";

export type DashboardPath =
  | "/dashboard"
  | "/dashboard/approvals"
  | "/dashboard/requests"
  | "/dashboard/sessions"
  | "/dashboard/rules"
  | "/dashboard/agents"
  | "/dashboard/skills"
  | "/dashboard/policies"
  | "/dashboard/queue"
  | "/dashboard/audit"
  | "/dashboard/usage"
  | "/dashboard/compliance"
  | "/dashboard/inference"
  | "/dashboard/settings/secrets"
  | "/dashboard/settings/inference"
  | "/dashboard/settings/ops"
  | "/dashboard/org"
  | "/dashboard/users";

const ALL_ROLES: AdminRole[] = [
  "admin",
  "lead",
  "developer",
  "auditor",
  "viewer",
  "reviewer",
  "approver",
];

export const DASHBOARD_PATH_ROLES: Record<DashboardPath, AdminRole[]> = {
  "/dashboard": ALL_ROLES,
  "/dashboard/approvals": [
    "admin",
    "lead",
    "developer",
    "reviewer",
    "approver",
  ],
  "/dashboard/requests": [
    "admin",
    "lead",
    "developer",
    "auditor",
    "reviewer",
  ],
  "/dashboard/sessions": ALL_ROLES,
  "/dashboard/rules": ["admin", "lead", "developer", "auditor", "reviewer"],
  "/dashboard/agents": ["admin", "lead", "developer", "auditor", "reviewer"],
  "/dashboard/skills": ["admin", "lead", "developer", "auditor", "reviewer"],
  "/dashboard/policies": ["admin", "lead", "auditor"],
  "/dashboard/queue": ALL_ROLES,
  "/dashboard/audit": ["admin", "auditor", "viewer", "developer", "approver"],
  "/dashboard/usage": ["admin", "auditor", "approver"],
  "/dashboard/compliance": ["admin", "auditor", "approver"],
  "/dashboard/inference": ["admin", "auditor"],
  "/dashboard/settings/secrets": ["admin", "auditor"],
  "/dashboard/settings/inference": ["admin", "auditor"],
  "/dashboard/settings/ops": ["admin", "auditor"],
  "/dashboard/org": ["admin", "lead", "developer", "auditor"],
  "/dashboard/users": ["admin", "lead", "auditor"],
};

export function normalizeAdminRole(
  role: string | null | undefined,
): AdminRole | null {
  const normalized = (role || "").trim().toLowerCase();
  if (
    normalized === "admin" ||
    normalized === "lead" ||
    normalized === "developer" ||
    normalized === "auditor" ||
    normalized === "viewer" ||
    normalized === "reviewer" ||
    normalized === "approver"
  ) {
    return normalized;
  }
  return null;
}

export function canAccessDashboardPath(
  path: DashboardPath,
  role: string | null | undefined,
): boolean {
  const normalized = normalizeAdminRole(role);
  return normalized ? DASHBOARD_PATH_ROLES[path].includes(normalized) : false;
}
