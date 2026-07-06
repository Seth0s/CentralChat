/**
 * Client-side auth helpers (safe to ship to browser — no token access).
 */
import { useRouter } from "@tanstack/react-router";
import { login as loginFn } from "./login";
import { refresh as refreshFn } from "./refresh";
import { logout as logoutFn } from "./session";

export function useAuth() {
  const router = useRouter();

  async function login(email: string, password: string) {
    const result = await loginFn({ data: { email, password } });
    if (!result.ok) throw new Error("Falha no login");
    await router.invalidate();
  }

  async function refresh() {
    await refreshFn();
  }

  async function logout() {
    await logoutFn();
    await router.invalidate();
    window.location.href = "/login";
  }

  return { login, refresh, logout };
}

/** Check if user is authenticated (for route guards). */
export async function isAuthenticated(): Promise<boolean> {
  try {
    // Import dynamically to avoid bundling server code on client
    const { validateSession } = await import("./session");
    const result = await validateSession();
    return result.valid;
  } catch {
    return false;
  }
}
