import { createServerFn } from "@tanstack/react-start";
import { getCookie, setCookie } from "@tanstack/react-start/server";
import { orchestratorJson } from "../api/orchestrator";

type RefreshResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

export const refresh = createServerFn({ method: "POST" }).handler(async () => {
  const currentRefresh = getCookie("central_refresh_token");
  if (!currentRefresh) {
    throw new Error("Sem refresh token — faça login novamente.");
  }

  const body = await orchestratorJson<RefreshResponse>("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: currentRefresh }),
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

  return { ok: true };
});
