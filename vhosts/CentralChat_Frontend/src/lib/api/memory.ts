/**
 * Memory context + RAG — server functions.
 */
import { createServerFn } from "@tanstack/react-start";
import { orchestratorJson } from "./orchestrator";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type MemoryContext = Record<string, any> & {
  blocks?: { id: string; content: string; namespace?: string }[];
};

export const fetchMemoryContext = createServerFn({ method: "GET" })
  .handler(async () => {
    try {
      return await orchestratorJson<MemoryContext>("/ui/memory-context");
    } catch {
      return { blocks: [] };
    }
  });

// ── Document RAG ──

export const uploadDocument = createServerFn({ method: "POST" })
  .handler(async ({ data }: { data: { name: string; content: string } }) => {
    return orchestratorJson("/document-rag/upload", {
      method: "POST",
      body: JSON.stringify(data),
    });
  });
