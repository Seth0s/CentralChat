/**
 * User skills — per-user skill blocks. Server functions.
 */
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

// ── Types ──

export type Skill = {
  id: string;
  name: string;
  description: string;
  prompt: string;
  enabled: boolean;
  version: number;
  source: string;
  created_at: string;
  updated_at: string;
};

type SkillsResponse = { skills: Skill[] };
type SkillResponse = { skill: Skill };

// ── CRUD ──

export const fetchSkills = createServerFn({ method: "GET" }).handler(async () => {
  try {
    const res = await orchestratorJson<SkillsResponse>("/ui/skills");
    return res.skills;
  } catch {
    return [];
  }
});

const createSkillSchema = z.object({
  name: z.string().min(1),
  description: z.string().default(""),
  prompt: z.string().default(""),
});

export const createSkill = createServerFn({ method: "POST" })
  .inputValidator(createSkillSchema)
  .handler(async ({ data }): Promise<Skill> => {
    const res = await orchestratorJson<SkillResponse>("/ui/skills", {
      method: "POST",
      body: JSON.stringify(data),
    });
    return res.skill;
  });

const updateSkillSchema = z.object({
  id: z.string(),
  name: z.string().optional(),
  description: z.string().optional(),
  prompt: z.string().optional(),
  enabled: z.boolean().optional(),
  version: z.number(),
});

export const updateSkill = createServerFn({ method: "PATCH" })
  .inputValidator(updateSkillSchema)
  .handler(async ({ data }) => {
    const { id, ...body } = data;
    return orchestratorJson(`/ui/skills/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  });

export const deleteSkill = createServerFn({ method: "DELETE" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) => {
    return orchestratorJson(`/ui/skills/${data.id}`, { method: "DELETE" });
  });
