/**
 * Session CRUD — server functions (BFF → orchestrator).
 */
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

// ── Types ──

export type ChatSession = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
};

// ── List ──

export const listSessions = createServerFn({ method: "GET" }).handler(async () => {
  const result = await orchestratorJson<{ items: ChatSession[]; chat_sessions_enabled: boolean }>("/ui/chat-sessions");
  return { sessions: result.items || [], chat_sessions_enabled: result.chat_sessions_enabled };
});

// ── Create ──

const createSchema = z.object({ title: z.string().min(1).max(200) });

export const createSession = createServerFn({ method: "POST" })
  .inputValidator(createSchema)
  .handler(async ({ data }) => {
    const result = await orchestratorJson<{ session: ChatSession }>("/ui/chat-sessions", {
      method: "POST",
      body: JSON.stringify(data),
    });
    return result.session;
  });

// ── Get ──

export const getSession = createServerFn({ method: "POST" })
  .handler(async ({ data }: { data: unknown }) => {
    const id = (data as { id?: string })?.id || "";
    if (!id) throw new Error("Session ID required");
    const result = await orchestratorJson<{ session: ChatSession & { messages?: { role: string; content: string }[] } }>(`/ui/chat-sessions/${id}`);
    return result.session;
  });

// ── Update (rename) ──

const updateSchema = z.object({ id: z.string(), title: z.string().min(1).max(200) });

export const updateSession = createServerFn({ method: "POST" })
  .inputValidator(updateSchema)
  .handler(async ({ data }) => {
    const { id, ...patch } = data;
    return orchestratorJson<ChatSession>(`/ui/chat-sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    });
  });

// ── Delete ──

export const deleteSession = createServerFn({ method: "POST" })
  .inputValidator(z.object({ id: z.string() }))
  .handler(async ({ data }) => {
    await orchestratorJson(`/ui/chat-sessions/${data.id}`, {
      method: "DELETE",
    });
    return { ok: true };
  });
