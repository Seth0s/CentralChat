/**
 * OIDC login — server function.
 */
import { createServerFn } from "@tanstack/react-start";
import { setCookie } from "@tanstack/react-start/server";
import { orchestratorJson } from "../api/orchestrator";

type OidcExchangeResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

export const oidcExchange = createServerFn({ method: "POST" })
  .handler(async ({ data }: { data: { code: string; code_verifier: string; redirect_uri: string } }) => {
    const body = await orchestratorJson<OidcExchangeResponse>("/auth/oidc/exchange", {
      method: "POST",
      body: JSON.stringify(data),
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
