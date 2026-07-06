import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type CompliancePack = {
  id: string;
  name: string;
  framework: string;
  description_pt: string;
};

export const fetchCompliancePacks = createServerFn({ method: "GET" }).handler(async () => {
  return orchestratorJson<{ items: CompliancePack[]; count: number }>("/admin/compliance/packs");
});

export const fetchCompliancePack = createServerFn({ method: "GET" })
  .inputValidator(z.object({ packId: z.string().min(1) }))
  .handler(async ({ data }) => {
    return orchestratorJson<Record<string, unknown>>(`/admin/compliance/packs/${data.packId}`);
  });

export const applyCompliancePack = createServerFn({ method: "POST" })
  .inputValidator(z.object({ packId: z.string().min(1) }))
  .handler(async ({ data }) => {
    return orchestratorJson<Record<string, unknown>>("/admin/compliance/apply", {
      method: "POST",
      body: JSON.stringify({ pack_id: data.packId }),
    });
  });

export const fetchCompliancePreview = createServerFn({ method: "GET" })
  .inputValidator(z.object({ packId: z.string().min(1) }))
  .handler(async ({ data }) => {
    return orchestratorJson<Record<string, unknown>>(
      `/admin/compliance/packs/${data.packId}/preview`,
    );
  });

export const fetchDeployResidency = createServerFn({ method: "GET" }).handler(async () => {
  return orchestratorJson<{
    data_residency: string;
    llm_endpoint_region: string;
    telemetry_disabled: boolean;
    air_gap_mode: boolean;
  }>("/admin/deploy/residency");
});

export const fetchActiveBreakGlass = createServerFn({ method: "GET" }).handler(async () => {
  return orchestratorJson<{ items: Array<Record<string, unknown>>; count: number }>(
    "/admin/break-glass/active",
  );
});

export { fetchDeployStatus, grantBreakGlass, revokeBreakGlass } from "./ops";
