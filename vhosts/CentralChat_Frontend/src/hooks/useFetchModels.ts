/**
 * useFetchModels — React Query hook for cloud models.
 * Per-user scoped via JWT (orchestrator resolves user_id).
 */
import { useQuery } from "@tanstack/react-query";
import { fetchCloudModels, type ModelEntry } from "@/lib/api/config";

export type { ModelEntry } from "@/lib/api/config";

export function useFetchModels() {
  return useQuery({
    queryKey: ["cloud-models"],
    queryFn: async (): Promise<ModelEntry[]> => {
      const res = await fetchCloudModels();
      return res.models || [];
    },
    staleTime: 60_000,
  });
}
