import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  approveTeamRule,
  createTeamRule,
  fetchTeamRules,
  patchTeamRule,
  rejectTeamRule,
} from "@/lib/api/team-rules";

export const Route = createFileRoute("/dashboard/rules")({
  component: RulesPage,
});

function RulesPage() {
  const qc = useQueryClient();
  const [newPattern, setNewPattern] = useState("");
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [editId, setEditId] = useState<string | null>(null);
  const [editPattern, setEditPattern] = useState("");

  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const canPropose =
    roleData?.role === "developer" ||
    roleData?.role === "lead" ||
    roleData?.role === "admin";
  const canReview = roleData?.role === "lead" || roleData?.role === "admin";

  const pendingQuery = useQuery({
    queryKey: ["team-rules", "pending"],
    queryFn: () => fetchTeamRules({ data: { status: "pending" } }),
  });
  const approvedQuery = useQuery({
    queryKey: ["team-rules", "approved"],
    queryFn: () => fetchTeamRules({ data: { status: "approved" } }),
  });
  const rejectedQuery = useQuery({
    queryKey: ["team-rules", "rejected"],
    queryFn: () => fetchTeamRules({ data: { status: "rejected" } }),
  });

  const invalidate = () => qc.invalidateQueries({ queryKey: ["team-rules"] });

  const createMut = useMutation({
    mutationFn: (pattern: string) => createTeamRule({ data: { pattern } }),
    onSuccess: () => {
      setNewPattern("");
      toast.success("Regra proposta.");
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const approveMut = useMutation({
    mutationFn: (id: string) => approveTeamRule({ data: { id } }),
    onSuccess: () => {
      toast.success("Regra aprovada.");
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const rejectMut = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) =>
      rejectTeamRule({ data: { id, reason } }),
    onSuccess: () => {
      setRejectId(null);
      setRejectReason("");
      toast.success("Regra rejeitada.");
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const patchMut = useMutation({
    mutationFn: ({ id, pattern }: { id: string; pattern: string }) =>
      patchTeamRule({ data: { id, pattern } }),
    onSuccess: () => {
      setEditId(null);
      toast.success("Regra actualizada.");
      invalidate();
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const pending = pendingQuery.data?.items ?? [];
  const approved = approvedQuery.data?.items ?? [];
  const rejected = rejectedQuery.data?.items ?? [];
  const counts = pendingQuery.data?.counts;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Regras da equipa</h2>
        <p className="text-sm text-muted-foreground">
          Só regras aprovadas entram no prompt (L4). Rejeição exige motivo e
          gera audit.
        </p>
      </div>

      {canPropose && (
        <section className="flex gap-2">
          <Input
            value={newPattern}
            onChange={(e) => setNewPattern(e.target.value)}
            placeholder="Nova regra (texto livre)"
            className="flex-1"
          />
          <Button
            disabled={!newPattern.trim() || createMut.isPending}
            onClick={() => createMut.mutate(newPattern.trim())}
          >
            Propor
          </Button>
        </section>
      )}

      <section className="space-y-3">
        <h3 className="text-sm font-medium">
          Pendentes ({counts?.pending ?? pending.length})
        </h3>
        {pending.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhuma pendente.</p>
        ) : (
          <ul className="space-y-3">
            {pending.map((rule) => (
              <li key={rule.id} className="rounded-lg border border-border p-4">
                {editId === rule.id ? (
                  <div className="flex gap-2">
                    <Input
                      value={editPattern}
                      onChange={(e) => setEditPattern(e.target.value)}
                      className="flex-1"
                    />
                    <Button
                      size="sm"
                      onClick={() =>
                        patchMut.mutate({ id: rule.id, pattern: editPattern })
                      }
                    >
                      Guardar
                    </Button>
                  </div>
                ) : (
                  <>
                    <p className="text-sm">{rule.pattern}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {rule.source} · {rule.id}
                    </p>
                    {canReview && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          onClick={() => approveMut.mutate(rule.id)}
                        >
                          Aprovar
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setEditId(rule.id);
                            setEditPattern(rule.pattern);
                          }}
                        >
                          Editar
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => setRejectId(rule.id)}
                        >
                          Rejeitar
                        </Button>
                      </div>
                    )}
                  </>
                )}
                {rejectId === rule.id && (
                  <div className="mt-3 space-y-2 border-t border-border pt-3">
                    <Input
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder="Motivo da rejeição"
                    />
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant="destructive"
                        disabled={!rejectReason.trim()}
                        onClick={() =>
                          rejectMut.mutate({
                            id: rule.id,
                            reason: rejectReason.trim(),
                          })
                        }
                      >
                        Confirmar rejeição
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setRejectId(null);
                          setRejectReason("");
                        }}
                      >
                        Cancelar
                      </Button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-medium">
          Aprovadas ({counts?.approved ?? approved.length})
        </h3>
        <ul className="space-y-2">
          {approved.map((rule) => (
            <li
              key={rule.id}
              className="rounded-md border border-border px-3 py-2 text-sm"
            >
              {rule.pattern}
              <span className="ml-2 text-xs text-muted-foreground">
                ({rule.source})
              </span>
            </li>
          ))}
        </ul>
      </section>

      {(counts?.rejected ?? rejected.length) > 0 && (
        <section className="space-y-3">
          <h3 className="text-sm font-medium">
            Rejeitadas ({counts?.rejected ?? rejected.length})
          </h3>
          <ul className="space-y-2">
            {rejected.map((rule) => (
              <li
                key={rule.id}
                className="rounded-md border border-border px-3 py-2 text-sm text-muted-foreground"
              >
                {rule.pattern}
                {typeof rule.rejection_context?.review_rejection_reason ===
                  "string" && (
                  <p className="mt-1 text-xs">
                    Motivo: {String(rule.rejection_context.review_rejection_reason)}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
