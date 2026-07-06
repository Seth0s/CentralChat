import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { listSessions } from "@/lib/api/sessions";

export const Route = createFileRoute("/dashboard/sessions")({
  component: SessionsPage,
});

function SessionsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["sessions"],
    queryFn: () => listSessions(),
  });

  const sessions = data?.sessions ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold">Sessões</h2>
        <p className="text-sm text-muted-foreground">
          Supervisão, partilha ACL e audit. Chat interactivo:{" "}
          <code className="rounded bg-secondary px-1">central tui</code>.
        </p>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">A carregar…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}

      {sessions.length === 0 && !isLoading ? (
        <p className="text-sm text-muted-foreground">Sem sessões.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-2 pr-4">Título</th>
              <th className="py-2 pr-4">ID</th>
              <th className="py-2 pr-4">Mensagens</th>
              <th className="py-2 pr-4">Actualizado</th>
              <th className="py-2">Detalhe</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((s) => (
              <tr key={s.id} className="border-b border-border/60">
                <td className="py-2 pr-4 font-medium">{s.title}</td>
                <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">{s.id}</td>
                <td className="py-2 pr-4">{s.message_count ?? "—"}</td>
                <td className="py-2 text-muted-foreground">{s.updated_at}</td>
                <td className="py-2">
                  <Link
                    to="/dashboard/sessions/$sessionId"
                    params={{ sessionId: s.id }}
                    className="text-primary hover:underline"
                  >
                    Abrir
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
