/** Keep in sync with `app/shared/catalog_limits.py` (default 64_000). */
export const CATALOG_PROMPT_MAX_CHARS = 64_000;

/** Rough heuristic: ~4 characters per token for Latin scripts. */
export function estimatePromptTokens(charCount: number): number {
  return Math.ceil(charCount / 4);
}
