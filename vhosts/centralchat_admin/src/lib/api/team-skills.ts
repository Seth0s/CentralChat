import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { CATALOG_PROMPT_MAX_CHARS } from "@/lib/catalog-limits";
import { orchestratorJson } from "./orchestrator";

export type TeamSkill = {
  id: string;
  name: string;
  description: string;
  prompt: string;
  enabled: boolean;
  published: boolean;
  lifecycle_status: "draft" | "review" | "published";
  version: number;
  updated_at?: string;
};

export const fetchTeamSkills = createServerFn({ method: "GET" })
  .inputValidator(
    z.object({ status: z.enum(["all", "draft", "review", "published"]).optional() }).optional(),
  )
  .handler(async ({ data }) => {
    const status = data?.status ?? "all";
    return orchestratorJson<{ items: TeamSkill[]; count: number; status: string }>(
      `/ui/team/skills?status=${status}`,
    );
  });

export const createTeamSkill = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      name: z.string().min(1).max(128),
      prompt: z.string().max(CATALOG_PROMPT_MAX_CHARS).optional(),
      description: z.string().max(2000).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ skill: TeamSkill; lifecycle_status: string }>("/ui/team/skills", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  );

export const patchTeamSkill = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      id: z.string(),
      name: z.string().max(128).optional(),
      prompt: z.string().max(CATALOG_PROMPT_MAX_CHARS).optional(),
      description: z.string().max(2000).optional(),
    }),
  )
  .handler(async ({ data }) => {
    const { id, ...patch } = data;
    return orchestratorJson<{ skill: TeamSkill; ok: boolean }>(`/ui/team/skills/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  });

export const submitTeamSkillReview = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson(`/ui/team/skills/${data.id}/submit-review`, { method: "POST" }),
  );

export const publishTeamSkill = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson(`/ui/team/skills/${data.id}/publish`, { method: "POST" }),
  );
