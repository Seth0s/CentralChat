/**
 * Orchestrator config + cloud models — server functions.
 */
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

// ── Config ──

export type OrchestratorConfig = {
  api_host: string;
  api_port: number;
  model_router_configured: boolean;
  model_router_url?: string;
  inference_resolve_error?: string;
  cloud_models_allowlist_edit_enabled: boolean;
  central_focus_mode: boolean;
  auth_login_enabled: boolean;
  auth_oidc_enabled: boolean;
  auth_oidc_configured: boolean;
  connector_status: {
    online: boolean;
    client_execution_enabled: boolean;
    connector_count: number;
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
};

export const fetchConfig = createServerFn({ method: "GET" }).handler(async () => {
  return orchestratorJson<OrchestratorConfig>("/config");
});

// ── Cloud Models (per-user, optimistic concurrency) ──

export type ModelEntry = {
  id: string;
  label: string;
  enabled: boolean;
  context_length?: number;
};

export type CloudModelsResponse = {
  models: ModelEntry[];
  version: number;
};

export const fetchCloudModels = createServerFn({ method: "GET" }).handler(async () => {
  try {
    return await orchestratorJson<CloudModelsResponse>("/ui/cloud-models");
  } catch {
    return { models: [], version: 0 };
  }
});

const putCloudModelsSchema = z.object({
  models: z.array(z.object({ id: z.string(), label: z.string(), enabled: z.boolean() })),
  version: z.number(),
  source: z.string().optional(),
});

export const putCloudModels = createServerFn({ method: "PUT" })
  .inputValidator(putCloudModelsSchema)
  .handler(async ({ data }) => {
    return orchestratorJson("/ui/cloud-models", {
      method: "PUT",
      body: JSON.stringify(data),
    });
  });

// ── Provider Routing (user_preferences) ──

const putProviderRoutingSchema = z.object({
  routing: z.enum(["cheapest", "fastest", "highest_throughput"]),
  version: z.number(),
});

export const saveProviderRouting = createServerFn({ method: "PUT" })
  .inputValidator(putProviderRoutingSchema)
  .handler(async ({ data }) => {
    return orchestratorJson("/ui/user-preferences", {
      method: "PUT",
      body: JSON.stringify({
        preferences: { provider_routing: data.routing },
        version: data.version,
      }),
    });
  });
