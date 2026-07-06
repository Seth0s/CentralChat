import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type PolicyRepoRule = {
  pattern: string;
  read?: string;
  write?: string;
  approval?: string;
};

export type PolicyBundleHistoryItem = {
  bundle_id: string;
  version: number;
  status: string;
  label?: string | null;
  created_by?: string | null;
  created_at?: string;
};

export const fetchActivePolicy = createServerFn({ method: "GET" }).handler(async () =>
  orchestratorJson<{
    tenant_id: string;
    active: {
      bundle_id: string;
      bundle_version: number;
      repos: PolicyRepoRule[];
      tools: Record<string, { denied_patterns?: string[] }>;
    } | null;
    history_count: number;
  }>("/admin/policies/active"),
);

export const fetchPolicyHistory = createServerFn({ method: "GET" }).handler(async () =>
  orchestratorJson<{ items: PolicyBundleHistoryItem[]; count: number }>(
    "/admin/policies/history",
  ),
);

export const createPolicyDraft = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      label: z.string().max(200).optional(),
      repos: z.array(
        z.object({
          pattern: z.string().min(1),
          read: z.string().optional(),
          write: z.string().optional(),
          approval: z.string().optional(),
        }),
      ),
      tools: z.record(z.object({ denied_patterns: z.array(z.string()).optional() })).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson("/admin/policies/drafts", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  );

export const publishPolicyDraft = createServerFn({ method: "POST" })
  .inputValidator(z.object({ bundleId: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson(`/admin/policies/drafts/${data.bundleId}/publish`, {
      method: "POST",
    }),
  );

export const rollbackPolicy = createServerFn({ method: "POST" })
  .inputValidator(z.object({ version: z.number().int().min(1) }))
  .handler(async ({ data }) =>
    orchestratorJson("/admin/policies/rollback", {
      method: "POST",
      body: JSON.stringify({ version: data.version }),
    }),
  );
