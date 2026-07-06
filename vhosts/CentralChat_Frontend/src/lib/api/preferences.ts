/**
 * Assistant preferences — server functions.
 */
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { orchestratorJson } from "./orchestrator";

const preferencesSchema = z.object({
  verbosity: z.enum(["short", "normal", "long"]).optional(),
  tone_hint: z.string().optional(),
  inference_destination: z.string().optional(),
  llm_model_id: z.string().optional(),
  default_include_long_session_memory: z.boolean().optional(),
  default_include_memory_recall: z.boolean().optional(),
  default_include_host_context: z.boolean().optional(),
  default_use_agent_tools: z.boolean().optional(),
});

export const savePreferences = createServerFn({ method: "POST" })
  .inputValidator(preferencesSchema)
  .handler(async ({ data }) => {
    return orchestratorJson("/ui/preferences", {
      method: "POST",
      body: JSON.stringify(data),
    });
  });
