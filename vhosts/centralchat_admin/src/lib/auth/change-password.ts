import { createServerFn } from "@tanstack/react-start";
import { setCookie } from "@tanstack/react-start/server";
import { z } from "zod";
import { orchestratorJson } from "../api/orchestrator";

const changePasswordSchema = z
  .object({
    currentPassword: z.string().min(1, "Palavra-passe actual obrigatória"),
    newPassword: z.string().min(8, "Mínimo 8 caracteres"),
    confirmPassword: z.string().min(8, "Confirme a nova palavra-passe"),
  })
  .refine((data) => data.newPassword === data.confirmPassword, {
    message: "As palavras-passe não coincidem",
    path: ["confirmPassword"],
  });

type ChangePasswordInput = z.infer<typeof changePasswordSchema>;

type ChangePasswordResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  must_change_password?: boolean;
};

export const changePassword = createServerFn({ method: "POST" })
  .inputValidator(changePasswordSchema)
  .handler(async ({ data }: { data: ChangePasswordInput }) => {
    const body = await orchestratorJson<ChangePasswordResponse>(
      "/auth/change-password",
      {
        method: "POST",
        body: JSON.stringify({
          current_password: data.currentPassword,
          new_password: data.newPassword,
        }),
      },
    );

    setCookie("central_access_token", body.access_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
      maxAge: body.expires_in,
    });

    setCookie("central_refresh_token", body.refresh_token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
      maxAge: 604800,
    });

    return { ok: true, mustChangePassword: Boolean(body.must_change_password) };
  });
