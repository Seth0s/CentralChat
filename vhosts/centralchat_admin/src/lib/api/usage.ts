import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type UsageSummary = {
  tenant_id: string;
  window: string;
  total_tokens: number;
  total_cost: number;
  monthly_limit: number;
  monthly_pct: number;
  hours: Array<{
    period_start: string;
    tokens_input: number;
    tokens_output: number;
    total_tokens: number;
    total_cost: number;
  }>;
};

export const fetchUsageSummary = createServerFn({ method: "GET" })
  .inputValidator(z.object({ window: z.enum(["24h", "7d", "30d"]).optional() }).optional())
  .handler(async ({ data }) => {
    const w = data?.window ?? "7d";
    return orchestratorJson<UsageSummary>(`/admin/usage/summary?window=${w}`);
  });
