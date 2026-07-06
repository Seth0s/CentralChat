import { createServerFn } from "@tanstack/react-start";
import { setCookie } from "@tanstack/react-start/server";
import { z } from "zod";
import { orchestratorJson } from "../api/orchestrator";

const loginSchema = z.object({
  email: z.string().email("Email inválido"),
  password: z.string().min(1, "Palavra-passe obrigatória"),
});

type LoginInput = z.infer<typeof loginSchema>;

type LoginResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  must_change_password?: boolean;
};

export const login = createServerFn({ method: "POST" })
  .inputValidator(loginSchema)
  .handler(async ({ data }: { data: LoginInput }) => {
    const body = await orchestratorJson<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email: data.email, password: data.password }),
      skipAuth: true,
    });

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

    return {
      ok: true,
      mustChangePassword: Boolean(body.must_change_password),
    };
  });
