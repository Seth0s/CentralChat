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
  createTeamSkill,
  fetchTeamSkills,
  patchTeamSkill,
  publishTeamSkill,
  submitTeamSkillReview,
  type TeamSkill,
} from "@/lib/api/team-skills";

export const Route = createFileRoute("/dashboard/skills")({
  component: SkillsPage,
});

const STATUSES = ["all", "draft", "review", "published"] as const;

function SkillsPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", description: "", prompt: "" });
  const [editing, setEditing] = useState<TeamSkill | null>(null);

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
    queryKey: ["team-skills", status],
    queryFn: () => fetchTeamSkills({ data: { status } }),
  });

  const createMut = useMutation({
    mutationFn: () => createTeamSkill({ data: form }),
    onSuccess: () => {
      toast.success("Skill criada em draft.");
      setShowCreate(false);
      setForm({ name: "", description: "", prompt: "" });
      qc.invalidateQueries({ queryKey: ["team-skills"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const patchMut = useMutation({
    mutationFn: (skill: TeamSkill) =>
      patchTeamSkill({
        data: {
          id: skill.id,
          name: skill.name,
          description: skill.description,
          prompt: skill.prompt,
        },
      }),
    onSuccess: () => {
      toast.success("Draft guardado.");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["team-skills"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const reviewMut = useMutation({
    mutationFn: (id: string) => submitTeamSkillReview({ data: { id } }),
    onSuccess: () => {
      toast.success("Enviada para revisão.");
      qc.invalidateQueries({ queryKey: ["team-skills"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const publishMut = useMutation({
    mutationFn: (id: string) => publishTeamSkill({ data: { id } }),
    onSuccess: () => {
      toast.success("Skill publicada.");
      qc.invalidateQueries({ queryKey: ["team-skills"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const items = listQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Skills</h2>
          <p className="text-sm text-muted-foreground">
            Skills partilhadas com o mesmo ciclo de governança dos agentes.
          </p>
        </div>
        {canDraft && (
          <Button size="sm" onClick={() => setShowCreate((v) => !v)}>
            {showCreate ? "Cancelar" : "Nova skill"}
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
          <div className="mt-3 grid gap-2">
            <Input
              placeholder="Nome"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <Input
              placeholder="Descrição"
              value={form.description}
              onChange={(e) =>
                setForm((f) => ({ ...f, description: e.target.value }))
              }
            />
            <PromptMarkdownEditor
              value={form.prompt}
              onChange={(prompt) => setForm((f) => ({ ...f, prompt }))}
              placeholder="Prompt / instruções (Markdown suportado)"
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

      <ul className="space-y-3">
        {items.map((skill) => (
          <li key={skill.id} className="rounded-lg border border-border p-4">
            {editing?.id === skill.id ? (
              <div className="space-y-2">
                <Input
                  value={editing.name}
                  onChange={(e) =>
                    setEditing({ ...editing, name: e.target.value })
                  }
                />
                <Input
                  value={editing.description}
                  onChange={(e) =>
                    setEditing({ ...editing, description: e.target.value })
                  }
                />
                <PromptMarkdownEditor
                  value={editing.prompt}
                  onChange={(prompt) => setEditing({ ...editing, prompt })}
                />
                <Button size="sm" onClick={() => patchMut.mutate(editing)}>
                  Guardar
                </Button>
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-medium">{skill.name}</p>
                    <p className="text-xs text-muted-foreground">
                      {skill.lifecycle_status} · v{skill.version}
                    </p>
                    {skill.description && (
                      <p className="mt-1 text-sm text-muted-foreground">
                        {skill.description}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2">
                    {skill.lifecycle_status === "draft" && canDraft && (
                      <>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setEditing(skill)}
                        >
                          Editar
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => reviewMut.mutate(skill.id)}
                        >
                          Enviar revisão
                        </Button>
                      </>
                    )}
                    {skill.lifecycle_status === "review" && canPublish && (
                      <Button
                        size="sm"
                        onClick={() => publishMut.mutate(skill.id)}
                      >
                        Publicar
                      </Button>
                    )}
                  </div>
                </div>
                {skill.prompt && <MarkdownPromptPreview text={skill.prompt} />}
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
