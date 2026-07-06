import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type InferenceProvider = {
  id: string;
  label: string;
  configured: boolean;
  enabled: boolean;
  source: string;
};

export type InferenceStatus = {
  providers: InferenceProvider[];
  providers_configured: number;
  providers_total: number;
  global_allowlist_count: number;
  global_allowlist_restricted: boolean;
  tenant_allowlist_count: number;
  tenant_allowlist_restricted: boolean;
};

export const fetchInferenceStatus = createServerFn({ method: "GET" }).handler(
  async () => {
    return orchestratorJson<InferenceStatus>("/admin/inference/status");
  },
);

export const fetchInferenceProviders = createServerFn({
  method: "GET",
}).handler(async () => {
  return orchestratorJson<{ items: InferenceProvider[]; count: number }>(
    "/admin/inference/providers",
  );
});

export const fetchGlobalModelsAllowlist = createServerFn({
  method: "GET",
}).handler(async () => {
  return orchestratorJson<{ model_ids: string[]; restricted: boolean }>(
    "/admin/inference/models/global",
  );
});

export const updateGlobalModelsAllowlist = createServerFn({ method: "POST" })
  .inputValidator(z.object({ modelIds: z.array(z.string()) }))
  .handler(async ({ data }) => {
    return orchestratorJson<{ model_ids: string[]; ok: boolean }>(
      "/admin/inference/models/global",
      {
        method: "PUT",
        body: JSON.stringify({ model_ids: data.modelIds }),
      },
    );
  });

export const updateInferenceProvider = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      providerId: z.string(),
      apiKey: z.string().optional(),
      enabled: z.boolean().optional(),
    }),
  )
  .handler(async ({ data }) => {
    const body: Record<string, unknown> = {};
    if (data.apiKey !== undefined) body.api_key = data.apiKey;
    if (data.enabled !== undefined) body.enabled = data.enabled;
    return orchestratorJson<{ ok: boolean; provider: InferenceProvider }>(
      `/admin/inference/providers/${data.providerId}`,
      {
        method: "PUT",
        body: JSON.stringify(body),
      },
    );
  });

export const testInferenceProvider = createServerFn({ method: "POST" })
  .inputValidator(z.object({ providerId: z.string() }))
  .handler(async ({ data }) => {
    return orchestratorJson<{
      provider_id: string;
      ok: boolean;
      message: string;
    }>(`/admin/inference/providers/${data.providerId}/test`, {
      method: "POST",
      body: JSON.stringify({}),
    });
  });

export const fetchTenantConfig = createServerFn({ method: "GET" })
  .inputValidator(z.object({ tenantId: z.string() }))
  .handler(async ({ data }) => {
    return orchestratorJson<{
      tenant_id: string;
      features_json: Record<string, unknown>;
    }>(`/admin/tenant-config/${data.tenantId}`);
  });

export const updateTenantModelsAllowlist = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      tenantId: z.string(),
      modelIds: z.array(z.string()),
      featuresJson: z.record(z.unknown()).optional(),
    }),
  )
  .handler(async ({ data }) => {
    const features = {
      ...(data.featuresJson ?? {}),
      models_allowlist: data.modelIds,
    };
    return orchestratorJson(`/admin/tenant-config/${data.tenantId}`, {
      method: "POST",
      body: JSON.stringify({ features_json: features }),
    });
  });
