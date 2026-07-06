/**
 * HITL Approvals — server functions.
 */
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ApprovalRecord = Record<string, any> & {
  id: string;
  action_id: string;
  risk_level: string;
  status: string;
  created_at: string;
};

const idSchema = z.object({ id: z.string() });

export const fetchApprovals = createServerFn({ method: "GET" })
  .handler(async () => {
    const result = await orchestratorJson<{ items: ApprovalRecord[] }>("/approvals?status=pending");
    return result.items ?? [];
  });

export const approveApproval = createServerFn({ method: "POST" })
  .inputValidator(idSchema)
  .handler(async ({ data }) => orchestratorJson(`/approvals/${data.id}/approve`, { method: "POST" }));

export const denyApproval = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string(), reason: z.string().optional() }))
  .handler(async ({ data }) =>
    orchestratorJson(`/approvals/${data.id}/deny`, {
      method: "POST",
      body: data.reason ? JSON.stringify({ reason: data.reason }) : undefined,
    }),
  );

export const confirmDoubleApproval = createServerFn({ method: "POST" })
  .inputValidator(idSchema)
  .handler(async ({ data }) => orchestratorJson(`/approvals/${data.id}/confirm-double`, { method: "POST" }));
