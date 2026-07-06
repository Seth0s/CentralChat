import { createFileRoute, Link } from "@tanstack/react-router";
import { Terminal } from "lucide-react";

export const Route = createFileRoute("/dashboard/")({
  component: DashboardHome,
});

function DashboardHome() {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Dashboard</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          A web é para supervisão, approvals grandes e audit. O fluxo diário de desenvolvimento corre no CLI.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-card p-5">
        <div className="flex items-start gap-3">
          <Terminal className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          <div>
            <h3 className="font-medium">Usa o terminal</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Sessão interactiva, chat e approvals no mesmo ecrã:
            </p>
            <pre className="mt-3 overflow-x-auto rounded-md bg-secondary p-3 text-xs">
{`central login
central workspace .
central          # abre TUI Surface
central daemon   # executor local (outro terminal)`}
            </pre>
          </div>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          to="/dashboard/approvals"
          className="rounded-lg border border-border p-4 transition-colors hover:bg-secondary"
        >
          <h3 className="font-medium">Approvals</h3>
          <p className="mt-1 text-sm text-muted-foreground">Diffs grandes e revisão side-by-side</p>
        </Link>
        <Link
          to="/dashboard/sessions"
          className="rounded-lg border border-border p-4 transition-colors hover:bg-secondary"
        >
          <h3 className="font-medium">Sessões</h3>
          <p className="mt-1 text-sm text-muted-foreground">Audit readonly das conversas da equipa</p>
        </Link>
      </div>
    </div>
  );
}
