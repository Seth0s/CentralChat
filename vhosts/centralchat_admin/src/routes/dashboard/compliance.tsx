import { createFileRoute, Link } from "@tanstack/react-router";
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
  applyCompliancePack,
  fetchActiveBreakGlass,
  fetchCompliancePacks,
  fetchCompliancePreview,
  fetchDeployResidency,
  grantBreakGlass,
  revokeBreakGlass,
} from "@/lib/api/compliance";

export const Route = createFileRoute("/dashboard/compliance")({
  component: CompliancePage,
});

function CompliancePage() {
  const qc = useQueryClient();
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [confirmPackId, setConfirmPackId] = useState<string | null>(null);
  const [grantForm, setGrantForm] = useState({
    pathPattern: "**/payment/**",
    reason: "",
    userId: "",
    ttlHours: "1",
  });

  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const isAdmin = roleData?.role === "admin";

  const packs = useQuery({
    queryKey: ["compliance-packs"],
    queryFn: () => fetchCompliancePacks(),
  });
  const preview = useQuery({
    queryKey: ["compliance-preview", previewId],
    queryFn: () => fetchCompliancePreview({ data: { packId: previewId! } }),
    enabled: Boolean(previewId),
  });
  const residency = useQuery({
    queryKey: ["deploy-residency"],
    queryFn: () => fetchDeployResidency(),
  });
  const breakGlass = useQuery({
    queryKey: ["break-glass"],
    queryFn: () => fetchActiveBreakGlass(),
  });

  const applyMut = useMutation({
    mutationFn: (packId: string) => applyCompliancePack({ data: { packId } }),
    onSuccess: () => {
      toast.success("Pack aplicado com sucesso.");
      setConfirmPackId(null);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const grantMut = useMutation({
    mutationFn: () =>
      grantBreakGlass({
        data: {
          pathPattern: grantForm.pathPattern,
          reason: grantForm.reason,
          userId: grantForm.userId || undefined,
          ttlHours: parseFloat(grantForm.ttlHours) || 1,
        },
      }),
    onSuccess: () => {
      toast.success("Break-glass concedido.");
      setGrantForm((f) => ({ ...f, reason: "" }));
      qc.invalidateQueries({ queryKey: ["break-glass"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const revokeMut = useMutation({
    mutationFn: (grantId: string) => revokeBreakGlass({ data: { grantId } }),
    onSuccess: () => {
      toast.success("Grant revogado.");
      qc.invalidateQueries({ queryKey: ["break-glass"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const items = packs.data?.items ?? [];
  const confirmPack = items.find((p) => p.id === confirmPackId);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Compliance</h2>
          <p className="text-sm text-muted-foreground">
            Templates audit-ready, break-glass auditado e preview antes de aplicar
            packs.
          </p>
        </div>
        <Link
          to="/dashboard/settings/ops"
          className="text-sm text-primary hover:underline"
        >
          Operação / SIEM →
        </Link>
      </div>

      {residency.data && (
        <div className="rounded-lg border border-border p-4 text-sm">
          <h3 className="mb-2 font-medium">Data residency / air-gap</h3>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Residency</dt>
              <dd className="font-mono">{residency.data.data_residency}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">LLM region</dt>
              <dd className="font-mono">{residency.data.llm_endpoint_region}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Telemetry off</dt>
              <dd>{residency.data.telemetry_disabled ? "sim" : "não"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Air-gap</dt>
              <dd>{residency.data.air_gap_mode ? "sim" : "não"}</dd>
            </div>
          </dl>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        {items.map((pack) => (
          <div key={pack.id} className="rounded-lg border border-border p-4">
            <h3 className="font-medium">{pack.name}</h3>
            <p className="text-xs text-muted-foreground">{pack.framework}</p>
            <p className="mt-2 text-sm text-muted-foreground">
              {pack.description_pt}
            </p>
            <Button
              size="sm"
              variant="outline"
              className="mt-4 mr-2"
              onClick={() => setPreviewId(pack.id)}
            >
              Preview
            </Button>
            {isAdmin && (
              <Button
                size="sm"
                className="mt-4"
                onClick={() => setConfirmPackId(pack.id)}
              >
                Aplicar
              </Button>
            )}
          </div>
        ))}
      </div>

      {preview.data && (
        <div className="rounded-lg border border-border p-4 text-sm">
          <h3 className="mb-2 font-medium">
            Preview: {String(preview.data.pack_name ?? "")}
          </h3>
          <p className="mb-2 text-muted-foreground">
            {String(preview.data.audit_ready_notice ?? "")}
          </p>
          <p className="text-xs text-muted-foreground">
            {String(preview.data.rollback_hint ?? "")}
          </p>
        </div>
      )}

      <section className="space-y-4">
        <h3 className="font-medium">Break-glass</h3>
        {isAdmin && (
          <div className="rounded-lg border border-border p-4">
            <p className="mb-3 text-sm text-muted-foreground">
              Conceda override temporário com motivo obrigatório (auditado).
            </p>
            <div className="grid gap-2 md:grid-cols-2">
              <Input
                placeholder="Path pattern"
                value={grantForm.pathPattern}
                onChange={(e) =>
                  setGrantForm((f) => ({ ...f, pathPattern: e.target.value }))
                }
              />
              <Input
                placeholder="User ID (opcional)"
                value={grantForm.userId}
                onChange={(e) =>
                  setGrantForm((f) => ({ ...f, userId: e.target.value }))
                }
              />
              <Input
                placeholder="Motivo"
                className="md:col-span-2"
                value={grantForm.reason}
                onChange={(e) =>
                  setGrantForm((f) => ({ ...f, reason: e.target.value }))
                }
              />
            </div>
            <Button
              className="mt-3"
              size="sm"
              disabled={!grantForm.reason.trim() || grantMut.isPending}
              onClick={() => grantMut.mutate()}
            >
              Conceder break-glass
            </Button>
          </div>
        )}

        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border bg-secondary/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2">Pattern</th>
                <th className="px-3 py-2">Utilizador</th>
                <th className="px-3 py-2">Expira</th>
                <th className="px-3 py-2">Motivo</th>
                {isAdmin && <th className="px-3 py-2">Acções</th>}
              </tr>
            </thead>
            <tbody>
              {(breakGlass.data?.items ?? []).length === 0 ? (
                <tr>
                  <td
                    colSpan={isAdmin ? 5 : 4}
                    className="px-3 py-4 text-muted-foreground"
                  >
                    Nenhum grant activo.
                  </td>
                </tr>
              ) : (
                breakGlass.data?.items.map((g) => (
                  <tr key={String(g.id)} className="border-b border-border/60">
                    <td className="px-3 py-2 font-mono text-xs">
                      {String(g.path_pattern ?? "")}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">
                      {String(g.user_id ?? "").slice(0, 12)}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {String(g.expires_at ?? "").slice(0, 19)}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground">
                      {String(g.reason ?? "")}
                    </td>
                    {isAdmin && (
                      <td className="px-3 py-2">
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={revokeMut.isPending}
                          onClick={() => revokeMut.mutate(String(g.id))}
                        >
                          Revogar
                        </Button>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <AlertDialog
        open={Boolean(confirmPackId)}
        onOpenChange={(open) => !open && setConfirmPackId(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Aplicar pack de compliance?</AlertDialogTitle>
            <AlertDialogDescription>
              O pack <strong>{confirmPack?.name}</strong> alterará políticas do
              tenant. A acção é auditada e deve ser precedida de preview.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                confirmPackId && applyMut.mutate(confirmPackId)
              }
            >
              Aplicar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
