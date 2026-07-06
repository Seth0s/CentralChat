import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type TeamRequest = {
  id: string;
  request_type: string;
  status: string;
  title: string;
  body?: string;
  requester_id?: string | null;
  assignee_id?: string | null;
  project_id?: string | null;
  session_id?: string | null;
  work_item_id?: string | null;
  resolution?: string | null;
  resolved_by?: string | null;
  resolved_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type TeamRequestComment = {
  id: string;
  request_id: string;
  author_id: string;
  body: string;
  created_at: string;
};

export const fetchTeamRequests = createServerFn({ method: "GET" })
  .inputValidator(
    z
      .object({
        status: z.string().optional(),
        projectId: z.string().optional(),
      })
      .optional(),
  )
  .handler(async ({ data }) => {
    const params = new URLSearchParams();
    if (data?.status) params.set("status", data.status);
    if (data?.projectId) params.set("project_id", data.projectId);
    const q = params.toString();
    return orchestratorJson<{
      items: TeamRequest[];
      count: number;
      requests_enabled: boolean;
    }>(`/admin/requests${q ? `?${q}` : ""}`);
  });

export const fetchTeamRequest = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson<{ request: TeamRequest; ok: boolean }>(
      `/admin/requests/${data.id}`,
    ),
  );

export const createTeamRequest = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      requestType: z.string(),
      title: z.string().min(1).max(500),
      body: z.string().max(4000).optional(),
      projectId: z.string().optional(),
      sessionId: z.string().optional(),
      workItemId: z.string().optional(),
      assigneeId: z.string().optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ request: TeamRequest; ok: boolean }>("/admin/requests", {
      method: "POST",
      body: JSON.stringify({
        request_type: data.requestType,
        title: data.title,
        body: data.body,
        project_id: data.projectId,
        session_id: data.sessionId,
        work_item_id: data.workItemId,
        assignee_id: data.assigneeId,
      }),
    }),
  );

export const resolveTeamRequest = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      id: z.string(),
      resolution: z.string().min(1).max(4000),
      status: z.enum(["resolved", "cancelled", "in_discussion"]).optional(),
    }),
  )
  .handler(async ({ data }) =>
    orchestratorJson<{ request: TeamRequest; ok: boolean }>(
      `/admin/requests/${data.id}/resolve`,
      {
        method: "POST",
        body: JSON.stringify({
          resolution: data.resolution,
          status: data.status ?? "resolved",
        }),
      },
    ),
  );

export const fetchTeamRequestComments = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson<{ items: TeamRequestComment[]; count: number }>(
      `/admin/requests/${data.id}/comments`,
    ),
  );

export const addTeamRequestComment = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string(), body: z.string().min(1).max(4000) }))
  .handler(async ({ data }) =>
    orchestratorJson<{ comment: TeamRequestComment; ok: boolean }>(
      `/admin/requests/${data.id}/comments`,
      {
        method: "POST",
        body: JSON.stringify({ body: data.body }),
      },
    ),
  );
