import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useRouter } from "@tanstack/react-router";
import { Loader2, Shield, LogIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useAuth } from "@/lib/auth/client";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { fetchAuthPublicConfig } from "@/lib/auth/oidc";
import { toast } from "sonner";

const loginSchema = z.object({
  email: z.string().email("Email inválido"),
  password: z.string().min(1, "Palavra-passe obrigatória"),
});

type LoginForm = z.infer<typeof loginSchema>;

type OidcPublic = {
  authorization_endpoint?: string;
  client_id?: string;
  scopes?: string;
  redirect_uri?: string;
};

const ADMIN_ORIGIN = import.meta.env.VITE_ADMIN_ORIGIN?.replace(/\/+$/, "");

function generatePKCE() {
  const array = new Uint8Array(32);
  crypto.getRandomValues(array);
  const verifier = btoa(String.fromCharCode(...array))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  const encoder = new TextEncoder();
  const data = encoder.encode(verifier);
  return crypto.subtle.digest("SHA-256", data).then((hash) => {
    const challenge = btoa(String.fromCharCode(...new Uint8Array(hash)))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    return { verifier, challenge };
  });
}

export function LoginPage() {
  const [busy, setBusy] = useState(false);
  const [oidcEnabled, setOidcEnabled] = useState(false);
  const [oidcConfig, setOidcConfig] = useState<OidcPublic | null>(null);
  const { login } = useAuth();
  const router = useRouter();

  useEffect(() => {
    fetchAuthPublicConfig()
      .then((cfg) => {
        const enabled = Boolean(
          cfg.auth_oidc_enabled && cfg.oidc?.authorization_endpoint,
        );
        setOidcEnabled(enabled);
        setOidcConfig(enabled ? (cfg.oidc ?? null) : null);
      })
      .catch(() => {
        setOidcEnabled(false);
        setOidcConfig(null);
      });
  }, []);

  const form = useForm<LoginForm>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });

  async function onSubmit(data: LoginForm) {
    setBusy(true);
    try {
      const result = await login(data.email, data.password);
      await router.navigate({
        to: result.mustChangePassword ? "/change-password" : "/dashboard",
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Falha no login.";
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  async function handleOidcLogin() {
    if (!oidcConfig?.authorization_endpoint || !oidcConfig.client_id) {
      toast.error("SSO não configurado no servidor.");
      return;
    }
    setBusy(true);
    try {
      const { verifier, challenge } = await generatePKCE();
      sessionStorage.setItem("oidc_code_verifier", verifier);
      const redirectUri =
        oidcConfig.redirect_uri ||
        `${ADMIN_ORIGIN || window.location.origin}/oidc-callback`;
      sessionStorage.setItem("oidc_redirect", redirectUri);

      const scope = oidcConfig.scopes || "openid profile email";
      const authUrl =
        `${oidcConfig.authorization_endpoint}?` +
        `client_id=${encodeURIComponent(oidcConfig.client_id)}` +
        `&redirect_uri=${encodeURIComponent(redirectUri)}` +
        `&response_type=code` +
        `&scope=${encodeURIComponent(scope)}` +
        `&code_challenge=${challenge}` +
        `&code_challenge_method=S256`;

      window.location.href = authUrl;
    } catch {
      toast.error("Falha ao iniciar SSO.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-background p-4">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Shield className="h-6 w-6 text-primary" />
          </div>
          <CardTitle>Central</CardTitle>
          <CardDescription>
            Dashboard de supervisão — inicie sessão
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {oidcEnabled && (
            <Button
              type="button"
              variant="outline"
              className="w-full"
              disabled={busy}
              onClick={handleOidcLogin}
            >
              {busy ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <LogIn className="mr-2 h-4 w-4" />
              )}
              Entrar com SSO
            </Button>
          )}

          {oidcEnabled && (
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <span className="w-full border-t border-border" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">ou</span>
              </div>
            </div>
          )}

          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                disabled={busy}
                {...form.register("email")}
              />
              {form.formState.errors.email && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.email.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Palavra-passe</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                disabled={busy}
                {...form.register("password")}
              />
              {form.formState.errors.password && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.password.message}
                </p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Entrar
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
