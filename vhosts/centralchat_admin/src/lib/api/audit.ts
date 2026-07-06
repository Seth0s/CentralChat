import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type AuditEvent = {
  id: string;
  action: string;
  resource?: string | null;
  user_id?: string | null;
  session_id?: string | null;
  work_item_id?: string | null;
  created_at?: string;
  metadata?: Record<string, unknown>;
};

export const fetchAuditEvents = createServerFn({ method: "GET" })
  .inputValidator(
    z
      .object({
        since: z.string().optional(),
        action: z.string().optional(),
        user_id: z.string().optional(),
        path_prefix: z.string().optional(),
        limit: z.number().int().min(1).max(1000).optional(),
      })
      .optional(),
  )
  .handler(async ({ data }) => {
    const params = new URLSearchParams();
    params.set("limit", String(data?.limit ?? 200));
    if (data?.since) params.set("since", data.since);
    if (data?.action) params.set("action", data.action);
    if (data?.user_id) params.set("user_id", data.user_id);
    if (data?.path_prefix) params.set("path_prefix", data.path_prefix);
    return orchestratorJson<{ items: AuditEvent[]; count: number }>(
      `/admin/audit/events?${params.toString()}`,
    );
  });

export const exportAuditCsv = createServerFn({ method: "GET" })
  .inputValidator(z.object({ since: z.string().optional(), userId: z.string().optional(), action: z.string().optional(), pathPrefix: z.string().optional() }).optional())
  .handler(async ({ data }) => {
    const params = new URLSearchParams({ format: "csv", limit: "5000" });
    if (data?.since) params.set("since", data.since);
    if (data?.userId) params.set("user_id", data.userId);
    if (data?.action) params.set("action", data.action);
    if (data?.pathPrefix) params.set("path_prefix", data.pathPrefix);
    const ORCH_URL = process.env.VITE_ORCHESTRATOR_PROXY_TARGET || "http://localhost:8004";
    const { getCookie } = await import("@tanstack/react-start/server");
    const token = getCookie("central_access_token");
    const res = await fetch(`${ORCH_URL}/admin/audit/export?${params}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`export failed (${res.status})`);
    return res.text();
  });

export const exportAuditReportPdf = createServerFn({ method: "GET" })
  .inputValidator(
    z
      .object({
        since: z.string().optional(),
        pathPrefix: z.string().optional(),
        userId: z.string().optional(),
        action: z.string().optional(),
      })
      .optional(),
  )
  .handler(async ({ data }) => {
    const params = new URLSearchParams({ format: "pdf", limit: "5000" });
    if (data?.since) params.set("since", data.since);
    if (data?.pathPrefix) params.set("path_prefix", data.pathPrefix);
    if (data?.userId) params.set("user_id", data.userId);
    if (data?.action) params.set("action", data.action);
    const ORCH_URL = process.env.VITE_ORCHESTRATOR_PROXY_TARGET || "http://localhost:8004";
    const { getCookie } = await import("@tanstack/react-start/server");
    const token = getCookie("central_access_token");
    const res = await fetch(`${ORCH_URL}/admin/audit/report?${params}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`report failed (${res.status})`);
    const buf = await res.arrayBuffer();
    return Buffer.from(buf).toString("base64");
  });

export type AuditExportJob = {
  id: string;
  status: string;
  format: string;
  since?: string | null;
  row_count?: number | null;
  error?: string | null;
  created_at?: string;
  completed_at?: string | null;
  download_ready?: boolean;
};

export const createAuditExportJob = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      format: z.enum(["csv", "json"]).optional(),
      since: z.string().optional(),
      userId: z.string().optional(),
      action: z.string().optional(),
      pathPrefix: z.string().optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ job: AuditExportJob; ok: boolean }>("/admin/audit/exports", {
      method: "POST",
      body: JSON.stringify({
        format: data.format ?? "csv",
        since: data.since,
        user_id: data.userId,
        action: data.action,
        path_prefix: data.pathPrefix,
      }),
    }),
  );

export const fetchAuditExportJobs = createServerFn({ method: "GET" }).handler(async () =>
  orchestratorJson<{ items: AuditExportJob[]; count: number }>("/admin/audit/exports"),
);

export const fetchAuditExportJob = createServerFn({ method: "POST" })
  .inputValidator(z.object({ jobId: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson<{ job: AuditExportJob; ok: boolean }>(
      `/admin/audit/exports/${data.jobId}`,
    ),
  );

export const downloadAuditExportJob = createServerFn({ method: "POST" })
  .inputValidator(z.object({ jobId: z.string() }))
  .handler(async ({ data }) => {
    const ORCH_URL = process.env.VITE_ORCHESTRATOR_PROXY_TARGET || "http://localhost:8004";
    const { getCookie } = await import("@tanstack/react-start/server");
    const token = getCookie("central_access_token");
    const res = await fetch(`${ORCH_URL}/admin/audit/exports/${data.jobId}/download`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(`download failed (${res.status})`);
    const text = await res.text();
    const contentType = res.headers.get("content-type") || "";
    return { body: text, contentType };
  });
