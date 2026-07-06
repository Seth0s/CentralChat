import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  fetchDeployStatus,
  fetchSiemOutbox,
  processSiemOutbox,
} from "@/lib/api/ops";

export const Route = createFileRoute("/dashboard/settings/ops")({
  component: OpsSettingsPage,
});

function OpsSettingsPage() {
  const qc = useQueryClient();
  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const isAdmin = roleData?.role === "admin";

  const statusQuery = useQuery({
    queryKey: ["deploy-status"],
    queryFn: () => fetchDeployStatus(),
  });
  const siemQuery = useQuery({
    queryKey: ["siem-outbox"],
    queryFn: () => fetchSiemOutbox(),
    refetchInterval: 30_000,
  });

  const processMut = useMutation({
    mutationFn: () => processSiemOutbox(),
    onSuccess: (result) => {
      const c = result.counts;
      toast.success(
        `Processado: ${c.delivered ?? 0} entregues, ${c.retried ?? 0} retentativas.`,
      );
      qc.invalidateQueries({ queryKey: ["siem-outbox"] });
      qc.invalidateQueries({ queryKey: ["deploy-status"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const status = statusQuery.data;
  const siem = siemQuery.data?.summary;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Operação</h2>
        <p className="text-sm text-muted-foreground">
          Health, feature flags, migrations, residency e monitor SIEM outbox.
        </p>
      </div>

      {statusQuery.isLoading && (
        <p className="text-sm text-muted-foreground">A carregar status…</p>
      )}

      {status && (
        <>
          <section className="rounded-lg border border-border p-4 text-sm">
            <h3 className="font-medium">Health</h3>
            <dl className="mt-2 grid gap-2 sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground">Ambiente</dt>
                <dd className="font-mono">{status.environment}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Postgres</dt>
                <dd className="font-mono">{status.health.postgres}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Memory DB</dt>
                <dd>{status.health.memory_db_enabled ? "activo" : "off"}</dd>
              </div>
            </dl>
          </section>

          <section className="rounded-lg border border-border p-4 text-sm">
            <h3 className="font-medium">Feature flags efectivas</h3>
            <ul className="mt-2 space-y-1 font-mono text-xs">
              {Object.entries(status.feature_flags).map(([k, v]) => (
                <li key={k}>
                  {k}: {String(v)}
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-lg border border-border p-4 text-sm">
            <h3 className="font-medium">Migrations</h3>
            <p className="mt-1">
              {status.migrations.applied_count}/{status.migrations.total_files}{" "}
              aplicadas
              {status.migrations.pending_count > 0 && (
                <span className="text-amber-600">
                  {" "}
                  · {status.migrations.pending_count} pendentes
                </span>
              )}
            </p>
            {status.migrations.pending.length > 0 && (
              <ul className="mt-2 font-mono text-xs text-muted-foreground">
                {status.migrations.pending.map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            )}
          </section>

          <section className="rounded-lg border border-border p-4 text-sm">
            <h3 className="font-medium">Backup</h3>
            <p className="mt-1 text-muted-foreground">
              {String(status.backup.note_pt ?? status.backup.status)}
            </p>
          </section>
        </>
      )}

      <section className="rounded-lg border border-border p-4 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-medium">SIEM outbox</h3>
          {isAdmin && (
            <Button
              size="sm"
              variant="outline"
              disabled={processMut.isPending}
              onClick={() => processMut.mutate()}
            >
              Processar fila
            </Button>
          )}
        </div>
        {!siem ? (
          <p className="mt-2 text-muted-foreground">A carregar…</p>
        ) : (
          <dl className="mt-3 grid gap-2 sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Estado</dt>
              <dd className="font-medium">{siem.status}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Pendentes</dt>
              <dd>{siem.pending}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Dead-letter</dt>
              <dd className={siem.dead > 0 ? "text-destructive" : ""}>
                {siem.dead}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Entregues</dt>
              <dd>{siem.delivered}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Webhooks</dt>
              <dd>{siem.webhooks_configured}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">HEC token</dt>
              <dd>{siem.hec_token_configured ? "sim" : "não"}</dd>
            </div>
          </dl>
        )}
        {siem?.last_error && (
          <p className="mt-3 text-xs text-destructive">
            Último erro: {siem.last_error}
          </p>
        )}
        {siem?.oldest_pending_at && (
          <p className="mt-1 text-xs text-muted-foreground">
            Pendente mais antigo: {siem.oldest_pending_at}
          </p>
        )}
      </section>
    </div>
  );
}
