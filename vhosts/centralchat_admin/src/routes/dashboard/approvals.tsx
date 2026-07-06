import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchApprovals, approveApproval, denyApproval } from "@/lib/api/approvals";
import { Button } from "@/components/ui/button";

export const Route = createFileRoute("/dashboard/approvals")({
  component: ApprovalsPage,
});

function ApprovalsPage() {
  const qc = useQueryClient();
  const { data: items = [], isLoading, error } = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => fetchApprovals(),
  });

  const approveMut = useMutation({
    mutationFn: (id: string) => approveApproval({ data: { id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });

  const denyMut = useMutation({
    mutationFn: (id: string) => denyApproval({ data: { id } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["approvals"] }),
  });

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">Approvals pendentes</h2>
        <p className="text-sm text-muted-foreground">
          Para o dia-a-dia use <code className="rounded bg-secondary px-1">central diff</code> e{" "}
          <code className="rounded bg-secondary px-1">central approve</code>. Esta página serve diffs grandes.
        </p>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">A carregar…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}

      {items.length === 0 && !isLoading ? (
        <p className="text-sm text-muted-foreground">Nenhuma approval pendente.</p>
      ) : (
        <ul className="space-y-3">
          {items.map((item) => {
            const id = String(item.approval_id || item.id || "");
            return (
              <li key={id} className="rounded-lg border border-border p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-mono text-sm">{id}</p>
                    <p className="text-sm text-muted-foreground">
                      {item.action_id} · {item.risk_level || item.status}
                    </p>
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" variant="outline" asChild>
                      <a href={`/api/orchestrator/approvals/${id}/diff`} target="_blank" rel="noreferrer">
                        Ver diff
                      </a>
                    </Button>
                    <Button size="sm" onClick={() => approveMut.mutate(id)} disabled={approveMut.isPending}>
                      Aprovar
                    </Button>
                    <Button size="sm" variant="destructive" onClick={() => denyMut.mutate(id)} disabled={denyMut.isPending}>
                      Rejeitar
                    </Button>
                  </div>
                </div>
                {item.payload && typeof item.payload === "object" && (
                  <pre className="mt-3 max-h-48 overflow-auto rounded bg-secondary p-2 text-xs">
                    {JSON.stringify(item.payload, null, 2)}
                  </pre>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
