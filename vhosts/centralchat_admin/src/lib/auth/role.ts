import { createServerFn } from "@tanstack/react-start";
import { validateSession } from "../auth/session";

export const fetchSessionRole = createServerFn({ method: "GET" }).handler(async () => {
  const s = await validateSession();
  if (!s.valid) return { role: null, sub: null, clientId: null };
  const session = s as { role?: string; sub?: string; clientId?: string };
  return {
    role: session.role ?? null,
    sub: session.sub ?? "",
    clientId: session.clientId ?? "",
  };
});
