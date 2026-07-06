/**
 * Server-side session management via httpOnly cookies.
 * Uses TanStack Start native cookie helpers (h3-based).
 */
import { createServerFn } from "@tanstack/react-start";
import { getCookie, setCookie, deleteCookie } from "@tanstack/react-start/server";

// ── Server function: validate session ──

export const validateSession = createServerFn({ method: "GET" }).handler(async () => {
  const access = getCookie("central_access_token");
  const refresh = getCookie("central_refresh_token");

  if (!access && !refresh) return { valid: false };

  let email = "";
  let clientId = "";

  if (access) {
    try {
      const payload = JSON.parse(
        Buffer.from(access.split(".")[1], "base64url").toString(),
      );
      const now = Math.floor(Date.now() / 1000);
      if (payload.exp && payload.exp >= now) {
        email = payload.email || payload.sub || "";
        clientId = payload.client_id || "";
        return { valid: true, sub: email, clientId, email };
      }
    } catch {}
  }

  if (refresh) return { valid: true, email: "", clientId: "" };
  return { valid: false };
});

// ── Server function: logout ──

export const logout = createServerFn({ method: "POST" }).handler(async () => {
  deleteCookie("central_access_token");
  deleteCookie("central_refresh_token");
  return { ok: true };
});
