import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MarkdownPromptPreview } from "@/components/markdown-prompt-preview";
import { PromptMarkdownEditor } from "@/components/prompt-markdown-editor";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  createTeamAgent,
  fetchTeamAgents,
  patchTeamAgent,
  publishTeamAgent,
  submitTeamAgentReview,
  type TeamAgent,
} from "@/lib/api/team-agents";

export const Route = createFileRoute("/dashboard/agents")({
  component: AgentsPage,
});

const STATUSES = ["all", "draft", "review", "published"] as const;

function AgentsPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", prompt: "", modelId: "" });
  const [editing, setEditing] = useState<TeamAgent | null>(null);

  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const canDraft =
    roleData?.role === "developer" ||
    roleData?.role === "lead" ||
    roleData?.role === "admin";
  const canPublish = roleData?.role === "lead" || roleData?.role === "admin";

  const listQuery = useQuery({
    queryKey: ["team-agents", status],
    queryFn: () => fetchTeamAgents({ data: { status } }),
  });

  const createMut = useMutation({
    mutationFn: () =>
      createTeamAgent({
        data: {
          name: form.name,
          prompt: form.prompt,
          modelId: form.modelId || undefined,
        },
      }),
    onSuccess: () => {
      toast.success("Agente criado em draft.");
      setShowCreate(false);
      setForm({ name: "", prompt: "", modelId: "" });
      qc.invalidateQueries({ queryKey: ["team-agents"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const patchMut = useMutation({
    mutationFn: (agent: TeamAgent) =>
      patchTeamAgent({
        data: {
          id: agent.id,
          name: agent.name,
          prompt: agent.prompt,
          modelId: agent.model_id,
        },
      }),
    onSuccess: () => {
      toast.success("Draft guardado.");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["team-agents"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const reviewMut = useMutation({
    mutationFn: (id: string) => submitTeamAgentReview({ data: { id } }),
    onSuccess: () => {
      toast.success("Enviado para revisão.");
      qc.invalidateQueries({ queryKey: ["team-agents"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const publishMut = useMutation({
    mutationFn: (id: string) => publishTeamAgent({ data: { id } }),
    onSuccess: () => {
      toast.success("Agente publicado.");
      qc.invalidateQueries({ queryKey: ["team-agents"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const items = listQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Agentes</h2>
          <p className="text-sm text-muted-foreground">
            Ciclo draft → review → publish. Developer propõe; lead/admin
            publica.
          </p>
        </div>
        {canDraft && (
          <Button size="sm" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Cancelar" : "Novo agente"}
          </Button>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {STATUSES.map((st) => (
          <Button
            key={st}
            size="sm"
            variant={status === st ? "default" : "outline"}
            onClick={() => setStatus(st)}
          >
            {st}
          </Button>
        ))}
      </div>

      {showCreate && canDraft && (
        <section className="rounded-lg border border-border p-4">
          <h3 className="font-medium">Criar draft</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <Input
              placeholder="Nome"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <Input
              placeholder="Model ID (opcional)"
              value={form.modelId}
              onChange={(e) =>
                setForm((f) => ({ ...f, modelId: e.target.value }))
              }
            />
            <PromptMarkdownEditor
              className="md:col-span-2"
              value={form.prompt}
              onChange={(prompt) => setForm((f) => ({ ...f, prompt }))}
              placeholder="Prompt do agente (Markdown suportado)"
            />
          </div>
          <Button
            className="mt-3"
            size="sm"
            disabled={!form.name.trim() || createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            Criar draft
          </Button>
        </section>
      )}

      {listQuery.isLoading && (
        <p className="text-sm text-muted-foreground">A carregar…</p>
      )}

      <ul className="space-y-3">
        {items.length === 0 && !listQuery.isLoading ? (
          <li className="text-sm text-muted-foreground">Sem agentes.</li>
        ) : (
          items.map((agent) => (
            <li key={agent.id} className="rounded-lg border border-border p-4">
              {editing?.id === agent.id ? (
                <div className="space-y-2">
                  <Input
                    value={editing.name}
                    onChange={(e) =>
                      setEditing({ ...editing, name: e.target.value })
                    }
                  />
                  <PromptMarkdownEditor
                    value={editing.prompt}
                    onChange={(prompt) => setEditing({ ...editing, prompt })}
                  />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={() => patchMut.mutate(editing)}>
                      Guardar
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setEditing(null)}
                    >
                      Cancelar
                    </Button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <p className="font-medium">{agent.name}</p>
                      <p className="text-xs text-muted-foreground">
                        {agent.lifecycle_status} · v{agent.version}
                        {agent.model_id ? ` · ${agent.model_id}` : ""}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {agent.lifecycle_status === "draft" && canDraft && (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setEditing(agent)}
                          >
                            Editar
                          </Button>
                          <Button
                            size="sm"
                            onClick={() => reviewMut.mutate(agent.id)}
                          >
                            Enviar revisão
                          </Button>
                        </>
                      )}
                      {agent.lifecycle_status === "review" && canPublish && (
                        <Button
                          size="sm"
                          onClick={() => publishMut.mutate(agent.id)}
                        >
                          Publicar
                        </Button>
                      )}
                    </div>
                  </div>
                  {agent.prompt && (
                    <MarkdownPromptPreview text={agent.prompt} />
                  )}
                </>
              )}
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
