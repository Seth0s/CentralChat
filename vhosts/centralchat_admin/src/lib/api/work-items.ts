import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

export type WorkItem = {
  id: string;
  title: string;
  description?: string | null;
  status: string;
  priority: string;
  assignee_id?: string | null;
  session_id?: string | null;
  workspace_path?: string | null;
  source?: string;
  created_at?: string;
  updated_at?: string;
};

export type WorkItemEvent = {
  event_id: string;
  event_type: string;
  actor_id?: string | null;
  from_status?: string | null;
  to_status?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
};

export type WorkItemComment = {
  id: string;
  author_id: string;
  body: string;
  created_at: string;
};

export const fetchWorkItems = createServerFn({ method: "GET" })
  .inputValidator(z.object({ status: z.string().optional() }).optional())
  .handler(async ({ data }) => {
    const q = data?.status ? `?status=${encodeURIComponent(data.status)}` : "";
    return orchestratorJson<{ items: WorkItem[]; work_items_enabled: boolean }>(`/ui/work-items${q}`);
  });

export const fetchWorkItem = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson<{ item: WorkItem }>(`/ui/work-items/${data.id}`),
  );

export const fetchWorkItemEvents = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson<{ items: WorkItemEvent[]; work_items_enabled: boolean }>(
      `/ui/work-items/${data.id}/events`,
    ),
  );

export const fetchWorkItemComments = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) =>
    orchestratorJson<{ items: WorkItemComment[]; work_items_enabled: boolean }>(
      `/ui/work-items/${data.id}/comments`,
    ),
  );

export const patchWorkItem = createServerFn({ method: "POST" })
  .inputValidator(
    z.object({
      id: z.string(),
      status: z.string().optional(),
      assigneeId: z.string().optional().nullable(),
      title: z.string().optional(),
      priority: z.string().optional(),
      sessionId: z.string().optional().nullable(),
    }),
  )
  .handler(async ({ data }) => {
    const { id, assigneeId, sessionId, ...rest } = data;
    return orchestratorJson(`/ui/work-items/${id}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: rest.status,
        title: rest.title,
        priority: rest.priority,
        assignee_id: assigneeId,
        session_id: sessionId,
      }),
    });
  });

export const addWorkItemComment = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string(), body: z.string().min(1).max(4000) }))
  .handler(async ({ data }) =>
    orchestratorJson<{ comment: WorkItemComment; ok: boolean }>(
      `/ui/work-items/${data.id}/comments`,
      {
        method: "POST",
        body: JSON.stringify({ body: data.body }),
      },
    ),
  );
