import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  deleteAdminSecret,
  fetchAdminSecrets,
  testAdminSecret,
  upsertAdminSecret,
  type SecretMetadata,
} from "@/lib/api/secrets";

export const Route = createFileRoute("/dashboard/settings/secrets")({
  component: SecretsSettingsPage,
});

function SecretsSettingsPage() {
  const qc = useQueryClient();
  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const secretsQuery = useQuery({
    queryKey: ["admin-secrets"],
    queryFn: () => fetchAdminSecrets(),
  });

  const [createForm, setCreateForm] = useState({
    key: "",
    label: "",
    category: "custom",
    value: "",
  });
  const [pendingValues, setPendingValues] = useState<Record<string, string>>(
    {},
  );
  const [confirmRotate, setConfirmRotate] = useState<SecretMetadata | null>(
    null,
  );
  const [confirmRevoke, setConfirmRevoke] = useState<SecretMetadata | null>(
    null,
  );

  const isAdmin = roleData?.role === "admin";
  const items = secretsQuery.data?.items ?? [];
  const envSourcedProviders = items.filter(
    (item) => item.category === "provider" && item.source === "env",
  );

  const upsertMut = useMutation({
    mutationFn: (data: {
      key: string;
      value: string;
      label?: string;
      category?: string;
    }) => upsertAdminSecret({ data }),
    onSuccess: (_result, variables) => {
      toast.success("Segredo atualizado.");
      setPendingValues((current) => ({ ...current, [variables.key]: "" }));
      setCreateForm({ key: "", label: "", category: "custom", value: "" });
      qc.invalidateQueries({ queryKey: ["admin-secrets"] });
      qc.invalidateQueries({ queryKey: ["inference-providers"] });
      qc.invalidateQueries({ queryKey: ["inference-status"] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const deleteMut = useMutation({
    mutationFn: (key: string) => deleteAdminSecret({ data: { key } }),
    onSuccess: () => {
      toast.success("Segredo revogado.");
      qc.invalidateQueries({ queryKey: ["admin-secrets"] });
      qc.invalidateQueries({ queryKey: ["inference-providers"] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const testMut = useMutation({
    mutationFn: (key: string) => testAdminSecret({ data: { key } }),
    onSuccess: (result) => {
      if (result.ok) toast.success("Teste concluído com sucesso.");
      else toast.error(`Teste falhou: ${result.message}`);
    },
    onError: (error) => toast.error((error as Error).message),
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Segredos</h2>
        <p className="text-sm text-muted-foreground">
          Metadados visíveis para admin e auditor. Valores são write-only e
          nunca retornam completos pela API.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Com{" "}
          <code className="rounded bg-muted px-1">CENTRAL_VAULT_MASTER_KEY</code>{" "}
          definida, segredos em disco são encriptados (AES-256-GCM). Backend
          activo:{" "}
          <code className="rounded bg-muted px-1">
            {secretsQuery.data?.storage?.backend_id ?? "filesystem"}
          </code>
          {secretsQuery.data?.storage?.read_only ? " (read-only)" : ""}.
        </p>
      </div>

      {envSourcedProviders.length > 0 && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertTitle>Variáveis de ambiente activas</AlertTitle>
          <AlertDescription>
            {envSourcedProviders.length === 1
              ? `O segredo ${envSourcedProviders[0].label} está definido via variável de ambiente.`
              : `${envSourcedProviders.length} providers estão definidos via variável de ambiente.`}{" "}
            Rotações feitas aqui não terão efeito até remover a env var
            correspondente e reiniciar o serviço.
          </AlertDescription>
        </Alert>
      )}

      <Alert>
        <Info className="h-4 w-4" />
        <AlertTitle>Inferência LLM</AlertTitle>
        <AlertDescription>
          As chamadas de chat passam actualmente pelo OpenRouter. Chaves de
          outros providers (Anthropic, OpenAI, Google, DeepSeek) servem para
          governança de catálogo e teste de conexão — modelos{" "}
          <code className="rounded bg-muted px-1">deepseek/*</code> via
          OpenRouter usam a chave OpenRouter.
        </AlertDescription>
      </Alert>

      {secretsQuery.isLoading && (
        <p className="text-sm text-muted-foreground">A carregar segredos...</p>
      )}
      {secretsQuery.error && (
        <p className="text-sm text-destructive">
          {(secretsQuery.error as Error).message}
        </p>
      )}

      {isAdmin && (
        <section className="rounded-lg border border-border bg-card p-4">
          <h3 className="font-medium">
            Criar ou rotacionar segredo customizado
          </h3>
          <form
            className="mt-3 grid gap-3 md:grid-cols-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (!createForm.key.trim() || !createForm.value.trim()) return;
              upsertMut.mutate({
                key: createForm.key.trim(),
                value: createForm.value,
                label: createForm.label || undefined,
                category: createForm.category || undefined,
              });
            }}
          >
            <Input
              placeholder="chave (ex: siem.webhook)"
              value={createForm.key}
              onChange={(event) =>
                setCreateForm((form) => ({ ...form, key: event.target.value }))
              }
              required
            />
            <Input
              placeholder="rótulo opcional"
              value={createForm.label}
              onChange={(event) =>
                setCreateForm((form) => ({
                  ...form,
                  label: event.target.value,
                }))
              }
            />
            <Input
              placeholder="categoria (webhook, integration...)"
              value={createForm.category}
              onChange={(event) =>
                setCreateForm((form) => ({
                  ...form,
                  category: event.target.value,
                }))
              }
            />
            <Input
              type="password"
              placeholder="valor do segredo"
              value={createForm.value}
              onChange={(event) =>
                setCreateForm((form) => ({
                  ...form,
                  value: event.target.value,
                }))
              }
              required
            />
            <div className="md:col-span-2">
              <Button type="submit" size="sm" disabled={upsertMut.isPending}>
                Guardar segredo
              </Button>
            </div>
          </form>
        </section>
      )}

      <section className="rounded-lg border border-border bg-card p-4">
        <h3 className="font-medium">Chaves de integração suportadas</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Segredos custom com estas chaves são consumidos pelo runtime (env tem
          prioridade).
        </p>
        <ul className="mt-3 space-y-2 text-sm">
          {(secretsQuery.data?.integration_keys_catalog ?? [
            { key: "siem.webhook", label: "SIEM webhook URLs", category: "integration" },
            { key: "siem.hec_token", label: "SIEM HEC token", category: "integration" },
            { key: "alert.webhook", label: "Ops alert webhook", category: "integration" },
            { key: "quota.webhook", label: "Quota alert webhook", category: "integration" },
          ]).map((entry) => (
            <li key={entry.key} className="font-mono text-xs">
              {entry.key}{" "}
              <span className="font-sans text-muted-foreground">
                — {entry.label}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-lg border border-border bg-card">
        <div className="border-b border-border px-4 py-3">
          <h3 className="font-medium">Inventário de segredos</h3>
        </div>
        {items.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">
            Nenhum segredo registado.
          </p>
        ) : (
          <TooltipProvider>
            <ul className="divide-y divide-border">
              {items.map((item) => (
                <li key={item.key} className="space-y-3 px-4 py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-medium">
                        {item.label}
                        {item.category === "provider" && (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <button
                                type="button"
                                className="ml-1.5 inline-flex text-muted-foreground hover:text-foreground"
                                aria-label="Informação sobre provider"
                              >
                                <Info className="h-3.5 w-3.5" />
                              </button>
                            </TooltipTrigger>
                            <TooltipContent side="top" className="max-w-xs">
                              {item.source === "env"
                                ? "Definido por variável de ambiente — rotação no admin não surte efeito."
                                : item.key === "provider:openrouter"
                                  ? "Usado nas chamadas de inferência via OpenRouter."
                                  : "Usado para governança de catálogo e teste; inferência directa ainda não activa."}
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </p>
                    <p className="font-mono text-xs text-muted-foreground">
                      {item.key}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {item.category} ·{" "}
                      {item.configured ? "configurado" : "não configurado"} ·
                      origem {item.source}
                      {item.prefix ? ` · prefixo ${item.prefix}` : ""}
                    </p>
                    {item.updated_at && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Atualizado em {item.updated_at}
                      </p>
                    )}
                    {item.last_test_at && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        Último teste: {item.last_test_at}
                        {item.last_test_ok === false ? " (falhou)" : ""}
                      </p>
                    )}
                    {typeof item.active_version_count === "number" &&
                      item.active_version_count > 0 && (
                        <p className="mt-1 text-xs text-muted-foreground">
                          Versões activas: {item.active_version_count}
                        </p>
                      )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={!isAdmin || testMut.isPending}
                      onClick={() => testMut.mutate(item.key)}
                    >
                      Testar
                    </Button>
                    {isAdmin && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={deleteMut.isPending}
                        onClick={() => setConfirmRevoke(item)}
                      >
                        Revogar
                      </Button>
                    )}
                  </div>
                </div>
                {isAdmin && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Input
                      type="password"
                      className="max-w-sm"
                      placeholder="novo valor (write-only)"
                      value={pendingValues[item.key] ?? ""}
                      onChange={(event) =>
                        setPendingValues((current) => ({
                          ...current,
                          [item.key]: event.target.value,
                        }))
                      }
                    />
                    <Button
                      type="button"
                      size="sm"
                      disabled={
                        upsertMut.isPending ||
                        !(pendingValues[item.key] ?? "").trim()
                      }
                      onClick={() => setConfirmRotate(item)}
                    >
                      Rotacionar
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          </TooltipProvider>
        )}
      </section>

      <AlertDialog
        open={Boolean(confirmRotate)}
        onOpenChange={() => setConfirmRotate(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar rotação</AlertDialogTitle>
            <AlertDialogDescription>
              Vai substituir o segredo <code>{confirmRotate?.key}</code>.
              Serviços que dependem deste valor podem falhar até a nova
              credencial propagar.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!confirmRotate) return;
                const value = pendingValues[confirmRotate.key] ?? "";
                upsertMut.mutate({ key: confirmRotate.key, value });
                setConfirmRotate(null);
              }}
            >
              Confirmar rotação
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog
        open={Boolean(confirmRevoke)}
        onOpenChange={() => setConfirmRevoke(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar revogação</AlertDialogTitle>
            <AlertDialogDescription>
              O segredo <code>{confirmRevoke?.key}</code> deixará de estar
              disponível para o runtime.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (!confirmRevoke) return;
                deleteMut.mutate(confirmRevoke.key);
                setConfirmRevoke(null);
              }}
            >
              Confirmar revogação
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
