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
  createPolicyDraft,
  fetchActivePolicy,
  fetchPolicyHistory,
  publishPolicyDraft,
  rollbackPolicy,
} from "@/lib/api/policies";

export const Route = createFileRoute("/dashboard/policies")({
  component: PoliciesPage,
});

function PoliciesPage() {
  const qc = useQueryClient();
  const [draftLabel, setDraftLabel] = useState("Revisão admin");
  const [repoPattern, setRepoPattern] = useState("**/payment/**");
  const [repoWrite, setRepoWrite] = useState("approval_required");
  const [rollbackVersion, setRollbackVersion] = useState("");
  const [confirmRollback, setConfirmRollback] = useState(false);
  const [lastDraftId, setLastDraftId] = useState<string | null>(null);

  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const canEdit = roleData?.role === "lead" || roleData?.role === "admin";
  const canRollback = roleData?.role === "admin";

  const activeQuery = useQuery({
    queryKey: ["policy-active"],
    queryFn: () => fetchActivePolicy(),
  });
  const historyQuery = useQuery({
    queryKey: ["policy-history"],
    queryFn: () => fetchPolicyHistory(),
  });

  const draftMut = useMutation({
    mutationFn: () => {
      const active = activeQuery.data?.active;
      const repos = active?.repos?.length
        ? active.repos
        : [{ pattern: repoPattern, write: repoWrite }];
      return createPolicyDraft({
        data: {
          label: draftLabel,
          repos,
          tools: active?.tools ?? {},
        },
      });
    },
    onSuccess: (result: { bundle?: { bundle_id?: string } }) => {
      const id = result?.bundle?.bundle_id;
      if (id) setLastDraftId(id);
      toast.success("Draft de policy criado.");
      qc.invalidateQueries({ queryKey: ["policy-history"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const publishMut = useMutation({
    mutationFn: (bundleId: string) =>
      publishPolicyDraft({ data: { bundleId } }),
    onSuccess: () => {
      toast.success("Policy publicada.");
      setLastDraftId(null);
      qc.invalidateQueries({ queryKey: ["policy-active"] });
      qc.invalidateQueries({ queryKey: ["policy-history"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const rollbackMut = useMutation({
    mutationFn: (version: number) => rollbackPolicy({ data: { version } }),
    onSuccess: () => {
      toast.success("Rollback aplicado.");
      setConfirmRollback(false);
      qc.invalidateQueries({ queryKey: ["policy-active"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const active = activeQuery.data?.active;
  const history = historyQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Policies</h2>
        <p className="text-sm text-muted-foreground">
          Bundle activo, histórico versionado, draft/publish e rollback (admin).
        </p>
      </div>

      <section className="rounded-lg border border-border p-4">
        <h3 className="font-medium">Policy activa</h3>
        {activeQuery.isLoading ? (
          <p className="mt-2 text-sm text-muted-foreground">A carregar…</p>
        ) : !active ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Sem bundle PG activo — usa defaults do ficheiro/tenant.
          </p>
        ) : (
          <div className="mt-2 space-y-2 text-sm">
            <p>
              Versão <strong>{active.bundle_version}</strong> · ID{" "}
              <code className="text-xs">{active.bundle_id}</code>
            </p>
            <ul className="space-y-1">
              {(active.repos ?? []).map((rule, i) => (
                <li key={i} className="font-mono text-xs">
                  {rule.pattern}
                  {rule.write ? ` · write=${rule.write}` : ""}
                  {rule.read ? ` · read=${rule.read}` : ""}
                  {rule.approval ? ` · approval=${rule.approval}` : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {canEdit && (
        <section className="rounded-lg border border-border p-4">
          <h3 className="font-medium">Novo draft</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <Input
              value={draftLabel}
              onChange={(e) => setDraftLabel(e.target.value)}
              placeholder="Label do draft"
            />
            {!active && (
              <>
                <Input
                  value={repoPattern}
                  onChange={(e) => setRepoPattern(e.target.value)}
                  placeholder="Pattern"
                />
                <Input
                  value={repoWrite}
                  onChange={(e) => setRepoWrite(e.target.value)}
                  placeholder="write mode"
                />
              </>
            )}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={draftMut.isPending}
              onClick={() => draftMut.mutate()}
            >
              Criar draft
            </Button>
            {lastDraftId && (
              <Button
                size="sm"
                variant="default"
                disabled={publishMut.isPending}
                onClick={() => publishMut.mutate(lastDraftId)}
              >
                Publicar draft {lastDraftId.slice(0, 8)}…
              </Button>
            )}
          </div>
        </section>
      )}

      <section className="rounded-lg border border-border p-4">
        <h3 className="font-medium">Histórico</h3>
        <table className="mt-3 w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-2 pr-4">Versão</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">Label</th>
              <th className="py-2">Criado</th>
            </tr>
          </thead>
          <tbody>
            {history.length === 0 ? (
              <tr>
                <td colSpan={4} className="py-3 text-muted-foreground">
                  Sem histórico em PG.
                </td>
              </tr>
            ) : (
              history.map((item) => (
                <tr key={item.bundle_id} className="border-b border-border/60">
                  <td className="py-2 pr-4">{item.version}</td>
                  <td className="py-2 pr-4">{item.status}</td>
                  <td className="py-2 pr-4">{item.label || "—"}</td>
                  <td className="py-2 text-muted-foreground">
                    {item.created_at}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      {canRollback && (
        <section className="rounded-lg border border-border p-4">
          <h3 className="font-medium">Rollback</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Reativa uma versão publicada anterior (só admin).
          </p>
          <div className="mt-3 flex gap-2">
            <Input
              type="number"
              min={1}
              value={rollbackVersion}
              onChange={(e) => setRollbackVersion(e.target.value)}
              placeholder="Versão"
              className="max-w-[120px]"
            />
            <Button
              size="sm"
              variant="outline"
              disabled={!rollbackVersion}
              onClick={() => setConfirmRollback(true)}
            >
              Rollback
            </Button>
          </div>
        </section>
      )}

      <AlertDialog open={confirmRollback} onOpenChange={setConfirmRollback}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Confirmar rollback</AlertDialogTitle>
            <AlertDialogDescription>
              A versão {rollbackVersion} passará a ser a policy activa do
              tenant. Esta acção é auditada.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                rollbackMut.mutate(parseInt(rollbackVersion, 10))
              }
            >
              Confirmar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
