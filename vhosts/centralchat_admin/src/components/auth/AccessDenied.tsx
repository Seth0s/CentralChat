import { Link } from "@tanstack/react-router";
import { ShieldAlert } from "lucide-react";

export function AccessDenied({ role }: { role: string | null | undefined }) {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <section className="max-w-lg rounded-lg border border-border bg-card p-6 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-secondary">
          <ShieldAlert className="h-6 w-6 text-muted-foreground" />
        </div>
        <h2 className="mt-4 text-lg font-semibold">Acesso restrito</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Seu papel atual ({role || "desconhecido"}) não tem permissão para ver
          esta área do painel.
        </p>
        <Link
          to="/dashboard"
          className="mt-5 inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Voltar ao dashboard
        </Link>
      </section>
    </div>
  );
}
