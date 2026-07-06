import { create } from "zustand";
import { persist } from "zustand/middleware";

// ── Types ──

export type InferenceMode = "central_api" | "byok";

export type ApiKeys = {
  openrouter?: string;
  openai?: string;
  deepseek?: string;
  [provider: string]: string | undefined;
};

export type ModelParams = {
  temperature: number;
  topP: number;
  nitro?: boolean;
  reasoning?: boolean;
};

type AISettingsState = {
  // ── Inference mode ──
  inferenceMode: InferenceMode;
  setInferenceMode: (mode: InferenceMode) => void;

  // ── API Keys (BYOK) ──
  apiKeys: ApiKeys;
  setApiKey: (provider: string, key: string) => void;
  removeApiKey: (provider: string) => void;

  // ── Enabled models ──
  enabledModels: string[];
  toggleModel: (modelId: string) => void;
  setEnabledModels: (models: string[]) => void;

  // ── Global parameters ──
  parameters: ModelParams;
  setParameters: (params: Partial<ModelParams>) => void;

  // ── Per-model parameters ──
  modelParams: Record<string, Partial<ModelParams>>;
  setModelParams: (modelId: string, params: Partial<ModelParams>) => void;

  // ── Token usage (stream telemetry) ──
  tokenUsage: { promptTokens: number; completionTokens: number; totalTokens: number };
  contextLimit: number;
  activeProvider: string | null;
  updateTokenUsage: (usage: { promptTokens?: number; completionTokens?: number; totalTokens?: number }) => void;
  setContextLimit: (limit: number) => void;
  setActiveProvider: (provider: string) => void;
  resetTokenUsage: () => void;

  // Tier profiles (model selection per tier)
  tierProfiles: Record<string, { models: string[]; version: number }>;
  setTierProfile: (tier: string, profile: Record<string, unknown>) => void;

  // Provider routing (user preference — cheapest/fastest/highest_throughput)
  providerRouting: string;
  setProviderRouting: (routing: string) => void;

  // ── Reset ──
  clearHistory: () => void;
};

export const useAISettingsStore = create<AISettingsState>()(
  persist(
    (set) => ({
      // ── Defaults ──
      inferenceMode: "central_api",
      setInferenceMode: (mode) => set({ inferenceMode: mode }),

      apiKeys: {},
      setApiKey: (provider, key) =>
        set((s) => ({ apiKeys: { ...s.apiKeys, [provider]: key } })),
      removeApiKey: (provider) =>
        set((s) => {
          const { [provider]: _, ...rest } = s.apiKeys;
          return { apiKeys: rest };
        }),

      enabledModels: [],
      toggleModel: (modelId) =>
        set((s) => ({
          enabledModels: s.enabledModels.includes(modelId)
            ? s.enabledModels.filter((m) => m !== modelId)
            : [...s.enabledModels, modelId],
        })),
      setEnabledModels: (models) => set({ enabledModels: models }),

      parameters: { temperature: 0.7, topP: 0.9 },
      setParameters: (params) =>
        set((s) => ({ parameters: { ...s.parameters, ...params } })),

      modelParams: {},
      setModelParams: (modelId, params) =>
        set((s) => ({
          modelParams: {
            ...s.modelParams,
            [modelId]: { ...(s.modelParams[modelId] || {}), ...params },
          },
        })),

      tokenUsage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 },
      contextLimit: 128_000,
      activeProvider: null,
      updateTokenUsage: (usage) =>
        set((s) => ({
          tokenUsage: {
            promptTokens: usage.promptTokens ?? s.tokenUsage.promptTokens,
            completionTokens: usage.completionTokens ?? s.tokenUsage.completionTokens,
            totalTokens: usage.totalTokens ?? s.tokenUsage.totalTokens,
          },
        })),
      setContextLimit: (limit) => set({ contextLimit: limit }),
      setActiveProvider: (provider) => set({ activeProvider: provider }),
      resetTokenUsage: () =>
        set({ tokenUsage: { promptTokens: 0, completionTokens: 0, totalTokens: 0 }, activeProvider: null }),

      tierProfiles: {},
      setTierProfile: (tier, profile) =>
        set((s) => ({
          tierProfiles: { ...s.tierProfiles, [tier]: { ...s.tierProfiles[tier], ...profile } as typeof s.tierProfiles[string] },
        })),

      providerRouting: "cheapest",
      setProviderRouting: (routing) => set({ providerRouting: routing }),

      clearHistory: () => {
        // Dispatch custom event — chat page listens and clears messages
        window.dispatchEvent(new CustomEvent("central:clearHistory"));
      },
    }),
    {
      name: "central-ai-settings",
      partialize: (state) => ({
        // NEVER persist API keys
        inferenceMode: state.inferenceMode,
        enabledModels: state.enabledModels,
        parameters: state.parameters,
        modelParams: state.modelParams,
        providerRouting: state.providerRouting,
      }),
    },
  ),
);
