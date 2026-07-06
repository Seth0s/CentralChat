import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type TeamRule = {
  id: string;
  pattern: string;
  source: string;
  approved: boolean;
  rejected?: boolean;
  proposed_by?: string | null;
  approved_by?: string | null;
  rejection_context?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
};

export const fetchTeamRules = createServerFn({ method: "GET" })
  .inputValidator(
    z.object({ status: z.enum(["all", "pending", "approved", "rejected"]).optional() }),
  )
  .handler(async ({ data }) => {
    const status = data?.status ?? "all";
    return orchestratorJson<{
      items: TeamRule[];
      counts: { pending: number; approved: number; rejected: number };
    }>(`/ui/team/rules?status=${status}`);
  });

export const createTeamRule = createServerFn({ method: "POST" })
  .inputValidator(z.object({ pattern: z.string().min(3).max(2000) }))
  .handler(async ({ data }) =>
    orchestratorJson("/ui/team/rules", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  );

export const approveTeamRule = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson(`/ui/team/rules/${data.id}/approve`, { method: "POST" }),
  );

export const rejectTeamRule = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string(), reason: z.string().min(1).max(2000) }))
  .handler(async ({ data }) =>
    orchestratorJson(`/ui/team/rules/${data.id}/reject`, {
      method: "POST",
      body: JSON.stringify({ reason: data.reason }),
    }),
  );

export const patchTeamRule = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string(), pattern: z.string().min(3).max(2000) }))
  .handler(async ({ data }) =>
    orchestratorJson(`/ui/team/rules/${data.id}`, {
      method: "PATCH",
      body: JSON.stringify({ pattern: data.pattern }),
    }),
  );
