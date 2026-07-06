import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useRouter } from "@tanstack/react-router";
import { KeyRound, Loader2 } from "lucide-react";
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
import { changePassword } from "@/lib/auth/change-password";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { toast } from "sonner";

const schema = z
  .object({
    currentPassword: z.string().min(1, "Palavra-passe actual obrigatória"),
    newPassword: z.string().min(8, "Mínimo 8 caracteres"),
    confirmPassword: z.string().min(8, "Confirme a nova palavra-passe"),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: "As palavras-passe não coincidem",
    path: ["confirmPassword"],
  });

type ChangePasswordForm = z.infer<typeof schema>;

export function ChangePasswordPage() {
  const [busy, setBusy] = useState(false);
  const router = useRouter();

  const form = useForm<ChangePasswordForm>({
    resolver: zodResolver(schema),
    defaultValues: {
      currentPassword: "",
      newPassword: "",
      confirmPassword: "",
    },
  });

  async function onSubmit(data: ChangePasswordForm) {
    setBusy(true);
    try {
      await changePassword({ data });
      toast.success("Palavra-passe actualizada. Bem-vindo ao Central.");
      await router.invalidate();
      await router.navigate({ to: "/dashboard" });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Não foi possível alterar a palavra-passe.";
      toast.error(message);
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
            <KeyRound className="h-6 w-6 text-primary" />
          </div>
          <CardTitle>Defina a sua palavra-passe</CardTitle>
          <CardDescription>
            Por segurança, deve alterar a palavra-passe inicial antes de usar o
            painel.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="currentPassword">Palavra-passe actual</Label>
              <Input
                id="currentPassword"
                type="password"
                autoComplete="current-password"
                disabled={busy}
                {...form.register("currentPassword")}
              />
              {form.formState.errors.currentPassword && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.currentPassword.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="newPassword">Nova palavra-passe</Label>
              <Input
                id="newPassword"
                type="password"
                autoComplete="new-password"
                disabled={busy}
                {...form.register("newPassword")}
              />
              {form.formState.errors.newPassword && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.newPassword.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirmPassword">Confirmar nova palavra-passe</Label>
              <Input
                id="confirmPassword"
                type="password"
                autoComplete="new-password"
                disabled={busy}
                {...form.register("confirmPassword")}
              />
              {form.formState.errors.confirmPassword && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.confirmPassword.message}
                </p>
              )}
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Guardar e continuar
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
