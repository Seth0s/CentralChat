import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchWorkItems, patchWorkItem } from "@/lib/api/work-items";
import { fetchSessionRole } from "@/lib/auth/role";
import { Button } from "@/components/ui/button";

const COLUMNS = [
  { key: "open", label: "Aberto" },
  { key: "in_progress", label: "Em andamento" },
  { key: "review", label: "Em revisão" },
  { key: "done", label: "Concluído" },
] as const;

export const Route = createFileRoute("/dashboard/queue")({
  component: QueuePage,
});

function QueuePage() {
  const qc = useQueryClient();
  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const readOnly = roleData?.role === "viewer" || roleData?.role === "auditor";
  const { data, isLoading, error } = useQuery({
    queryKey: ["work-items"],
    queryFn: () => fetchWorkItems({ data: {} }),
  });

  const moveMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      patchWorkItem({ data: { id, status } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["work-items"] }),
  });

  const items = data?.items ?? [];
  const byStatus = (st: string) => items.filter((i) => i.status === st);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Fila de trabalho</h2>
        <p className="text-sm text-muted-foreground">
          Kanban simples — cada item liga sessão, diff e audit. CLI:{" "}
          <code className="rounded bg-secondary px-1">central queue list</code>
          {readOnly && (
            <span className="ml-2 text-amber-600">
              (somente leitura — papel viewer/auditor)
            </span>
          )}
        </p>
      </div>

      {isLoading && (
        <p className="text-sm text-muted-foreground">A carregar…</p>
      )}
      {error && (
        <p className="text-sm text-destructive">{(error as Error).message}</p>
      )}
      {data && !data.work_items_enabled && (
        <p className="text-sm text-muted-foreground">
          Fila de trabalho desativada (sem Postgres).
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {COLUMNS.map((col) => (
          <section
            key={col.key}
            className="rounded-lg border border-border bg-card p-3"
          >
            <h3 className="mb-3 text-sm font-medium text-muted-foreground">
              {col.label}
            </h3>
            <ul className="space-y-2">
              {byStatus(col.key).length === 0 ? (
                <li className="text-xs text-muted-foreground">—</li>
              ) : (
                byStatus(col.key).map((wi) => (
                  <li
                    key={wi.id}
                    className="rounded-md border border-border p-3 text-sm"
                  >
                    <Link
                      to="/dashboard/queue/$itemId"
                      params={{ itemId: wi.id }}
                      className="block hover:opacity-90"
                    >
                      <p className="font-medium">{wi.title}</p>
                      <p className="mt-1 font-mono text-xs text-muted-foreground">
                        {wi.id}
                      </p>
                    </Link>
                    {wi.session_id && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        sessão: {wi.session_id.slice(0, 12)}…
                      </p>
                    )}
                    {!readOnly && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {COLUMNS.filter((c) => c.key !== wi.status).map((c) => (
                          <Button
                            key={c.key}
                            variant="outline"
                            size="sm"
                            className="h-7 text-xs"
                            disabled={moveMut.isPending}
                            onClick={() =>
                              moveMut.mutate({ id: wi.id, status: c.key })
                            }
                          >
                            → {c.label}
                          </Button>
                        ))}
                      </div>
                    )}
                  </li>
                ))
              )}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
