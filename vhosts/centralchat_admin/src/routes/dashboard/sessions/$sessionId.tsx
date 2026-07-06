import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchSessionRole } from "@/lib/auth/role";
import { fetchAdminUsers } from "@/lib/api/users";
import {
  deleteSessionAcl,
  fetchSessionAcl,
  getAdminSession,
  upsertSessionAcl,
} from "@/lib/api/sessions";

export const Route = createFileRoute("/dashboard/sessions/$sessionId")({
  component: SessionDetailPage,
});

function SessionDetailPage() {
  const { sessionId } = Route.useParams();
  const qc = useQueryClient();
  const [principalType, setPrincipalType] = useState<"user" | "role">("user");
  const [principalId, setPrincipalId] = useState("");
  const [accessLevel, setAccessLevel] = useState<"read" | "write" | "admin">(
    "read",
  );

  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const canManageAcl =
    roleData?.role === "lead" || roleData?.role === "admin";

  const sessionQuery = useQuery({
    queryKey: ["admin-session", sessionId],
    queryFn: () => getAdminSession({ data: { id: sessionId } }),
  });
  const aclQuery = useQuery({
    queryKey: ["session-acl", sessionId],
    queryFn: () => fetchSessionAcl({ data: { sessionId } }),
    enabled: canManageAcl,
  });
  const usersQuery = useQuery({
    queryKey: ["admin-users"],
    queryFn: () => fetchAdminUsers({ data: { limit: 200 } }),
    enabled: canManageAcl,
  });

  const session = sessionQuery.data?.session;
  const users = usersQuery.data?.items ?? [];
  const userLabel = (id: string) =>
    users.find((u) => u.id === id)?.display_name ||
    users.find((u) => u.id === id)?.email ||
    id;

  const aclMut = useMutation({
    mutationFn: () =>
      upsertSessionAcl({
        data: {
          sessionId,
          principalType,
          principalId: principalId.trim(),
          accessLevel,
        },
      }),
    onSuccess: () => {
      toast.success("Acesso partilhado.");
      setPrincipalId("");
      qc.invalidateQueries({ queryKey: ["session-acl", sessionId] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const revokeMut = useMutation({
    mutationFn: (entry: {
      principalType: "user" | "role";
      principalId: string;
    }) =>
      deleteSessionAcl({
        data: { sessionId, ...entry },
      }),
    onSuccess: () => {
      toast.success("Acesso removido.");
      qc.invalidateQueries({ queryKey: ["session-acl", sessionId] });
    },
    onError: (error) => toast.error((error as Error).message),
  });

  if (sessionQuery.isLoading) {
    return <p className="text-sm text-muted-foreground">A carregar sessão…</p>;
  }
  if (sessionQuery.error) {
    return (
      <p className="text-sm text-destructive">
        {(sessionQuery.error as Error).message}
      </p>
    );
  }
  if (!session) {
    return <p className="text-sm text-muted-foreground">Sessão não encontrada.</p>;
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          to="/dashboard/sessions"
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          ← Sessões
        </Link>
        <h2 className="mt-1 text-xl font-semibold">{session.title}</h2>
        <p className="font-mono text-xs text-muted-foreground">{session.id}</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {session.message_count ?? session.messages?.length ?? 0} mensagens ·
          actualizado {session.updated_at}
        </p>
      </div>

      {canManageAcl && (
        <section className="rounded-lg border border-border p-4">
          <h3 className="font-medium">Partilha (ACL)</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Conceda acesso por utilizador ou papel. Leads e admins gerem a ACL;
            developers precisam de entrada explícita.
          </p>

          <div className="mt-4 grid gap-2 md:grid-cols-4">
            <select
              className="rounded border border-border bg-background px-2 py-2 text-sm"
              value={principalType}
              onChange={(e) =>
                setPrincipalType(e.target.value as "user" | "role")
              }
            >
              <option value="user">Utilizador</option>
              <option value="role">Papel</option>
            </select>
            {principalType === "user" ? (
              <select
                className="rounded border border-border bg-background px-2 py-2 text-sm md:col-span-2"
                value={principalId}
                onChange={(e) => setPrincipalId(e.target.value)}
              >
                <option value="">Seleccionar…</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.display_name || u.email}
                  </option>
                ))}
              </select>
            ) : (
              <Input
                value={principalId}
                onChange={(e) => setPrincipalId(e.target.value)}
                placeholder="developer, reviewer…"
                className="md:col-span-2"
              />
            )}
            <select
              className="rounded border border-border bg-background px-2 py-2 text-sm"
              value={accessLevel}
              onChange={(e) =>
                setAccessLevel(e.target.value as "read" | "write" | "admin")
              }
            >
              <option value="read">read</option>
              <option value="write">write</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <Button
            className="mt-3"
            size="sm"
            disabled={!principalId.trim() || aclMut.isPending}
            onClick={() => aclMut.mutate()}
          >
            Partilhar
          </Button>

          <table className="mt-6 w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th className="py-2 pr-4">Principal</th>
                <th className="py-2 pr-4">ID</th>
                <th className="py-2 pr-4">Nível</th>
                <th className="py-2">Acções</th>
              </tr>
            </thead>
            <tbody>
              {(aclQuery.data?.items ?? []).length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-3 text-muted-foreground">
                    Sem entradas ACL.
                  </td>
                </tr>
              ) : (
                (aclQuery.data?.items ?? []).map((entry) => (
                  <tr
                    key={`${entry.principal_type}:${entry.principal_id}`}
                    className="border-b border-border/60"
                  >
                    <td className="py-2 pr-4">{entry.principal_type}</td>
                    <td className="py-2 pr-4 font-mono text-xs">
                      {entry.principal_type === "user"
                        ? userLabel(entry.principal_id)
                        : entry.principal_id}
                    </td>
                    <td className="py-2 pr-4">{entry.access_level}</td>
                    <td className="py-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={revokeMut.isPending}
                        onClick={() =>
                          revokeMut.mutate({
                            principalType: entry.principal_type,
                            principalId: entry.principal_id,
                          })
                        }
                      >
                        Remover
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </section>
      )}

      {!canManageAcl && (
        <p className="text-sm text-muted-foreground">
          Apenas lead ou admin podem gerir a ACL desta sessão.
        </p>
      )}
    </div>
  );
}
