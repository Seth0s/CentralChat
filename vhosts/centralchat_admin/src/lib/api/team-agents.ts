import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { CATALOG_PROMPT_MAX_CHARS } from "@/lib/catalog-limits";
import { orchestratorJson } from "./orchestrator";

export type TeamAgent = {
  id: string;
  name: string;
  prompt: string;
  model_id?: string | null;
  icon?: string;
  published: boolean;
  lifecycle_status: "draft" | "review" | "published";
  version: number;
  updated_at?: string;
};

export const fetchTeamAgents = createServerFn({ method: "GET" })
  .inputValidator(
    z.object({ status: z.enum(["all", "draft", "review", "published"]).optional() }).optional(),
  )
  .handler(async ({ data }) => {
    const status = data?.status ?? "all";
    return orchestratorJson<{ items: TeamAgent[]; count: number; status: string }>(
      `/ui/team/agents?status=${status}`,
    );
  });

export const createTeamAgent = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      name: z.string().min(1).max(128),
      prompt: z.string().max(CATALOG_PROMPT_MAX_CHARS).optional(),
      modelId: z.string().max(256).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ agent: TeamAgent; lifecycle_status: string }>("/ui/team/agents", {
      method: "POST",
      body: JSON.stringify({
        name: data.name,
        prompt: data.prompt ?? "",
        model_id: data.modelId,
      }),
    }),
  );

export const patchTeamAgent = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      id: z.string(),
      name: z.string().max(128).optional(),
      prompt: z.string().max(CATALOG_PROMPT_MAX_CHARS).optional(),
      modelId: z.string().max(256).optional().nullable(),
    }),
  )
  .handler(async ({ data }) => {
    const { id, modelId, ...rest } = data;
    return orchestratorJson<{ agent: TeamAgent; ok: boolean }>(`/ui/team/agents/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ ...rest, model_id: modelId }),
    });
  });

export const submitTeamAgentReview = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson(`/ui/team/agents/${data.id}/submit-review`, { method: "POST" }),
  );

export const publishTeamAgent = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson(`/ui/team/agents/${data.id}/publish`, { method: "POST" }),
  );
