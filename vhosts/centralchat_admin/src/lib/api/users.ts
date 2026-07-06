import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import type { OrgMembership } from "./org";
import { orchestratorJson } from "./orchestrator";

export type AdminUser = {
  id: string;
  email: string;
  client_id: string;
  display_name: string;
  active: boolean;
  role: string;
};

export const fetchAdminUsers = createServerFn({ method: "GET" })
  .inputValidator(z.object({ q: z.string().optional(), limit: z.number().int().min(1).max(500).optional() }).optional())
  .handler(async ({ data }) => {
    const params = new URLSearchParams();
    params.set("limit", String(data?.limit ?? 200));
    if (data?.q) params.set("q", data.q);
    return orchestratorJson<{ items: AdminUser[]; count: number }>(`/admin/users?${params.toString()}`);
  });

export const createAdminUser = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      email: z.string().email().max(320),
      password: z.string().min(8).max(512),
      displayName: z.string().max(200).optional(),
      role: z.enum(["admin", "lead", "developer", "auditor"]).default("developer"),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ user: AdminUser; ok: boolean; membership_created: boolean }>("/admin/users", {
      method: "POST",
      body: JSON.stringify({
        email: data.email,
        password: data.password,
        display_name: data.displayName,
        role: data.role,
      }),
    }),
  );

export const patchAdminUser = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      userId: z.string().min(8),
      displayName: z.string().max(200).optional(),
      role: z.enum(["admin", "lead", "developer", "auditor"]).optional(),
      active: z.boolean().optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ user: AdminUser; ok: boolean }>(`/admin/users/${data.userId}`, {
      method: "PATCH",
      body: JSON.stringify({
        display_name: data.displayName,
        role: data.role,
        active: data.active,
      }),
    }),
  );

export const resetAdminUserPassword = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      userId: z.string().min(8),
      password: z.string().min(8).max(512),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ ok: boolean }>(`/admin/users/${data.userId}/reset-password`, {
      method: "POST",
      body: JSON.stringify({ password: data.password }),
    }),
  );

export const revokeAdminUserSessions = createServerFn({ method: "POST" })
  .inputValidator(z.object({ userId: z.string().min(8) }))
  .handler(async ({ data }) =>
    orchestratorJson<{ ok: boolean; sessions_revoked: boolean }>(`/admin/users/${data.userId}/revoke-sessions`, {
      method: "POST",
    }),
  );

export const fetchAdminUserMemberships = createServerFn({ method: "GET" })
  .inputValidator(z.object({ userId: z.string().min(8) }))
  .handler(async ({ data }) =>
    orchestratorJson<{ items: OrgMembership[]; count: number }>(`/admin/users/${data.userId}/memberships`),
  );
