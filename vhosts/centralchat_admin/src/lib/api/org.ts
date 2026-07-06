import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type OrgGroup = {
  id: string;
  tenant_id: string;
  name: string;
  slug: string;
  description?: string;
  created_at?: string;
  updated_at?: string;
};

export type OrgProject = {
  id: string;
  tenant_id: string;
  group_id: string;
  name: string;
  slug: string;
  description?: string;
  repository_url?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type OrgMembership = {
  id: string;
  tenant_id: string;
  user_id: string;
  scope_type: "organization" | "group" | "project";
  scope_id: string;
  role: "admin" | "lead" | "developer" | "auditor";
  created_at?: string;
  updated_at?: string;
};

export type OrgTree = {
  tenant_id: string;
  groups: OrgGroup[];
  projects: OrgProject[];
  memberships: OrgMembership[];
  org_enabled: boolean;
};

export type OrgHealth = {
  tenant_id: string;
  groups_without_projects: OrgGroup[];
  projects_without_direct_lead: OrgProject[];
  counts: {
    groups: number;
    projects: number;
    groups_without_projects: number;
    projects_without_direct_lead: number;
  };
  org_enabled: boolean;
};

export const fetchOrgTree = createServerFn({ method: "GET" }).handler(async () =>
  orchestratorJson<OrgTree>("/admin/org/tree"),
);

export const fetchOrgHealth = createServerFn({ method: "GET" }).handler(async () =>
  orchestratorJson<OrgHealth>("/admin/org/health"),
);

export const createOrgGroup = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      name: z.string().min(1).max(200),
      slug: z.string().max(80).optional(),
      description: z.string().max(2000).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ group: OrgGroup; ok: boolean }>("/admin/groups", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  );

export const patchOrgGroup = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      groupId: z.string().min(8),
      name: z.string().min(1).max(200).optional(),
      slug: z.string().max(80).optional(),
      description: z.string().max(2000).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ group: OrgGroup; ok: boolean }>(`/admin/groups/${data.groupId}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: data.name,
        slug: data.slug,
        description: data.description,
      }),
    }),
  );

export const createOrgProject = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      groupId: z.string().min(8),
      name: z.string().min(1).max(200),
      slug: z.string().max(80).optional(),
      description: z.string().max(2000).optional(),
      repositoryUrl: z.string().max(1000).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ project: OrgProject; ok: boolean }>("/admin/projects", {
      method: "POST",
      body: JSON.stringify({
        group_id: data.groupId,
        name: data.name,
        slug: data.slug,
        description: data.description,
        repository_url: data.repositoryUrl,
      }),
    }),
  );

export const patchOrgProject = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      projectId: z.string().min(8),
      name: z.string().min(1).max(200).optional(),
      slug: z.string().max(80).optional(),
      description: z.string().max(2000).optional(),
      repositoryUrl: z.string().max(1000).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ project: OrgProject; ok: boolean }>(`/admin/projects/${data.projectId}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: data.name,
        slug: data.slug,
        description: data.description,
        repository_url: data.repositoryUrl,
      }),
    }),
  );

export const upsertProjectMember = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      projectId: z.string().min(8),
      userId: z.string().min(8),
      role: z.enum(["admin", "lead", "developer", "auditor"]),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ membership: OrgMembership; ok: boolean }>(
      `/admin/projects/${data.projectId}/members/${data.userId}`,
      {
        method: "PUT",
        body: JSON.stringify({ role: data.role }),
      },
    ),
  );

export const fetchProjectMembers = createServerFn({ method: "GET" })
  .inputValidator(z.object({ projectId: z.string().min(8) }))
  .handler(async ({ data }) =>
    orchestratorJson<{ items: OrgMembership[]; count: number }>(`/admin/projects/${data.projectId}/members`),
  );

export const deleteProjectMember = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      projectId: z.string().min(8),
      userId: z.string().min(8),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ ok: boolean; project_id: string; user_id: string }>(
      `/admin/projects/${data.projectId}/members/${data.userId}`,
      { method: "DELETE" },
    ),
  );
