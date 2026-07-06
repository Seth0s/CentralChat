import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchSessionRole } from "@/lib/auth/role";
import { fetchAdminUsers } from "@/lib/api/users";
import {
  addWorkItemComment,
  fetchWorkItem,
  fetchWorkItemComments,
  fetchWorkItemEvents,
  patchWorkItem,
} from "@/lib/api/work-items";

export const Route = createFileRoute("/dashboard/queue/$itemId")({
  component: WorkItemDetailPage,
});

const PRIORITIES = ["low", "normal", "high", "urgent"] as const;
const STATUSES = ["open", "in_progress", "review", "done", "cancelled"] as const;

function WorkItemDetailPage() {
  const { itemId } = Route.useParams();
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const [assigneeId, setAssigneeId] = useState("");

  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const readOnly =
    roleData?.role === "viewer" || roleData?.role === "auditor";
  const canAssign = roleData?.role === "lead" || roleData?.role === "admin";

  const itemQuery = useQuery({
    queryKey: ["work-item", itemId],
    queryFn: () => fetchWorkItem({ data: { id: itemId } }),
  });
  const eventsQuery = useQuery({
    queryKey: ["work-item-events", itemId],
    queryFn: () => fetchWorkItemEvents({ data: { id: itemId } }),
  });
  const commentsQuery = useQuery({
    queryKey: ["work-item-comments", itemId],
    queryFn: () => fetchWorkItemComments({ data: { id: itemId } }),
  });
  const usersQuery = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => fetchAdminUsers({ data: { limit: 200 } }),
    enabled: canAssign,
  });

  const item = itemQuery.data?.item;

  const patchMut = useMutation({
    mutationFn: (patch: {
      status?: string;
      priority?: string;
      assigneeId?: string | null;
    }) =>
      patchWorkItem({
        data: { id: itemId, ...patch },
      }),
    onSuccess: () => {
      toast.success("Item atualizado.");
      qc.invalidateQueries({ queryKey: ["work-item", itemId] });
      qc.invalidateQueries({ queryKey: ["work-item-events", itemId] });
      qc.invalidateQueries({ queryKey: ["work-items"] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const commentMut = useMutation({
    mutationFn: (body: string) =>
      addWorkItemComment({ data: { id: itemId, body } }),
    onSuccess: () => {
      setComment("");
      qc.invalidateQueries({ queryKey: ["work-item-comments", itemId] });
      qc.invalidateQueries({ queryKey: ["work-item-events", itemId] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  if (itemQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">A carregar item…</p>;
  }
  if (itemQuery.error || !item) {
    return (
      <p className="text-sm text-destructive">
        {(itemQuery.error as Error)?.message || "Item não encontrado."}
      </p>
    );
  }

  const users = usersQuery.data?.items ?? [];
  const userLabel = (id: string) =>
    users.find((u) => u.id === id)?.display_name ||
    users.find((u) => u.id === id)?.email ||
    id.slice(0, 8);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to="/dashboard/queue"
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← Fila de trabalho
          </Link>
          <h2 className="mt-1 text-xl font-semibold">{item.title}</h2>
          <p className="font-mono text-xs text-muted-foreground">{item.id}</p>
        </div>
        {!readOnly && (
          <div className="flex flex-wrap gap-2">
            {STATUSES.map((st) => (
              <Button
                key={st}
                size="sm"
                variant={item.status === st ? "default" : "outline"}
                disabled={patchMut.isPending || item.status === st}
                onClick={() => patchMut.mutate({ status: st })}
              >
                {st}
              </Button>
            ))}
          </div>
        )}
      </div>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-border p-4">
          <h3 className="font-medium">Detalhes</h3>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Status</dt>
              <dd>{item.status}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Prioridade</dt>
              <dd>
                {readOnly || !canAssign ? (
                  item.priority
                ) : (
                  <select
                    className="rounded border border-border bg-background px-2 py-1 text-sm"
                    value={item.priority}
                    disabled={patchMut.isPending}
                    onChange={(e) =>
                      patchMut.mutate({ priority: e.target.value })
                    }
                  >
                    {PRIORITIES.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                )}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">Responsável</dt>
              <dd>
                {item.assignee_id ? userLabel(item.assignee_id) : "—"}
              </dd>
            </div>
            {item.session_id && (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">Sessão</dt>
                <dd>
                  <Link
                    to="/dashboard/sessions/$sessionId"
                    params={{ sessionId: item.session_id }}
                    className="text-primary hover:underline"
                  >
                    {item.session_id.slice(0, 12)}…
                  </Link>
                </dd>
              </div>
            )}
          </dl>

          {canAssign && !readOnly && (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-medium text-muted-foreground">
                Atribuir responsável
              </p>
              <div className="flex gap-2">
                <select
                  className="min-w-0 flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
                  value={assigneeId || item.assignee_id || ""}
                  onChange={(e) => setAssigneeId(e.target.value)}
                >
                  <option value="">— nenhum —</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.display_name || u.email}
                    </option>
                  ))}
                </select>
                <Button
                  size="sm"
                  disabled={patchMut.isPending}
                  onClick={() =>
                    patchMut.mutate({
                      assigneeId: assigneeId || item.assignee_id || null,
                    })
                  }
                >
                  Guardar
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border p-4">
          <h3 className="font-medium">Timeline</h3>
          <ul className="mt-3 max-h-72 space-y-2 overflow-auto text-sm">
            {(eventsQuery.data?.items ?? []).length === 0 ? (
              <li className="text-muted-foreground">Sem eventos.</li>
            ) : (
              (eventsQuery.data?.items ?? []).map((ev) => (
                <li key={ev.event_id} className="border-b border-border/50 pb-2">
                  <p className="font-medium">{ev.event_type}</p>
                  <p className="text-xs text-muted-foreground">
                    {ev.created_at}
                    {ev.from_status && ev.to_status
                      ? ` · ${ev.from_status} → ${ev.to_status}`
                      : ""}
                  </p>
                </li>
              ))
            )}
          </ul>
        </div>
      </section>

      <section className="rounded-lg border border-border p-4">
        <h3 className="font-medium">Comentários</h3>
        <ul className="mt-3 space-y-3">
          {(commentsQuery.data?.items ?? []).length === 0 ? (
            <li className="text-sm text-muted-foreground">Sem comentários.</li>
          ) : (
            (commentsQuery.data?.items ?? []).map((c) => (
              <li key={c.id} className="rounded-md bg-secondary/40 p-3 text-sm">
                <p className="text-xs text-muted-foreground">
                  {c.author_id.slice(0, 8)} · {c.created_at}
                </p>
                <p className="mt-1 whitespace-pre-wrap">{c.body}</p>
              </li>
            ))
          )}
        </ul>
        {!readOnly && (
          <div className="mt-4 flex gap-2">
            <Input
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Adicionar comentário…"
              className="flex-1"
            />
            <Button
              disabled={!comment.trim() || commentMut.isPending}
              onClick={() => commentMut.mutate(comment.trim())}
            >
              Enviar
            </Button>
          </div>
        )}
      </section>
    </div>
  );
}
