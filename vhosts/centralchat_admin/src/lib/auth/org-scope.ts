import type { OrgMembership, OrgProject } from "@/lib/api/org";

export function isGlobalAdminRole(role: string | null | undefined): boolean {
  return role === "admin";
}

export function canManageProjectFromMemberships({
  project,
  memberships,
  role,
}: {
  project: OrgProject;
  memberships: OrgMembership[];
  role: string | null | undefined;
}): boolean {
  if (isGlobalAdminRole(role)) return true;
  if (
    memberships.some(
      (membership) => membership.scope_type === "organization" && membership.role === "admin",
    )
  ) {
    return true;
  }
  if (
    memberships.some(
      (membership) =>
        membership.scope_type === "project" && membership.scope_id === project.id && membership.role === "lead",
    )
  ) {
    return true;
  }
  return memberships.some(
    (membership) =>
      membership.scope_type === "group" && membership.scope_id === project.group_id && membership.role === "lead",
  );
}

export function manageableProjects({
  projects,
  memberships,
  role,
}: {
  projects: OrgProject[];
  memberships: OrgMembership[];
  role: string | null | undefined;
}): OrgProject[] {
  return projects.filter((project) => canManageProjectFromMemberships({ project, memberships, role }));
}
