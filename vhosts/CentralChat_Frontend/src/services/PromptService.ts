/**
 * PromptService — Agents & Skills backed by orchestrator endpoints.
 * Per-user persistence via JWT (server-side).
 */
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchAgents as fetchAgentsFromApi,
  createAgent as createAgentApi,
  updateAgent as updateAgentApi,
  type Agent,
} from "@/lib/api/agents";
import {
  fetchSkills as fetchSkillsFromApi,
  createSkill as createSkillApi,
  updateSkill as updateSkillApi,
  type Skill,
} from "@/lib/api/skills";

// ── Re-export types ──

export type { Agent as IAgent, Skill as ISkill } from "@/lib/api/agents";
export type { Skill } from "@/lib/api/skills";

// ── Agents ──

const AGENTS_KEY = ["central", "agents"];

export function useAgents() {
  return useQuery({
    queryKey: AGENTS_KEY,
    queryFn: fetchAgentsFromApi,
    staleTime: 30_000,
  });
}

export function useSaveAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (agent: Partial<Agent> & { name: string; prompt: string }) => {
      if (agent.id && agent.version !== undefined) {
        await updateAgentApi({
          data: {
            id: agent.id,
            name: agent.name,
            prompt: agent.prompt,
            model_id: agent.model_id,
            version: agent.version,
          },
        });
      } else {
        await createAgentApi({
          data: {
            name: agent.name,
            prompt: agent.prompt,
            model_id: agent.model_id,
          },
        });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: AGENTS_KEY });
    },
  });
}

// ── Skills ──

const SKILLS_KEY = ["central", "skills"];

export function useSkills() {
  return useQuery({
    queryKey: SKILLS_KEY,
    queryFn: fetchSkillsFromApi,
    staleTime: 30_000,
  });
}

export function useSaveSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (skill: Partial<Skill> & { name: string }) => {
      if (skill.id && skill.version !== undefined) {
        await updateSkillApi({
          data: {
            id: skill.id,
            name: skill.name,
            description: skill.description,
            prompt: skill.prompt,
            enabled: skill.enabled,
            version: skill.version,
          },
        });
      } else {
        await createSkillApi({
          data: {
            name: skill.name,
            description: skill.description || "",
            prompt: skill.prompt || "",
          },
        });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: SKILLS_KEY });
    },
  });
}
