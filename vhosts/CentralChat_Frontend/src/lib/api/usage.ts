import { createServerFn } from "@tanstack/react-start";
import { orchestratorJson } from "./orchestrator";

// ── Types ──

export type UsageStats = {
  period_start: string;
  period_end: string;
  tokens_input: number;
  tokens_output: number;
  total_tokens: number;
  cost_input: number;
  cost_output: number;
  total_cost: number;
  quota_limit: number;
  quota_pct: number;
  quota_enabled: boolean;
  period_label: string;
};

// ── Server Function ──

export const fetchUsage = createServerFn({ method: "GET" }).handler(async (): Promise<UsageStats | null> => {
  try {
    return await orchestratorJson<UsageStats>("/ui/usage");
  } catch {
    return null;
  }
});
