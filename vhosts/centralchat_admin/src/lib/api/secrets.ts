import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type SecretMetadata = {
  key: string;
  category: string;
  label: string;
  configured: boolean;
  enabled: boolean;
  source: string;
  prefix: string | null;
  updated_at?: string | null;
  updated_by?: string | null;
  last_used_at?: string | null;
  last_test_at?: string | null;
  last_test_ok?: boolean | null;
  last_test_message?: string | null;
  active_version_count?: number | null;
  value_fingerprint?: string | null;
};

export const fetchAdminSecrets = createServerFn({ method: "GET" }).handler(
  async () => {
    return orchestratorJson<{
      items: SecretMetadata[];
      count: number;
      integration_keys_catalog?: Array<{
        key: string;
        label: string;
        category: string;
      }>;
      storage?: {
        backend_id: string;
        configured_backend: string;
        available?: boolean;
        read_only?: boolean;
        [key: string]: string | boolean | undefined;
      };
    }>("/admin/secrets");
  },
);

export const upsertAdminSecret = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      key: z.string(),
      value: z.string().min(1),
      label: z.string().optional(),
      category: z.string().optional(),
    }),
  )
  .handler(async ({ data }) => {
    return orchestratorJson<{ secret: SecretMetadata; ok: boolean }>(
      `/admin/secrets/${data.key}`,
      {
        method: "PUT",
        body: JSON.stringify({
          value: data.value,
          label: data.label,
          category: data.category,
        }),
      },
    );
  });

export const deleteAdminSecret = createServerFn({ method: "POST" })
  .inputValidator(z.object({ key: z.string() }))
  .handler(async ({ data }) => {
    return orchestratorJson<{ ok: boolean; key: string }>(
      `/admin/secrets/${data.key}`,
      {
        method: "DELETE",
      },
    );
  });

export const testAdminSecret = createServerFn({ method: "POST" })
  .inputValidator(z.object({ key: z.string() }))
  .handler(async ({ data }) => {
    return orchestratorJson<{ key: string; ok: boolean; message: string }>(
      `/admin/secrets/${data.key}/test`,
      { method: "POST", body: JSON.stringify({}) },
    );
  });
