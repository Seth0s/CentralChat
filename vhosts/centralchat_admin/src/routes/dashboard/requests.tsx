import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  addTeamRequestComment,
  createTeamRequest,
  fetchTeamRequest,
  fetchTeamRequestComments,
  fetchTeamRequests,
  resolveTeamRequest,
} from "@/lib/api/requests";

export const Route = createFileRoute("/dashboard/requests")({
  component: RequestsPage,
  validateSearch: (search: Record<string, unknown>) => ({
    id: typeof search.id === "string" ? search.id : undefined,
  }),
});

const REQUEST_TYPES = [
  "lead_decision",
  "admin_exception",
  "compliance_question",
  "policy_exception",
  "shared_resource_change",
  "central_repo_change",
] as const;

function RequestsPage() {
  const { id: selectedId } = Route.useSearch();
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState({
    requestType: "lead_decision" as (typeof REQUEST_TYPES)[number],
    title: "",
    body: "",
    projectId: "",
    sessionId: "",
    workItemId: "",
  });
  const [comment, setComment] = useState("");
  const [resolution, setResolution] = useState("");

  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const canCreate =
    roleData?.role === "developer" ||
    roleData?.role === "lead" ||
    roleData?.role === "admin";
  const canResolve =
    roleData?.role === "lead" ||
    roleData?.role === "admin" ||
    roleData?.role === "auditor";

  const listQuery = useQuery({
    queryKey: ["team-requests"],
    queryFn: () => fetchTeamRequests({ data: {} }),
  });
  const detailQuery = useQuery({
    queryKey: ["team-request", selectedId],
    queryFn: () => fetchTeamRequest({ data: { id: selectedId! } }),
    enabled: Boolean(selectedId),
  });
  const commentsQuery = useQuery({
    queryKey: ["team-request-comments", selectedId],
    queryFn: () => fetchTeamRequestComments({ data: { id: selectedId! } }),
    enabled: Boolean(selectedId),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createTeamRequest({
        data: {
          requestType: createForm.requestType,
          title: createForm.title,
          body: createForm.body || undefined,
          projectId: createForm.projectId || undefined,
          sessionId: createForm.sessionId || undefined,
          workItemId: createForm.workItemId || undefined,
        },
      }),
    onSuccess: () => {
      toast.success("Solicitação criada.");
      setShowCreate(false);
      setCreateForm({
        requestType: "lead_decision",
        title: "",
        body: "",
        projectId: "",
        sessionId: "",
        workItemId: "",
      });
      qc.invalidateQueries({ queryKey: ["team-requests"] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const commentMut = useMutation({
    mutationFn: (body: string) =>
      addTeamRequestComment({ data: { id: selectedId!, body } }),
    onSuccess: () => {
      setComment("");
      qc.invalidateQueries({
        queryKey: ["team-request-comments", selectedId],
      });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const resolveMut = useMutation({
    mutationFn: () =>
      resolveTeamRequest({
        data: { id: selectedId!, resolution: resolution.trim() },
      }),
    onSuccess: () => {
      toast.success("Solicitação resolvida.");
      setResolution("");
      qc.invalidateQueries({ queryKey: ["team-requests"] });
      qc.invalidateQueries({ queryKey: ["team-request", selectedId] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const items = listQuery.data?.items ?? [];
  const selected = detailQuery.data?.request;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Solicitações contextuais</h2>
          <p className="text-sm text-muted-foreground">
            Comunicação com lead/admin sem bloquear o repo local. Substitui o
            approval universal para decisões de equipa.
          </p>
        </div>
        {canCreate && (
          <Button size="sm" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Cancelar" : "Nova solicitação"}
          </Button>
        )}
      </div>

      {showCreate && canCreate && (
        <section className="rounded-lg border border-border bg-card p-4">
          <h3 className="font-medium">Criar solicitação</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="text-sm">
              <span className="text-muted-foreground">Tipo</span>
              <select
                className="mt-1 w-full rounded border border-border bg-background px-2 py-2 text-sm"
                value={createForm.requestType}
                onChange={(e) =>
                  setCreateForm((f) => ({
                    ...f,
                    requestType: e.target.value as (typeof REQUEST_TYPES)[number],
                  }))
                }
              >
                {REQUEST_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm md:col-span-2">
              <span className="text-muted-foreground">Título</span>
              <Input
                className="mt-1"
                value={createForm.title}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, title: e.target.value }))
                }
              />
            </label>
            <label className="text-sm md:col-span-2">
              <span className="text-muted-foreground">Descrição</span>
              <textarea
                className="mt-1 w-full rounded border border-border bg-background px-3 py-2 text-sm"
                rows={3}
                value={createForm.body}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, body: e.target.value }))
                }
              />
            </label>
            <label className="text-sm">
              <span className="text-muted-foreground">Project ID (opcional)</span>
              <Input
                className="mt-1 font-mono text-xs"
                value={createForm.projectId}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, projectId: e.target.value }))
                }
              />
            </label>
            <label className="text-sm">
              <span className="text-muted-foreground">Sessão (opcional)</span>
              <Input
                className="mt-1 font-mono text-xs"
                value={createForm.sessionId}
                onChange={(e) =>
                  setCreateForm((f) => ({ ...f, sessionId: e.target.value }))
                }
              />
            </label>
          </div>
          <Button
            className="mt-4"
            size="sm"
            disabled={!createForm.title.trim() || createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            Enviar ao lead
          </Button>
        </section>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-lg border border-border p-4">
          <h3 className="font-medium">Abertas e recentes</h3>
          {listQuery.isLoading && (
            <p className="mt-2 text-sm text-muted-foreground">A carregar…</p>
          )}
          <ul className="mt-3 space-y-2">
            {items.length === 0 && !listQuery.isLoading ? (
              <li className="text-sm text-muted-foreground">Sem solicitações.</li>
            ) : (
              items.map((item) => (
                <li key={item.id}>
                  <Link
                    to="/dashboard/requests"
                    search={{ id: item.id }}
                    className={`block rounded-md border p-3 text-sm hover:bg-secondary/50 ${
                      selectedId === item.id
                        ? "border-primary bg-secondary/40"
                        : "border-border"
                    }`}
                  >
                    <p className="font-medium">{item.title}</p>
                    <p className="text-xs text-muted-foreground">
                      {item.request_type} · {item.status}
                    </p>
                  </Link>
                </li>
              ))
            )}
          </ul>
        </section>

        <section className="rounded-lg border border-border p-4">
          {!selectedId ? (
            <p className="text-sm text-muted-foreground">
              Seleccione uma solicitação para ver detalhe.
            </p>
          ) : detailQuery.isLoading ? (
            <p className="text-sm text-muted-foreground">A carregar detalhe…</p>
          ) : selected ? (
            <div className="space-y-4">
              <div>
                <h3 className="font-medium">{selected.title}</h3>
                <p className="text-xs text-muted-foreground">
                  {selected.request_type} · {selected.status}
                </p>
                {selected.body && (
                  <p className="mt-2 whitespace-pre-wrap text-sm">
                    {selected.body}
                  </p>
                )}
                {selected.work_item_id && (
                  <p className="mt-2 text-sm">
                    Work item:{" "}
                    <Link
                      to="/dashboard/queue/$itemId"
                      params={{ itemId: selected.work_item_id }}
                      className="text-primary hover:underline"
                    >
                      {selected.work_item_id}
                    </Link>
                  </p>
                )}
                {selected.resolution && (
                  <p className="mt-2 rounded-md bg-secondary/50 p-2 text-sm">
                    <span className="font-medium">Resolução:</span>{" "}
                    {selected.resolution}
                  </p>
                )}
              </div>

              <div>
                <h4 className="text-sm font-medium">Comentários</h4>
                <ul className="mt-2 space-y-2">
                  {(commentsQuery.data?.items ?? []).map((c) => (
                    <li
                      key={c.id}
                      className="rounded-md bg-secondary/40 p-2 text-sm"
                    >
                      <p className="text-xs text-muted-foreground">
                        {c.author_id.slice(0, 8)} · {c.created_at}
                      </p>
                      <p>{c.body}</p>
                    </li>
                  ))}
                </ul>
                <div className="mt-2 flex gap-2">
                  <Input
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                    placeholder="Comentar…"
                    className="flex-1"
                  />
                  <Button
                    size="sm"
                    disabled={!comment.trim() || commentMut.isPending}
                    onClick={() => commentMut.mutate(comment.trim())}
                  >
                    Enviar
                  </Button>
                </div>
              </div>

              {canResolve && selected.status !== "resolved" && (
                <div>
                  <h4 className="text-sm font-medium">Resolver</h4>
                  <textarea
                    className="mt-2 w-full rounded border border-border bg-background px-3 py-2 text-sm"
                    rows={3}
                    value={resolution}
                    onChange={(e) => setResolution(e.target.value)}
                    placeholder="Decisão ou motivo…"
                  />
                  <Button
                    className="mt-2"
                    size="sm"
                    disabled={!resolution.trim() || resolveMut.isPending}
                    onClick={() => resolveMut.mutate()}
                  >
                    Fechar solicitação
                  </Button>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-destructive">Solicitação não encontrada.</p>
          )}
        </section>
      </div>
    </div>
  );
}
