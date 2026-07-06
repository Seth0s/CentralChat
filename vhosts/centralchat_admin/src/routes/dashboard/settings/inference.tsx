import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  fetchGlobalModelsAllowlist,
  fetchInferenceProviders,
  fetchInferenceStatus,
  fetchTenantConfig,
  testInferenceProvider,
  updateGlobalModelsAllowlist,
  updateInferenceProvider,
  updateTenantModelsAllowlist,
} from "@/lib/api/inference";

export const Route = createFileRoute("/dashboard/settings/inference")({
  component: InferenceSettingsPage,
});

function InferenceSettingsPage() {
  const qc = useQueryClient();
  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const status = useQuery({
    queryKey: ["inference-status"],
    queryFn: () => fetchInferenceStatus(),
  });
  const providers = useQuery({
    queryKey: ["inference-providers"],
    queryFn: () => fetchInferenceProviders(),
  });
  const globalModels = useQuery({
    queryKey: ["inference-global-models"],
    queryFn: () => fetchGlobalModelsAllowlist(),
  });
  const tenantCfg = useQuery({
    queryKey: ["tenant-config", "default"],
    queryFn: () => fetchTenantConfig({ data: { tenantId: "default" } }),
    enabled: roleData?.role === "admin",
  });

  const [providerKey, setProviderKey] = useState<Record<string, string>>({});
  const [globalText, setGlobalText] = useState("");
  const [tenantText, setTenantText] = useState("");
  const [confirmProviderId, setConfirmProviderId] = useState<string | null>(
    null,
  );

  const isAdmin = roleData?.role === "admin";

  const providerMut = useMutation({
    mutationFn: (args: {
      providerId: string;
      apiKey?: string;
      enabled?: boolean;
    }) => updateInferenceProvider({ data: args }),
    onSuccess: (_result, variables) => {
      toast.success("Provider atualizado.");
      setProviderKey((current) => ({ ...current, [variables.providerId]: "" }));
      qc.invalidateQueries({ queryKey: ["inference-providers"] });
      qc.invalidateQueries({ queryKey: ["inference-status"] });
      qc.invalidateQueries({ queryKey: ["admin-secrets"] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const providerTestMut = useMutation({
    mutationFn: (providerId: string) =>
      testInferenceProvider({ data: { providerId } }),
    onSuccess: (result) => {
      if (result.ok) toast.success("Provider respondeu com sucesso.");
      else toast.error(`Teste falhou: ${result.message}`);
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const globalMut = useMutation({
    mutationFn: (modelIds: string[]) =>
      updateGlobalModelsAllowlist({ data: { modelIds } }),
    onSuccess: () => {
      toast.success("Allowlist global atualizada.");
      qc.invalidateQueries({ queryKey: ["inference-global-models"] });
      qc.invalidateQueries({ queryKey: ["inference-status"] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const tenantMut = useMutation({
    mutationFn: (modelIds: string[]) =>
      updateTenantModelsAllowlist({
        data: {
          tenantId: "default",
          modelIds,
          featuresJson: tenantCfg.data?.features_json,
        },
      }),
    onSuccess: () => {
      toast.success("Allowlist do tenant atualizada.");
      qc.invalidateQueries({ queryKey: ["tenant-config"] });
      qc.invalidateQueries({ queryKey: ["inference-status"] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const providerItems = providers.data?.items ?? [];
  const globalIds = globalModels.data?.model_ids ?? [];
  const tenantAllowlist =
    (tenantCfg.data?.features_json?.models_allowlist as string[] | undefined) ??
    [];

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-xl font-semibold">Inferência</h2>
        <p className="text-sm text-muted-foreground">
          Providers, allowlist global e por tenant. Segredos de provider são
          write-only; auditor vê apenas metadados em Segredos.
        </p>
      </div>

      {status.data && (
        <div className="rounded-lg border border-border p-4 text-sm">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Providers</dt>
              <dd>
                {status.data.providers_configured}/{status.data.providers_total}{" "}
                configurados
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Allowlist global</dt>
              <dd>
                {status.data.global_allowlist_restricted
                  ? `${status.data.global_allowlist_count} modelos`
                  : "sem restrição"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Allowlist tenant</dt>
              <dd>
                {status.data.tenant_allowlist_restricted
                  ? `${status.data.tenant_allowlist_count} modelos`
                  : "sem restrição"}
              </dd>
            </div>
          </dl>
        </div>
      )}

      <section className="space-y-3">
        <h3 className="font-medium">Providers</h3>
        <div className="space-y-2">
          {providerItems.map((provider) => (
            <div
              key={provider.id}
              className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3 text-sm"
            >
              <span className="min-w-[8rem] font-medium">{provider.label}</span>
              <span
                className={
                  provider.configured
                    ? "text-green-600"
                    : "text-muted-foreground"
                }
              >
                {provider.configured ? "configurado" : "não configurado"} (
                {provider.source})
              </span>
              {isAdmin && (
                <>
                  <Input
                    type="password"
                    placeholder="API key (write-only)"
                    className="max-w-xs"
                    value={providerKey[provider.id] ?? ""}
                    onChange={(event) =>
                      setProviderKey((current) => ({
                        ...current,
                        [provider.id]: event.target.value,
                      }))
                    }
                  />
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={
                      providerMut.isPending ||
                      !(providerKey[provider.id] ?? "").trim()
                    }
                    onClick={() => setConfirmProviderId(provider.id)}
                  >
                    Rotacionar
                  </Button>
                </>
              )}
              <Button
                size="sm"
                variant="outline"
                disabled={!isAdmin || providerTestMut.isPending}
                onClick={() => providerTestMut.mutate(provider.id)}
              >
                Testar
              </Button>
            </div>
          ))}
        </div>
      </section>

      {isAdmin && (
        <>
          <section className="space-y-3">
            <h3 className="font-medium">Allowlist global</h3>
            <p className="text-xs text-muted-foreground">
              Um <code>model_id</code> por linha. Vazio = sem restrição
              adicional além do ambiente.
            </p>
            <textarea
              className="min-h-[120px] w-full rounded-md border border-border bg-background p-2 font-mono text-sm"
              defaultValue={globalIds.join("\n")}
              onChange={(event) => setGlobalText(event.target.value)}
            />
            <Button
              size="sm"
              disabled={globalMut.isPending}
              onClick={() => {
                const ids = (globalText || globalIds.join("\n"))
                  .split("\n")
                  .map((line) => line.trim())
                  .filter(Boolean);
                globalMut.mutate(ids);
              }}
            >
              Atualizar global
            </Button>
          </section>

          <section className="space-y-3">
            <h3 className="font-medium">Allowlist tenant (default)</h3>
            <p className="text-xs text-muted-foreground">
              Subconjunto do global — não pode alargar além dele.
            </p>
            <textarea
              className="min-h-[100px] w-full rounded-md border border-border bg-background p-2 font-mono text-sm"
              defaultValue={tenantAllowlist.join("\n")}
              onChange={(event) => setTenantText(event.target.value)}
            />
            <Button
              size="sm"
              disabled={tenantMut.isPending}
              onClick={() => {
                const ids = (tenantText || tenantAllowlist.join("\n"))
                  .split("\n")
                  .map((line) => line.trim())
                  .filter(Boolean);
                tenantMut.mutate(ids);
              }}
            >
              Atualizar tenant
            </Button>
          </section>
        </>
      )}

      <AlertDialog
        open={Boolean(confirmProviderId)}
        onOpenChange={() => setConfirmProviderId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar rotação de provider</AlertDialogTitle>
            <AlertDialogDescription>
              Vai substituir a API key do provider{" "}
              <code>{confirmProviderId}</code>. Chamadas em curso podem falhar
              até a nova credencial propagar.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!confirmProviderId) return;
                providerMut.mutate({
                  providerId: confirmProviderId,
                  apiKey: providerKey[confirmProviderId],
                  enabled: true,
                });
                setConfirmProviderId(null);
              }}
            >
              Confirmar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
