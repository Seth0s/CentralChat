import { createFileRoute, useRouter } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { oidcExchange } from "@/lib/auth/oidc";

export const Route = createFileRoute("/oidc-callback")({
  component: OidcCallback,
});

function OidcCallback() {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const errorParam = params.get("error");

    if (errorParam) {
      setError(`SSO falhou: ${errorParam}`);
      return;
    }

    if (!code) {
      setError("Código de autorização em falta.");
      return;
    }

    const verifier = sessionStorage.getItem("oidc_code_verifier");
    const redirectUri = sessionStorage.getItem("oidc_redirect") ||
      window.location.origin + "/oidc-callback";

    if (!verifier) {
      setError("Sessão PKCE expirada. Tente novamente.");
      return;
    }

    sessionStorage.removeItem("oidc_code_verifier");
    sessionStorage.removeItem("oidc_redirect");

    oidcExchange({ data: { code, code_verifier: verifier, redirect_uri: redirectUri } })
      .then(() => router.navigate({ to: "/" }))
      .catch((err) => setError(err instanceof Error ? err.message : "Falha na troca OIDC."));
  }, [router]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="max-w-sm text-center">
          <p className="text-sm text-destructive">{error}</p>
          <button
            onClick={() => router.navigate({ to: "/login" })}
            className="mt-4 text-sm text-primary hover:underline"
          >
            Voltar ao login
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="flex flex-col items-center gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">A autenticar via SSO…</p>
      </div>
    </div>
  );
}
