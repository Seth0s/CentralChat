/**
 * Server-side session management via httpOnly cookies.
 * Uses TanStack Start native cookie helpers (h3-based).
 */
import { createServerFn } from "@tanstack/react-start";
import {
  getCookie,
  setCookie,
  deleteCookie,
} from "@tanstack/react-start/server";
import { orchestratorJson } from "../api/orchestrator";

const ORCH_URL =
  process.env.VITE_ORCHESTRATOR_PROXY_TARGET || "http://localhost:8004";

function adminOrigin() {
  return (
    process.env.VITE_ADMIN_ORIGIN ||
    process.env.VITE_APP_ORIGIN ||
    "http://localhost:5174"
  ).replace(/\/+$/, "");
}

type AuthPublicConfig = {
  auth_oidc_enabled?: boolean;
  oidc?: {
    client_id?: string;
    end_session_endpoint?: string;
  };
};

// ── Server function: validate session ──

export const validateSession = createServerFn({ method: "GET" }).handler(
  async () => {
    const access = getCookie("central_access_token");
    const refresh = getCookie("central_refresh_token");

    if (!access && !refresh) return { valid: false };

    if (access) {
      try {
        const payload = JSON.parse(
          Buffer.from(access.split(".")[1], "base64url").toString(),
        );
        const now = Math.floor(Date.now() / 1000);
        if (payload.exp && payload.exp >= now) {
          const sub = payload.sub || "";
          const email = payload.email || "";
          const displayName = payload.display_name || "";
          const clientId = payload.client_id || "";
          return {
            valid: true,
            sub,
            email,
            displayName,
            clientId,
            role: payload.role || null,
            mustChangePassword: Boolean(payload.must_change_password),
          };
        }
      } catch {
        // Invalid JWT payloads are treated as unauthenticated sessions.
      }
    }

    return { valid: false };
  },
);

// ── Server function: logout ──

export const logout = createServerFn({ method: "POST" }).handler(async () => {
  const refresh = getCookie("central_refresh_token");
  if (refresh) {
    try {
      await fetch(`${ORCH_URL}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
    } catch {
      // Logout must still clear local cookies if the backend is unavailable.
    }
  }

  let idpLogoutUrl: string | null = null;
  try {
    const cfg = await orchestratorJson<AuthPublicConfig>(
      "/auth/public-config",
      { skipAuth: true },
    );
    const end = cfg.oidc?.end_session_endpoint;
    const clientId = cfg.oidc?.client_id;
    if (cfg.auth_oidc_enabled && end && clientId) {
      const postLogout = `${adminOrigin()}/login`;
      idpLogoutUrl =
        `${end}?client_id=${encodeURIComponent(clientId)}` +
        `&post_logout_redirect_uri=${encodeURIComponent(postLogout)}`;
    }
  } catch {
    // IdP logout is best-effort; local logout remains authoritative.
  }

  deleteCookie("central_access_token");
  deleteCookie("central_refresh_token");
  return { ok: true, idpLogoutUrl };
});
