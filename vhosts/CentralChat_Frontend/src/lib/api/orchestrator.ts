/**
 * Server-side fetch to orchestrator. Injects JWT from httpOnly cookie.
 * Uses TanStack Start native cookie helpers.
 */
import { getCookie, setCookie } from "@tanstack/react-start/server";

const ORCH_URL = process.env.VITE_ORCHESTRATOR_PROXY_TARGET || "http://localhost:8004";

type ProblemDetails = {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string;
  errors?: { loc?: (string | number)[]; msg: string; type?: string }[];
};

export class OrchestratorError extends Error {
  status: number;
  type: string;
  errors?: ProblemDetails["errors"];

  constructor(pd: ProblemDetails) {
    super(pd.detail || pd.title);
    this.name = "OrchestratorError";
    this.status = pd.status;
    this.type = pd.type;
    this.errors = pd.errors;
  }
}

export class AuthError extends Error {
  constructor(message = "Sessao expirada — faca login novamente.") {
    super(message);
    this.name = "AuthError";
  }
}

async function refreshAndSetCookie(): Promise<string | null> {
  const refreshToken = getCookie("central_refresh_token");
  if (!refreshToken) {
    // No refresh token → session is dead
    throw new AuthError();
  }
  const res = await fetch(`${ORCH_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    // Refresh failed — session is dead
    throw new AuthError();
  }
  const body = await res.json();
  setCookie("central_access_token", body.access_token, {
    httpOnly: true, secure: process.env.NODE_ENV === "production",
    sameSite: "strict", path: "/", maxAge: body.expires_in || 1800,
  });
  if (body.refresh_token) {
    setCookie("central_refresh_token", body.refresh_token, {
      httpOnly: true, secure: process.env.NODE_ENV === "production",
      sameSite: "strict", path: "/", maxAge: 604800,
    });
  }
  return body.access_token;
}

export async function orchestratorJson<T = unknown>(
  path: string,
  options?: RequestInit & { skipAuth?: boolean },
): Promise<T> {
  const { skipAuth, ...fetchOptions } = options || {};

  const headers = new Headers(fetchOptions.headers);
  headers.set("Content-Type", headers.get("Content-Type") || "application/json");

  if (!skipAuth) {
    let token = getCookie("central_access_token");
    if (!token) token = await refreshAndSetCookie();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  let res = await fetch(`${ORCH_URL}${path}`, { ...fetchOptions, headers });

  if (res.status === 401 && !skipAuth) {
    try {
      const newToken = await refreshAndSetCookie();
      if (newToken) {
        headers.set("Authorization", `Bearer ${newToken}`);
        res = await fetch(`${ORCH_URL}${path}`, { ...fetchOptions, headers });
      }
    } catch (_authErr) {
      throw new AuthError();
    }
  }

  const body = await res.json();
  if (!res.ok) throw new OrchestratorError(body as ProblemDetails);
  return body as T;
}
