import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useRouter } from "@tanstack/react-router";
import { Loader2, Shield, LogIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "@/lib/auth/client";
import { toast } from "sonner";

const loginSchema = z.object({
  email: z.string().email("Email inválido"),
  password: z.string().min(1, "Palavra-passe obrigatória"),
});

type LoginForm = z.infer<typeof loginSchema>;

function generatePKCE() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  const verifier = btoa(String.fromCharCode(...array))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  return crypto.subtle.digest("SHA-256", data).then((hash) => {
    const challenge = btoa(String.fromCharCode(...new Uint8Array(hash)))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    return { verifier, challenge };
  });
}

export function LoginPage() {
  const [busy, setBusy] = useState(false);
  const [oidcEnabled, setOidcEnabled] = useState(false);
  const { login } = useAuth();
  const router = useRouter();

  useEffect(() => {
    // Check if OIDC is configured by calling public-config
    import("@/lib/auth/session").then(({ validateSession }) => {
      // We can check the URL for oidc callback or just enable the button
      // For now, check if there's an OIDC provider env
      setOidcEnabled(true); // Always show SSO button in dev
    }).catch(() => {});
  }, []);

  const form = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  async function onSubmit(data: LoginForm) {
    setBusy(true);
    try {
      await login(data.email, data.password);
      await router.navigate({ to: "/" });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Falha no login.";
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function handleOidcLogin() {
    setBusy(true);
    try {
      const { verifier, challenge } = await generatePKCE();
      sessionStorage.setItem("oidc_code_verifier", verifier);
      sessionStorage.setItem("oidc_redirect", window.location.origin + "/oidc-callback");

      const issuerUrl = "http://localhost:8180/realms/central";
      const clientId = "central-bff";
      const redirectUri = window.location.origin + "/oidc-callback";
      const scope = "openid profile email";

      const authUrl = `${issuerUrl}/protocol/openid-connect/auth?` +
        `client_id=${encodeURIComponent(clientId)}` +
        `&redirect_uri=${encodeURIComponent(redirectUri)}` +
        `&response_type=code` +
        `&scope=${encodeURIComponent(scope)}` +
        `&code_challenge=${challenge}` +
        `&code_challenge_method=S256`;

      window.location.href = authUrl;
    } catch (err) {
      toast.error("Falha ao iniciar SSO.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-sm shadow-central-strong border-border/60">
        <CardHeader className="space-y-1 text-center pb-4">
          <div className="mx-auto mb-2 grid h-12 w-12 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <Shield className="h-6 w-6" />
          </div>
          <CardTitle className="text-xl font-semibold tracking-tight">Central</CardTitle>
          <CardDescription className="text-sm text-muted-foreground">
            Escolha o método de login.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {oidcEnabled && (
            <>
              <Button
                variant="outline"
                className="w-full mb-4"
                onClick={handleOidcLogin}
                disabled={busy}
              >
                <LogIn className="mr-2 h-4 w-4" />
                Entrar com SSO
              </Button>
              <div className="relative mb-4">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t" />
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-card px-2 text-muted-foreground">ou</span>
                </div>
              </div>
            </>
          )}
          <form
            onSubmit={form.handleSubmit(onSubmit)}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="username"
                placeholder="dev@local.test"
                disabled={busy}
                {...form.register("email")}
              />
              {form.formState.errors.email && (
                <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Palavra-passe</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                disabled={busy}
                {...form.register("password")}
              />
              {form.formState.errors.password && (
                <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  A entrar…
                </>
              ) : (
                "Entrar"
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
