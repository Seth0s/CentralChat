/**
 * Agent Trees — CRUD + execute server functions.
 */
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AgentTree = Record<string, any> & {
  id: string;
  name: string;
  description?: string;
  root_node_id?: string;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AgentNode = Record<string, any> & {
  id: string;
  tree_id: string;
  parent_id?: string;
  agent_name?: string;
  model_id?: string;
  prompt?: string;
};

const treeSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
});

const nodeSchema = z.object({
  tree_id: z.string(),
  parent_id: z.string().optional(),
  agent_name: z.string().optional(),
  model_id: z.string().optional(),
  prompt: z.string().optional(),
});

// ── Trees ──

export const listAgentTrees = createServerFn({ method: "GET" })
  .handler(async () => orchestratorJson<AgentTree[]>("/agent-trees"));

export const createAgentTree = createServerFn({ method: "POST" })
  .inputValidator(treeSchema)
  .handler(async ({ data }) => orchestratorJson<AgentTree>("/agent-trees", {
    method: "POST", body: JSON.stringify(data),
  }));

export const getAgentTree = createServerFn({ method: "GET" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) => orchestratorJson(`/agent-trees/${data.id}`));

export const deleteAgentTree = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) => orchestratorJson(`/agent-trees/${data.id}`, { method: "DELETE" }));

// ── Nodes ──

export const listAgentNodes = createServerFn({ method: "GET" })
  .inputValidator(z.object({ tree_id: z.string() }))
  .handler(async ({ data }) => orchestratorJson<AgentNode[]>(`/agent-trees/${data.tree_id}/nodes`));

export const createAgentNode = createServerFn({ method: "POST" })
  .inputValidator(nodeSchema)
  .handler(async ({ data }) => {
    const { tree_id, ...rest } = data;
    return orchestratorJson<AgentNode>(`/agent-trees/${tree_id}/nodes`, {
      method: "POST", body: JSON.stringify(rest),
    });
  });
