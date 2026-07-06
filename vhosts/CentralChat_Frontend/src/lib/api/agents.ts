/**
 * User agents — per-user agent personas. Server functions.
 */
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

// ── Types ──

export type Agent = {
  id: string;
  name: string;
  prompt: string;
  model_id: string | null;
  version: number;
  source: string;
  created_at: string;
  updated_at: string;
};

type AgentsResponse = { agents: Agent[] };
type AgentResponse = { agent: Agent };

// ── CRUD ──

export const fetchAgents = createServerFn({ method: "GET" }).handler(async () => {
  try {
    const res = await orchestratorJson<AgentsResponse>("/ui/agents");
    return res.agents;
  } catch {
    return [];
  }
});

const createAgentSchema = z.object({
  name: z.string().min(1),
  prompt: z.string().default(""),
  model_id: z.string().nullable().optional(),
});

export const createAgent = createServerFn({ method: "POST" })
  .inputValidator(createAgentSchema)
  .handler(async ({ data }): Promise<Agent> => {
    const res = await orchestratorJson<AgentResponse>("/ui/agents", {
      method: "POST",
      body: JSON.stringify(data),
    });
    return res.agent;
  });

const updateAgentSchema = z.object({
  id: z.string(),
  name: z.string().optional(),
  prompt: z.string().optional(),
  model_id: z.string().nullable().optional(),
  version: z.number(),
});

export const updateAgent = createServerFn({ method: "PATCH" })
  .inputValidator(updateAgentSchema)
  .handler(async ({ data }) => {
    const { id, ...body } = data;
    return orchestratorJson(`/ui/agents/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  });

export const deleteAgent = createServerFn({ method: "DELETE" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) => {
    return orchestratorJson(`/ui/agents/${data.id}`, { method: "DELETE" });
  });
