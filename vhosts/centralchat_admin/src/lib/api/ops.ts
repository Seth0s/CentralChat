import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type DeployStatus = {
  tenant_id: string;
  environment: string;
  health: { postgres: string; memory_db_enabled: boolean };
  residency: Record<string, unknown>;
  feature_flags: Record<string, unknown>;
  siem: Record<string, unknown>;
  migrations: {
    total_files: number;
    applied_count: number;
    pending_count: number;
    pending: string[];
  };
  backup: Record<string, unknown>;
};

export type SiemOutboxSummary = {
  status: string;
  webhooks_configured: number;
  hec_token_configured: boolean;
  pending: number;
  delivered: number;
  dead: number;
  last_error?: string | null;
  oldest_pending_at?: string | null;
};

export const fetchDeployStatus = createServerFn({ method: "GET" }).handler(async () =>
  orchestratorJson<DeployStatus>("/admin/deploy/status"),
);

export const fetchSiemOutbox = createServerFn({ method: "GET" }).handler(async () =>
  orchestratorJson<{ summary: SiemOutboxSummary; ok: boolean }>("/admin/siem/outbox"),
);

export const processSiemOutbox = createServerFn({ method: "POST" }).handler(async () =>
  orchestratorJson<{ counts: Record<string, number>; ok: boolean }>(
    "/admin/siem/outbox/process",
    { method: "POST" },
  ),
);

export const grantBreakGlass = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      pathPattern: z.string().min(1).max(500),
      reason: z.string().min(3).max(2000),
      userId: z.string().optional(),
      ttlHours: z.number().min(0.25).max(24).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson("/admin/break-glass/grant", {
      method: "POST",
      body: JSON.stringify({
        path_pattern: data.pathPattern,
        reason: data.reason,
        user_id: data.userId,
        ttl_hours: data.ttlHours,
      }),
    }),
  );

export const revokeBreakGlass = createServerFn({ method: "POST" })
  .inputValidator(z.object({ grantId: z.string() }))
  .handler(async ({ data }) => {
    await orchestratorJson(`/admin/break-glass/${data.grantId}`, { method: "DELETE" });
    return { ok: true };
  });
