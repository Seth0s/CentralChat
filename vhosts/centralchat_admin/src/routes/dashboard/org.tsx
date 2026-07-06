import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, FolderKanban, Plus, UserPlus, Users } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { manageableProjects } from "@/lib/auth/org-scope";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  createOrgGroup,
  createOrgProject,
  deleteProjectMember,
  fetchOrgHealth,
  fetchOrgTree,
  fetchProjectMembers,
  patchOrgGroup,
  patchOrgProject,
  upsertProjectMember,
  type OrgGroup,
  type OrgMembership,
  type OrgProject,
} from "@/lib/api/org";
import { createAdminUser, fetchAdminUsers } from "@/lib/api/users";

export const Route = createFileRoute("/dashboard/org")({
  component: OrgPage,
});

function OrgPage() {
  const qc = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["org-tree"],
    queryFn: () => fetchOrgTree(),
  });
  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const orgHealthQuery = useQuery({
    queryKey: ["org-health"],
    queryFn: () => fetchOrgHealth(),
    enabled:
      roleData?.role === "admin" ||
      roleData?.role === "lead" ||
      roleData?.role === "auditor",
  });
  const usersQuery = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => fetchAdminUsers({ data: { limit: 200 } }),
    enabled: roleData?.role === "admin" || roleData?.role === "lead",
  });

  const [groupForm, setGroupForm] = useState({
    name: "",
    slug: "",
    description: "",
  });
  const [userForm, setUserForm] = useState({
    email: "",
    password: "",
    displayName: "",
    role: "developer" as "admin" | "lead" | "developer" | "auditor",
  });
  const [projectForm, setProjectForm] = useState({
    groupId: "",
    name: "",
    slug: "",
    repositoryUrl: "",
  });
  const [memberForm, setMemberForm] = useState({
    projectId: "",
    userId: "",
    role: "developer" as "admin" | "lead" | "developer" | "auditor",
  });
  const [selectedMembersProjectId, setSelectedMembersProjectId] = useState("");

  const invalidateOrg = () => qc.invalidateQueries({ queryKey: ["org-tree"] });

  const groupMut = useMutation({
    mutationFn: () =>
      createOrgGroup({
        data: {
          name: groupForm.name,
          slug: groupForm.slug || undefined,
          description: groupForm.description || undefined,
        },
      }),
    onSuccess: () => {
      setGroupForm({ name: "", slug: "", description: "" });
      invalidateOrg();
    },
  });

  const projectMut = useMutation({
    mutationFn: () =>
      createOrgProject({
        data: {
          groupId: projectForm.groupId,
          name: projectForm.name,
          slug: projectForm.slug || undefined,
          repositoryUrl: projectForm.repositoryUrl || undefined,
        },
      }),
    onSuccess: () => {
      setProjectForm({ groupId: "", name: "", slug: "", repositoryUrl: "" });
      invalidateOrg();
    },
  });

  const groupPatchMut = useMutation({
    mutationFn: (data: {
      groupId: string;
      name: string;
      slug?: string;
      description?: string;
    }) => patchOrgGroup({ data }),
    onSuccess: () => invalidateOrg(),
  });

  const projectPatchMut = useMutation({
    mutationFn: (data: {
      projectId: string;
      name: string;
      slug?: string;
      description?: string;
      repositoryUrl?: string;
    }) => patchOrgProject({ data }),
    onSuccess: () => invalidateOrg(),
  });

  const memberMut = useMutation({
    mutationFn: () => upsertProjectMember({ data: memberForm }),
    onSuccess: () => {
      setMemberForm({ projectId: "", userId: "", role: "developer" });
      invalidateOrg();
      qc.invalidateQueries({ queryKey: ["project-members"] });
    },
  });

  const memberRoleMut = useMutation({
    mutationFn: (data: {
      projectId: string;
      userId: string;
      role: "admin" | "lead" | "developer" | "auditor";
    }) => upsertProjectMember({ data }),
    onSuccess: () => {
      invalidateOrg();
      qc.invalidateQueries({ queryKey: ["project-members"] });
    },
  });

  const memberDeleteMut = useMutation({
    mutationFn: (data: { projectId: string; userId: string }) =>
      deleteProjectMember({ data }),
    onSuccess: () => {
      invalidateOrg();
      qc.invalidateQueries({ queryKey: ["project-members"] });
    },
  });

  const groups = data?.groups ?? [];
  const projects = data?.projects ?? [];
  const memberships = data?.memberships ?? [];
  const users = usersQuery.data?.items ?? [];
  const isAdmin = roleData?.role === "admin";
  const manageable = manageableProjects({
    projects,
    memberships,
    role: roleData?.role,
  });
  const canManageAnyProject = manageable.length > 0;
  const manageableProjectIds = new Set(manageable.map((project) => project.id));
  const selectedMembersProject = manageable.find(
    (project) => project.id === selectedMembersProjectId,
  );
  const projectMembersQuery = useQuery({
    queryKey: ["project-members", selectedMembersProjectId],
    queryFn: () =>
      fetchProjectMembers({ data: { projectId: selectedMembersProjectId } }),
    enabled: Boolean(selectedMembersProjectId),
  });

  const userMut = useMutation({
    mutationFn: () =>
      createAdminUser({
        data: {
          email: userForm.email,
          password: userForm.password,
          displayName: userForm.displayName || undefined,
          role: userForm.role,
        },
      }),
    onSuccess: (created) => {
      setUserForm({
        email: "",
        password: "",
        displayName: "",
        role: "developer",
      });
      setMemberForm((form) => ({ ...form, userId: created.user.id }));
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Organização</h2>
        <p className="text-sm text-muted-foreground">
          Estrutura inicial de grupos, projetos e vínculos por escopo. Usuários
          só ganham acesso operacional quando entram em um escopo.
        </p>
      </div>

      {isLoading && (
        <p className="text-sm text-muted-foreground">A carregar organização…</p>
      )}
      {error && (
        <p className="text-sm text-destructive">{(error as Error).message}</p>
      )}

      {data && !data.org_enabled && (
        <p className="text-sm text-muted-foreground">
          Organização desativada ou sem Postgres.
        </p>
      )}

      {data && (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <MetricCard
              icon={<Building2 className="h-4 w-4" />}
              label="Grupos"
              value={groups.length}
            />
            <MetricCard
              icon={<FolderKanban className="h-4 w-4" />}
              label="Projetos"
              value={projects.length}
            />
            <MetricCard
              icon={<Users className="h-4 w-4" />}
              label="Vínculos"
              value={memberships.length}
            />
          </div>

          {orgHealthQuery.data && (
            <OrgHealthPanel
              groupsWithoutProjects={
                orgHealthQuery.data.groups_without_projects
              }
              projectsWithoutLead={
                orgHealthQuery.data.projects_without_direct_lead
              }
            />
          )}
          {orgHealthQuery.error && (
            <p className="text-sm text-destructive">
              {(orgHealthQuery.error as Error).message}
            </p>
          )}

          <div className="grid gap-4 xl:grid-cols-4">
            {isAdmin && (
              <section className="rounded-lg border border-border bg-card p-4">
                <div className="mb-3 flex items-center gap-2">
                  <UserPlus className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-medium">Criar usuário</h3>
                </div>
                <form
                  className="space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    userMut.mutate();
                  }}
                >
                  <Input
                    type="email"
                    placeholder="email"
                    value={userForm.email}
                    onChange={(event) =>
                      setUserForm((form) => ({
                        ...form,
                        email: event.target.value,
                      }))
                    }
                    required
                  />
                  <Input
                    placeholder="nome opcional"
                    value={userForm.displayName}
                    onChange={(event) =>
                      setUserForm((form) => ({
                        ...form,
                        displayName: event.target.value,
                      }))
                    }
                  />
                  <Input
                    type="password"
                    placeholder="senha inicial"
                    value={userForm.password}
                    onChange={(event) =>
                      setUserForm((form) => ({
                        ...form,
                        password: event.target.value,
                      }))
                    }
                    required
                  />
                  <select
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                    value={userForm.role}
                    onChange={(event) =>
                      setUserForm((form) => ({
                        ...form,
                        role: event.target.value as
                          | "admin"
                          | "lead"
                          | "developer"
                          | "auditor",
                      }))
                    }
                  >
                    <option value="developer">developer</option>
                    <option value="lead">lead</option>
                    <option value="auditor">auditor</option>
                    <option value="admin">admin</option>
                  </select>
                  <Button
                    type="submit"
                    size="sm"
                    disabled={
                      userMut.isPending ||
                      !userForm.email.trim() ||
                      userForm.password.length < 8
                    }
                  >
                    Criar usuário
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    Criar usuário não cria acesso operacional; adicione
                    membership depois.
                  </p>
                  {userMut.error && (
                    <p className="text-xs text-destructive">
                      {(userMut.error as Error).message}
                    </p>
                  )}
                </form>
              </section>
            )}

            {isAdmin && (
              <section className="rounded-lg border border-border bg-card p-4">
                <div className="mb-3 flex items-center gap-2">
                  <Plus className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-medium">Criar grupo</h3>
                </div>
                <form
                  className="space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    groupMut.mutate();
                  }}
                >
                  <Input
                    placeholder="Nome do grupo"
                    value={groupForm.name}
                    onChange={(event) =>
                      setGroupForm((form) => ({
                        ...form,
                        name: event.target.value,
                      }))
                    }
                    required
                  />
                  <Input
                    placeholder="slug opcional"
                    value={groupForm.slug}
                    onChange={(event) =>
                      setGroupForm((form) => ({
                        ...form,
                        slug: event.target.value,
                      }))
                    }
                  />
                  <Input
                    placeholder="descrição opcional"
                    value={groupForm.description}
                    onChange={(event) =>
                      setGroupForm((form) => ({
                        ...form,
                        description: event.target.value,
                      }))
                    }
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={groupMut.isPending || !groupForm.name.trim()}
                  >
                    Criar grupo
                  </Button>
                  {groupMut.error && (
                    <p className="text-xs text-destructive">
                      {(groupMut.error as Error).message}
                    </p>
                  )}
                </form>
              </section>
            )}

            {isAdmin && (
              <section className="rounded-lg border border-border bg-card p-4">
                <div className="mb-3 flex items-center gap-2">
                  <FolderKanban className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-medium">Criar projeto</h3>
                </div>
                <form
                  className="space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    projectMut.mutate();
                  }}
                >
                  <select
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                    value={projectForm.groupId}
                    onChange={(event) =>
                      setProjectForm((form) => ({
                        ...form,
                        groupId: event.target.value,
                      }))
                    }
                    required
                  >
                    <option value="">Selecione um grupo</option>
                    {groups.map((group) => (
                      <option key={group.id} value={group.id}>
                        {group.name}
                      </option>
                    ))}
                  </select>
                  <Input
                    placeholder="Nome do projeto"
                    value={projectForm.name}
                    onChange={(event) =>
                      setProjectForm((form) => ({
                        ...form,
                        name: event.target.value,
                      }))
                    }
                    required
                  />
                  <Input
                    placeholder="slug opcional"
                    value={projectForm.slug}
                    onChange={(event) =>
                      setProjectForm((form) => ({
                        ...form,
                        slug: event.target.value,
                      }))
                    }
                  />
                  <Input
                    placeholder="repository URL opcional"
                    value={projectForm.repositoryUrl}
                    onChange={(event) =>
                      setProjectForm((form) => ({
                        ...form,
                        repositoryUrl: event.target.value,
                      }))
                    }
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={
                      projectMut.isPending ||
                      !projectForm.groupId ||
                      !projectForm.name.trim()
                    }
                  >
                    Criar projeto
                  </Button>
                  {projectMut.error && (
                    <p className="text-xs text-destructive">
                      {(projectMut.error as Error).message}
                    </p>
                  )}
                </form>
              </section>
            )}

            {canManageAnyProject && (
              <section className="rounded-lg border border-border bg-card p-4">
                <div className="mb-3 flex items-center gap-2">
                  <UserPlus className="h-4 w-4 text-muted-foreground" />
                  <h3 className="font-medium">Adicionar membership</h3>
                </div>
                <form
                  className="space-y-3"
                  onSubmit={(event) => {
                    event.preventDefault();
                    memberMut.mutate();
                  }}
                >
                  <select
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                    value={memberForm.projectId}
                    onChange={(event) =>
                      setMemberForm((form) => ({
                        ...form,
                        projectId: event.target.value,
                      }))
                    }
                    required
                  >
                    <option value="">Selecione um projeto</option>
                    {manageable.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name}
                      </option>
                    ))}
                  </select>
                  <select
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                    value={memberForm.userId}
                    onChange={(event) =>
                      setMemberForm((form) => ({
                        ...form,
                        userId: event.target.value,
                      }))
                    }
                    required
                  >
                    <option value="">Selecione um usuário</option>
                    {users.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.display_name || user.email} ({user.role})
                      </option>
                    ))}
                  </select>
                  <select
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                    value={memberForm.role}
                    onChange={(event) =>
                      setMemberForm((form) => ({
                        ...form,
                        role: event.target.value as
                          | "admin"
                          | "lead"
                          | "developer"
                          | "auditor",
                      }))
                    }
                  >
                    <option value="developer">developer</option>
                    <option value="lead">lead</option>
                    <option value="auditor">auditor</option>
                    <option value="admin">admin</option>
                  </select>
                  <Button
                    type="submit"
                    size="sm"
                    disabled={
                      memberMut.isPending ||
                      !memberForm.projectId ||
                      !memberForm.userId.trim()
                    }
                  >
                    Adicionar membro
                  </Button>
                  {memberMut.error && (
                    <p className="text-xs text-destructive">
                      {(memberMut.error as Error).message}
                    </p>
                  )}
                </form>
              </section>
            )}
          </div>

          {canManageAnyProject && (
            <ProjectMembersPanel
              projects={manageable}
              users={users}
              selectedProjectId={selectedMembersProjectId}
              selectedProjectName={selectedMembersProject?.name ?? ""}
              members={projectMembersQuery.data?.items ?? []}
              isLoading={projectMembersQuery.isLoading}
              error={projectMembersQuery.error}
              onSelectProject={setSelectedMembersProjectId}
              onChangeRole={(membership, role) =>
                memberRoleMut.mutate({
                  projectId: membership.scope_id,
                  userId: membership.user_id,
                  role,
                })
              }
              onDelete={(membership) =>
                memberDeleteMut.mutate({
                  projectId: membership.scope_id,
                  userId: membership.user_id,
                })
              }
              rolePending={memberRoleMut.isPending}
              deletePending={memberDeleteMut.isPending}
              roleError={memberRoleMut.error}
              deleteError={memberDeleteMut.error}
            />
          )}

          <section className="rounded-lg border border-border bg-card">
            <div className="border-b border-border px-4 py-3">
              <h3 className="font-medium">
                Árvore Organização → Grupos → Projetos
              </h3>
              <p className="text-xs text-muted-foreground">
                Tenant: {data.tenant_id}
              </p>
            </div>
            <div className="divide-y divide-border">
              {groups.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">
                  Nenhum grupo criado ainda. O próximo passo é criar grupos e
                  projetos.
                </p>
              ) : (
                groups.map((group) => {
                  const groupProjects = projects.filter(
                    (project) => project.group_id === group.id,
                  );
                  return (
                    <div key={group.id} className="p-4">
                      <div className="flex items-start justify-between gap-4">
                        <EditableGroupSummary
                          group={group}
                          canEdit={isAdmin}
                          pending={groupPatchMut.isPending}
                          onSave={(patch) =>
                            groupPatchMut.mutate({
                              groupId: group.id,
                              ...patch,
                            })
                          }
                        />
                        <span className="rounded-full bg-secondary px-2 py-1 text-xs text-muted-foreground">
                          {groupProjects.length} projeto
                          {groupProjects.length === 1 ? "" : "s"}
                        </span>
                      </div>
                      {groupProjects.length > 0 && (
                        <ul className="mt-3 grid gap-2 md:grid-cols-2">
                          {groupProjects.map((project) => (
                            <EditableProjectCard
                              key={project.id}
                              project={project}
                              canEdit={
                                isAdmin || manageableProjectIds.has(project.id)
                              }
                              pending={projectPatchMut.isPending}
                              onSave={(patch) =>
                                projectPatchMut.mutate({
                                  projectId: project.id,
                                  ...patch,
                                })
                              }
                            />
                          ))}
                        </ul>
                      )}
                    </div>
                  );
                })
              )}
            </div>
            {groupPatchMut.error && (
              <p className="px-4 py-3 text-xs text-destructive">
                {(groupPatchMut.error as Error).message}
              </p>
            )}
            {projectPatchMut.error && (
              <p className="px-4 py-3 text-xs text-destructive">
                {(projectPatchMut.error as Error).message}
              </p>
            )}
          </section>

          {memberships.length > 0 && (
            <section className="rounded-lg border border-border bg-card">
              <div className="border-b border-border px-4 py-3">
                <h3 className="font-medium">Vínculos visíveis</h3>
                <p className="text-xs text-muted-foreground">
                  Escopos retornados para a sessão atual.
                </p>
              </div>
              <ul className="divide-y divide-border">
                {memberships.map((membership) => (
                  <li
                    key={membership.id}
                    className="grid gap-2 px-4 py-3 text-sm md:grid-cols-4"
                  >
                    <span className="font-mono text-xs text-muted-foreground">
                      {membership.user_id}
                    </span>
                    <span>{membership.scope_type}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {membership.scope_id}
                    </span>
                    <span className="font-medium">{membership.role}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function OrgHealthPanel({
  groupsWithoutProjects,
  projectsWithoutLead,
}: {
  groupsWithoutProjects: OrgGroup[];
  projectsWithoutLead: OrgProject[];
}) {
  const hasWarnings =
    groupsWithoutProjects.length > 0 || projectsWithoutLead.length > 0;
  return (
    <section
      className={`rounded-lg border p-4 ${hasWarnings ? "border-amber-300 bg-amber-50/40" : "border-border bg-card"}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="font-medium">Saúde da organização</h3>
          <p className="text-sm text-muted-foreground">
            Alertas estruturais para evitar projetos sem dono claro e grupos
            esquecidos.
          </p>
        </div>
        <span className="rounded-full bg-secondary px-2 py-1 text-xs text-muted-foreground">
          {groupsWithoutProjects.length + projectsWithoutLead.length} alerta
          {groupsWithoutProjects.length + projectsWithoutLead.length === 1
            ? ""
            : "s"}
        </span>
      </div>

      {!hasWarnings ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Nenhum alerta estrutural no escopo visível.
        </p>
      ) : (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <p className="text-sm font-medium">Projetos sem lead direto</p>
            {projectsWithoutLead.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">Tudo certo.</p>
            ) : (
              <ul className="mt-2 space-y-1">
                {projectsWithoutLead.map((project) => (
                  <li
                    key={project.id}
                    className="rounded-md border border-border bg-background px-3 py-2 text-sm"
                  >
                    {project.name}
                    <span className="ml-2 font-mono text-xs text-muted-foreground">
                      {project.slug}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <p className="text-sm font-medium">Grupos sem projetos</p>
            {groupsWithoutProjects.length === 0 ? (
              <p className="mt-2 text-xs text-muted-foreground">Tudo certo.</p>
            ) : (
              <ul className="mt-2 space-y-1">
                {groupsWithoutProjects.map((group) => (
                  <li
                    key={group.id}
                    className="rounded-md border border-border bg-background px-3 py-2 text-sm"
                  >
                    {group.name}
                    <span className="ml-2 font-mono text-xs text-muted-foreground">
                      {group.slug}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function EditableGroupSummary({
  group,
  canEdit,
  pending,
  onSave,
}: {
  group: OrgGroup;
  canEdit: boolean;
  pending: boolean;
  onSave: (patch: {
    name: string;
    slug?: string;
    description?: string;
  }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: group.name,
    slug: group.slug,
    description: group.description || "",
  });

  if (!editing) {
    return (
      <div className="min-w-0">
        <h4 className="font-medium">{group.name}</h4>
        <p className="font-mono text-xs text-muted-foreground">{group.slug}</p>
        {group.description && (
          <p className="mt-1 text-sm text-muted-foreground">
            {group.description}
          </p>
        )}
        {canEdit && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="mt-2"
            onClick={() => setEditing(true)}
          >
            Editar grupo
          </Button>
        )}
      </div>
    );
  }

  return (
    <form
      className="min-w-0 flex-1 space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({
          name: form.name,
          slug: form.slug || undefined,
          description: form.description || undefined,
        });
        setEditing(false);
      }}
    >
      <Input
        value={form.name}
        onChange={(event) =>
          setForm((current) => ({ ...current, name: event.target.value }))
        }
        required
      />
      <Input
        value={form.slug}
        onChange={(event) =>
          setForm((current) => ({ ...current, slug: event.target.value }))
        }
        placeholder="slug"
      />
      <Input
        value={form.description}
        onChange={(event) =>
          setForm((current) => ({
            ...current,
            description: event.target.value,
          }))
        }
        placeholder="descrição"
      />
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={pending || !form.name.trim()}>
          Salvar
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setEditing(false)}
        >
          Cancelar
        </Button>
      </div>
    </form>
  );
}

function EditableProjectCard({
  project,
  canEdit,
  pending,
  onSave,
}: {
  project: OrgProject;
  canEdit: boolean;
  pending: boolean;
  onSave: (patch: {
    name: string;
    slug?: string;
    description?: string;
    repositoryUrl?: string;
  }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    name: project.name,
    slug: project.slug,
    description: project.description || "",
    repositoryUrl: project.repository_url || "",
  });

  if (!editing) {
    return (
      <li className="rounded-md border border-border p-3">
        <p className="text-sm font-medium">{project.name}</p>
        <p className="font-mono text-xs text-muted-foreground">
          {project.slug}
        </p>
        {project.repository_url && (
          <p className="mt-1 truncate text-xs text-muted-foreground">
            repo: {project.repository_url}
          </p>
        )}
        {project.description && (
          <p className="mt-1 text-xs text-muted-foreground">
            {project.description}
          </p>
        )}
        {canEdit && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="mt-2"
            onClick={() => setEditing(true)}
          >
            Editar projeto
          </Button>
        )}
      </li>
    );
  }

  return (
    <li className="rounded-md border border-border p-3">
      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          onSave({
            name: form.name,
            slug: form.slug || undefined,
            description: form.description || undefined,
            repositoryUrl: form.repositoryUrl || undefined,
          });
          setEditing(false);
        }}
      >
        <Input
          value={form.name}
          onChange={(event) =>
            setForm((current) => ({ ...current, name: event.target.value }))
          }
          required
        />
        <Input
          value={form.slug}
          onChange={(event) =>
            setForm((current) => ({ ...current, slug: event.target.value }))
          }
          placeholder="slug"
        />
        <Input
          value={form.repositoryUrl}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              repositoryUrl: event.target.value,
            }))
          }
          placeholder="repository URL"
        />
        <Input
          value={form.description}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              description: event.target.value,
            }))
          }
          placeholder="descrição"
        />
        <div className="flex gap-2">
          <Button
            type="submit"
            size="sm"
            disabled={pending || !form.name.trim()}
          >
            Salvar
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setEditing(false)}
          >
            Cancelar
          </Button>
        </div>
      </form>
    </li>
  );
}

function ProjectMembersPanel({
  projects,
  users,
  selectedProjectId,
  selectedProjectName,
  members,
  isLoading,
  error,
  onSelectProject,
  onChangeRole,
  onDelete,
  rolePending,
  deletePending,
  roleError,
  deleteError,
}: {
  projects: { id: string; name: string }[];
  users: { id: string; email: string; display_name: string }[];
  selectedProjectId: string;
  selectedProjectName: string;
  members: OrgMembership[];
  isLoading: boolean;
  error: unknown;
  onSelectProject: (projectId: string) => void;
  onChangeRole: (
    membership: OrgMembership,
    role: "admin" | "lead" | "developer" | "auditor",
  ) => void;
  onDelete: (membership: OrgMembership) => void;
  rolePending: boolean;
  deletePending: boolean;
  roleError: unknown;
  deleteError: unknown;
}) {
  const userLabel = (userId: string) => {
    const user = users.find((item) => item.id === userId);
    return user ? user.display_name || user.email : userId;
  };

  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="flex flex-col gap-3 border-b border-border px-4 py-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 className="font-medium">Membros do projeto</h3>
          <p className="text-xs text-muted-foreground">
            Gerencie papéis contextuais apenas nos projetos sob seu escopo.
          </p>
        </div>
        <select
          className="flex h-9 min-w-64 rounded-md border border-input bg-transparent px-3 py-1 text-sm"
          value={selectedProjectId}
          onChange={(event) => onSelectProject(event.target.value)}
        >
          <option value="">Selecione um projeto</option>
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>

      {!selectedProjectId ? (
        <p className="p-4 text-sm text-muted-foreground">
          Selecione um projeto para ver memberships.
        </p>
      ) : isLoading ? (
        <p className="p-4 text-sm text-muted-foreground">
          A carregar membros...
        </p>
      ) : error ? (
        <p className="p-4 text-sm text-destructive">
          {(error as Error).message}
        </p>
      ) : members.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">
          Nenhum membro direto em {selectedProjectName || "projeto selecionado"}
          .
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {members.map((membership) => (
            <li
              key={membership.id}
              className="grid gap-3 px-4 py-3 text-sm md:grid-cols-[minmax(0,1fr)_180px_120px]"
            >
              <div className="min-w-0">
                <p className="truncate font-medium">
                  {userLabel(membership.user_id)}
                </p>
                <p className="truncate font-mono text-xs text-muted-foreground">
                  {membership.user_id}
                </p>
              </div>
              <select
                className="flex h-9 rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                value={membership.role}
                disabled={rolePending}
                onChange={(event) =>
                  onChangeRole(
                    membership,
                    event.target.value as
                      | "admin"
                      | "lead"
                      | "developer"
                      | "auditor",
                  )
                }
              >
                <option value="developer">developer</option>
                <option value="lead">lead</option>
                <option value="auditor">auditor</option>
                <option value="admin">admin</option>
              </select>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={deletePending}
                onClick={() => onDelete(membership)}
              >
                Remover
              </Button>
            </li>
          ))}
        </ul>
      )}

      {roleError && (
        <p className="px-4 py-3 text-xs text-destructive">
          {(roleError as Error).message}
        </p>
      )}
      {deleteError && (
        <p className="px-4 py-3 text-xs text-destructive">
          {(deleteError as Error).message}
        </p>
      )}
    </section>
  );
}

function MetricCard({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        {icon}
        {label}
      </div>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}
