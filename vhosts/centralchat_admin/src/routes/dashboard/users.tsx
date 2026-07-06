import { createFileRoute } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Search, UserPlus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { deleteProjectMember, type OrgMembership } from "@/lib/api/org";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  createAdminUser,
  fetchAdminUserMemberships,
  fetchAdminUsers,
  patchAdminUser,
  revokeAdminUserSessions,
  resetAdminUserPassword,
  type AdminUser,
} from "@/lib/api/users";

type BaseRole = "admin" | "lead" | "developer" | "auditor";

export const Route = createFileRoute("/dashboard/users")({
  component: UsersPage,
});

function UsersPage() {
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [createForm, setCreateForm] = useState({
    email: "",
    password: "",
    displayName: "",
    role: "developer" as BaseRole,
  });
  const [resetPasswords, setResetPasswords] = useState<Record<string, string>>(
    {},
  );
  const [selectedUserId, setSelectedUserId] = useState("");
  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });

  const usersQuery = useQuery({
    queryKey: ["admin-users", submittedQuery],
    queryFn: () =>
      fetchAdminUsers({ data: { q: submittedQuery || undefined, limit: 300 } }),
  });

  const users = useMemo(
    () => usersQuery.data?.items ?? [],
    [usersQuery.data?.items],
  );
  const selectedUser = users.find((user) => user.id === selectedUserId);
  const activeCount = useMemo(
    () => users.filter((user) => user.active).length,
    [users],
  );
  const isAdmin = roleData?.role === "admin";

  const membershipsQuery = useQuery({
    queryKey: ["admin-user-memberships", selectedUserId],
    queryFn: () =>
      fetchAdminUserMemberships({ data: { userId: selectedUserId } }),
    enabled: Boolean(selectedUserId),
  });

  const invalidateUsers = () =>
    qc.invalidateQueries({ queryKey: ["admin-users"] });

  const createMut = useMutation({
    mutationFn: () =>
      createAdminUser({
        data: {
          email: createForm.email,
          password: createForm.password,
          displayName: createForm.displayName || undefined,
          role: createForm.role,
        },
      }),
    onSuccess: () => {
      setCreateForm({
        email: "",
        password: "",
        displayName: "",
        role: "developer",
      });
      invalidateUsers();
    },
  });

  const patchMut = useMutation({
    mutationFn: (data: {
      userId: string;
      displayName?: string;
      role?: BaseRole;
      active?: boolean;
    }) => patchAdminUser({ data }),
    onSuccess: () => invalidateUsers(),
  });

  const resetMut = useMutation({
    mutationFn: (data: { userId: string; password: string }) =>
      resetAdminUserPassword({ data }),
    onSuccess: (_result, variables) => {
      setResetPasswords((current) => ({ ...current, [variables.userId]: "" }));
    },
  });

  const revokeSessionsMut = useMutation({
    mutationFn: (data: { userId: string }) => revokeAdminUserSessions({ data }),
  });

  const membershipDeleteMut = useMutation({
    mutationFn: (data: { projectId: string; userId: string }) =>
      deleteProjectMember({ data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-user-memberships"] });
    },
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold">Usuários</h2>
        <p className="text-sm text-muted-foreground">
          Identidade do tenant. Usuário criado aqui não recebe acesso
          operacional até ganhar vínculo em organização, grupo ou projeto.
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <MetricCard label="Usuários" value={users.length} />
        <MetricCard label="Ativos" value={activeCount} />
        <MetricCard label="Inativos" value={users.length - activeCount} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <section className="rounded-lg border border-border bg-card p-4">
          <div className="mb-3 flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-muted-foreground" />
            <h3 className="font-medium">Criar usuário</h3>
          </div>
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              createMut.mutate();
            }}
          >
            <Input
              type="email"
              placeholder="email"
              value={createForm.email}
              onChange={(event) =>
                setCreateForm((form) => ({
                  ...form,
                  email: event.target.value,
                }))
              }
              required
            />
            <Input
              placeholder="nome opcional"
              value={createForm.displayName}
              onChange={(event) =>
                setCreateForm((form) => ({
                  ...form,
                  displayName: event.target.value,
                }))
              }
            />
            <Input
              type="password"
              placeholder="senha inicial"
              value={createForm.password}
              onChange={(event) =>
                setCreateForm((form) => ({
                  ...form,
                  password: event.target.value,
                }))
              }
              required
            />
            <RoleSelect
              value={createForm.role}
              onChange={(role) => setCreateForm((form) => ({ ...form, role }))}
            />
            <Button
              type="submit"
              size="sm"
              disabled={
                !isAdmin ||
                createMut.isPending ||
                !createForm.email.trim() ||
                createForm.password.length < 8
              }
            >
              Criar usuário
            </Button>
            <p className="text-xs text-muted-foreground">
              {isAdmin
                ? "Papéis base servem para bootstrap/administração. Acesso real a projetos vem dos vínculos."
                : "Somente admin pode criar ou alterar usuários."}
            </p>
            {createMut.error && (
              <p className="text-xs text-destructive">
                {(createMut.error as Error).message}
              </p>
            )}
          </form>
        </section>

        <section className="rounded-lg border border-border bg-card">
          <div className="flex flex-col gap-3 border-b border-border px-4 py-3 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-muted-foreground" />
              <h3 className="font-medium">Lista de usuários</h3>
            </div>
            <form
              className="flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                setSubmittedQuery(query.trim());
              }}
            >
              <Input
                placeholder="buscar email ou nome"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <Button type="submit" size="sm" variant="outline">
                <Search className="mr-1 h-4 w-4" />
                Buscar
              </Button>
            </form>
          </div>

          {usersQuery.isLoading ? (
            <p className="p-4 text-sm text-muted-foreground">
              A carregar usuários...
            </p>
          ) : usersQuery.error ? (
            <p className="p-4 text-sm text-destructive">
              {(usersQuery.error as Error).message}
            </p>
          ) : users.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">
              Nenhum usuário encontrado.
            </p>
          ) : (
            <div className="divide-y divide-border">
              {users.map((user) => (
                <UserRow
                  key={user.id}
                  user={user}
                  resetPassword={resetPasswords[user.id] ?? ""}
                  onResetPasswordChange={(password) =>
                    setResetPasswords((current) => ({
                      ...current,
                      [user.id]: password,
                    }))
                  }
                  onPatch={(patch) =>
                    patchMut.mutate({ userId: user.id, ...patch })
                  }
                  onReset={() =>
                    resetMut.mutate({
                      userId: user.id,
                      password: resetPasswords[user.id] ?? "",
                    })
                  }
                  onRevokeSessions={() =>
                    revokeSessionsMut.mutate({ userId: user.id })
                  }
                  onSelectMemberships={() => setSelectedUserId(user.id)}
                  selected={selectedUserId === user.id}
                  canMutate={isAdmin}
                  patchPending={patchMut.isPending}
                  resetPending={resetMut.isPending}
                  revokeSessionsPending={revokeSessionsMut.isPending}
                />
              ))}
            </div>
          )}

          {patchMut.error && (
            <p className="px-4 py-3 text-xs text-destructive">
              {(patchMut.error as Error).message}
            </p>
          )}
          {resetMut.error && (
            <p className="px-4 py-3 text-xs text-destructive">
              {(resetMut.error as Error).message}
            </p>
          )}
          {revokeSessionsMut.error && (
            <p className="px-4 py-3 text-xs text-destructive">
              {(revokeSessionsMut.error as Error).message}
            </p>
          )}
        </section>
      </div>

      <UserMembershipsPanel
        selectedUser={selectedUser}
        memberships={membershipsQuery.data?.items ?? []}
        isLoading={membershipsQuery.isLoading}
        error={membershipsQuery.error}
        deletePending={membershipDeleteMut.isPending}
        deleteError={membershipDeleteMut.error}
        canDeleteProjectMembership={isAdmin}
        onDeleteProjectMembership={(membership) =>
          membershipDeleteMut.mutate({
            projectId: membership.scope_id,
            userId: membership.user_id,
          })
        }
      />
    </div>
  );
}

function UserRow({
  user,
  resetPassword,
  onResetPasswordChange,
  onPatch,
  onReset,
  onRevokeSessions,
  onSelectMemberships,
  selected,
  canMutate,
  patchPending,
  resetPending,
  revokeSessionsPending,
}: {
  user: AdminUser;
  resetPassword: string;
  onResetPasswordChange: (password: string) => void;
  onPatch: (patch: {
    displayName?: string;
    role?: BaseRole;
    active?: boolean;
  }) => void;
  onReset: () => void;
  onRevokeSessions: () => void;
  onSelectMemberships: () => void;
  selected: boolean;
  canMutate: boolean;
  patchPending: boolean;
  resetPending: boolean;
  revokeSessionsPending: boolean;
}) {
  const [displayName, setDisplayName] = useState(user.display_name || "");
  const role = isBaseRole(user.role) ? user.role : "developer";

  return (
    <div
      className={`grid gap-3 p-4 xl:grid-cols-[minmax(0,1fr)_170px_110px_340px] xl:items-center ${selected ? "bg-secondary/40" : ""}`}
    >
      <div className="min-w-0 space-y-2">
        <div>
          <p className="truncate text-sm font-medium">{user.email}</p>
          <p className="truncate text-xs text-muted-foreground">{user.id}</p>
        </div>
        <div className="flex gap-2">
          <Input
            placeholder="nome"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={
              !canMutate ||
              patchPending ||
              displayName === (user.display_name || "")
            }
            onClick={() => onPatch({ displayName })}
          >
            Salvar
          </Button>
        </div>
      </div>

      <div className="space-y-1">
        <RoleSelect
          value={role}
          onChange={(nextRole) => onPatch({ role: nextRole })}
          disabled={!canMutate || patchPending}
        />
        {!isBaseRole(user.role) && (
          <p className="text-xs text-muted-foreground">
            Papel legado: {user.role}
          </p>
        )}
      </div>

      <Button
        type="button"
        size="sm"
        variant={user.active ? "outline" : "default"}
        disabled={!canMutate || patchPending}
        onClick={() => onPatch({ active: !user.active })}
      >
        {user.active ? "Desativar" : "Ativar"}
      </Button>

      <div className="flex gap-2">
        <Input
          type="password"
          placeholder="nova senha"
          value={resetPassword}
          disabled={!canMutate}
          onChange={(event) => onResetPasswordChange(event.target.value)}
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!canMutate || resetPending || resetPassword.length < 8}
          onClick={onReset}
        >
          <KeyRound className="mr-1 h-4 w-4" />
          Reset
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!canMutate || revokeSessionsPending}
          onClick={onRevokeSessions}
        >
          Sessões
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onSelectMemberships}
        >
          Acessos
        </Button>
      </div>
    </div>
  );
}

function UserMembershipsPanel({
  selectedUser,
  memberships,
  isLoading,
  error,
  deletePending,
  deleteError,
  canDeleteProjectMembership,
  onDeleteProjectMembership,
}: {
  selectedUser?: AdminUser;
  memberships: OrgMembership[];
  isLoading: boolean;
  error: unknown;
  deletePending: boolean;
  deleteError: unknown;
  canDeleteProjectMembership: boolean;
  onDeleteProjectMembership: (membership: OrgMembership) => void;
}) {
  return (
    <section className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-4 py-3">
        <h3 className="font-medium">Acessos do usuário</h3>
        <p className="text-xs text-muted-foreground">
          {selectedUser
            ? `${selectedUser.display_name || selectedUser.email} · vínculos visíveis no seu escopo`
            : "Selecione um usuário na lista para ver grupos/projetos vinculados."}
        </p>
      </div>

      {!selectedUser ? (
        <p className="p-4 text-sm text-muted-foreground">
          Nenhum usuário selecionado.
        </p>
      ) : isLoading ? (
        <p className="p-4 text-sm text-muted-foreground">
          A carregar vínculos...
        </p>
      ) : error ? (
        <p className="p-4 text-sm text-destructive">
          {(error as Error).message}
        </p>
      ) : memberships.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">
          Este usuário não possui vínculos visíveis.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {memberships.map((membership) => (
            <li
              key={membership.id}
              className="grid gap-3 px-4 py-3 text-sm md:grid-cols-[160px_minmax(0,1fr)_140px_120px] md:items-center"
            >
              <span>{membership.scope_type}</span>
              <span className="truncate font-mono text-xs text-muted-foreground">
                {membership.scope_id}
              </span>
              <span className="font-medium">{membership.role}</span>
              {membership.scope_type === "project" ? (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={!canDeleteProjectMembership || deletePending}
                  onClick={() => onDeleteProjectMembership(membership)}
                >
                  Remover
                </Button>
              ) : (
                <span className="text-xs text-muted-foreground">
                  Somente leitura
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {deleteError && (
        <p className="px-4 py-3 text-xs text-destructive">
          {(deleteError as Error).message}
        </p>
      )}
    </section>
  );
}

function isBaseRole(role: string): role is BaseRole {
  return (
    role === "admin" ||
    role === "lead" ||
    role === "developer" ||
    role === "auditor"
  );
}

function RoleSelect({
  value,
  onChange,
  disabled,
}: {
  value: BaseRole;
  onChange: (role: BaseRole) => void;
  disabled?: boolean;
}) {
  return (
    <select
      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value as BaseRole)}
    >
      <option value="developer">developer</option>
      <option value="lead">lead</option>
      <option value="auditor">auditor</option>
      <option value="admin">admin</option>
    </select>
  );
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 text-2xl font-semibold">{value}</p>
    </div>
  );
}
