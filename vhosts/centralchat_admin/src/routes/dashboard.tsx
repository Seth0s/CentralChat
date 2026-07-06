import {
  createFileRoute,
  Link,
  Outlet,
  useRouterState,
} from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bot,
  BookOpen,
  ChevronDown,
  Cpu,
  FolderTree,
  KeyRound,
  Kanban,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  ScrollText,
  Settings,
  Shield,
  ShieldCheck,
  Sparkles,
  Terminal,
  Users,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AccessDenied } from "@/components/auth/AccessDenied";
import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { useAuth } from "@/lib/auth/client";
import { fetchSessionRole } from "@/lib/auth/role";
import {
  canAccessDashboardPath,
  type DashboardPath,
} from "@/lib/auth/permissions";

export const Route = createFileRoute("/dashboard")({
  component: DashboardLayout,
});

type NavItem = {
  label: string;
  to: DashboardPath;
  icon: typeof LayoutDashboard;
  exact?: boolean;
};

type NavGroup = {
  id: string;
  label: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    id: "overview",
    label: "Visão geral",
    items: [
      {
        label: "Dashboard",
        to: "/dashboard",
        icon: LayoutDashboard,
        exact: true,
      },
    ],
  },
  {
    id: "work",
    label: "Trabalho",
    items: [
      { label: "Fila", to: "/dashboard/queue", icon: Kanban },
      { label: "Sessões", to: "/dashboard/sessions", icon: MessageSquare },
      { label: "Solicitações", to: "/dashboard/requests", icon: ShieldCheck },
      { label: "Approvals (legado)", to: "/dashboard/approvals", icon: Shield },
    ],
  },
  {
    id: "organization",
    label: "Organização",
    items: [
      { label: "Usuários", to: "/dashboard/users", icon: Users },
      {
        label: "Árvore organizacional",
        to: "/dashboard/org",
        icon: FolderTree,
      },
    ],
  },
  {
    id: "agents",
    label: "Agentes",
    items: [
      { label: "Agentes", to: "/dashboard/agents", icon: Bot },
      { label: "Skills", to: "/dashboard/skills", icon: Sparkles },
      { label: "Regras", to: "/dashboard/rules", icon: BookOpen },
      { label: "Policies", to: "/dashboard/policies", icon: Shield },
    ],
  },
  {
    id: "governance",
    label: "Governança",
    items: [
      { label: "Auditoria", to: "/dashboard/audit", icon: ScrollText },
      { label: "Compliance", to: "/dashboard/compliance", icon: Shield },
      { label: "Custo", to: "/dashboard/usage", icon: BarChart3 },
    ],
  },
  {
    id: "settings",
    label: "Configurações",
    items: [
      { label: "Segredos", to: "/dashboard/settings/secrets", icon: KeyRound },
      { label: "Inferência", to: "/dashboard/settings/inference", icon: Cpu },
      { label: "Operação", to: "/dashboard/settings/ops", icon: Activity },
    ],
  },
];

function DashboardLayout() {
  const { logout } = useAuth();
  const { data: roleData, isLoading: roleLoading } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  });
  const role = roleData?.role ?? null;
  const visibleGroups = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        ...group,
        items: group.items.filter((item) =>
          canAccessDashboardPath(item.to, role),
        ),
      })).filter((group) => group.items.length > 0),
    [role],
  );
  const currentPath = useMemo(() => resolveDashboardPath(pathname), [pathname]);
  const canAccessCurrentPath =
    roleLoading || canAccessDashboardPath(currentPath, role);
  const activeGroupIds = useMemo(
    () =>
      visibleGroups
        .filter((group) =>
          group.items.some((item) =>
            item.exact ? pathname === item.to : pathname.startsWith(item.to),
          ),
        )
        .map((group) => group.id),
    [pathname, visibleGroups],
  );
  const [openGroups, setOpenGroups] = useState<Set<string>>(
    () => new Set(["overview", "work"]),
  );

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem("central-admin-nav-open");
      if (raw) {
        const saved = JSON.parse(raw);
        if (Array.isArray(saved)) setOpenGroups(new Set(saved.map(String)));
      }
    } catch {
      // Ignore invalid persisted UI state.
    }
  }, []);

  useEffect(() => {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      for (const id of activeGroupIds) next.add(id);
      return next;
    });
  }, [activeGroupIds]);

  const toggleGroup = (id: string) => {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        window.localStorage.setItem(
          "central-admin-nav-open",
          JSON.stringify([...next]),
        );
      } catch {
        // Local storage is an enhancement only.
      }
      return next;
    });
  };

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-card p-4">
        <div className="mb-6">
          <h1 className="text-lg font-semibold tracking-tight">
            Central Admin
          </h1>
          <p className="text-xs text-muted-foreground">
            Organização · governança · operação
          </p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 text-sm">
          {visibleGroups.map((group) => {
            const isOpen = openGroups.has(group.id);
            return (
              <section key={group.id} className="space-y-1">
                <button
                  type="button"
                  onClick={() => toggleGroup(group.id)}
                  className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:bg-secondary hover:text-foreground"
                >
                  {group.label}
                  <ChevronDown
                    className={`h-3.5 w-3.5 transition-transform ${isOpen ? "rotate-180" : ""}`}
                  />
                </button>
                {isOpen && (
                  <div className="space-y-1 pl-2">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      return (
                        <Link
                          key={item.to}
                          to={item.to}
                          className="flex items-center gap-2 rounded-md px-3 py-2 hover:bg-secondary [&.active]:bg-secondary"
                          activeOptions={{ exact: item.exact }}
                        >
                          <Icon className="h-4 w-4" />
                          {item.label}
                        </Link>
                      );
                    })}
                  </div>
                )}
              </section>
            );
          })}
        </nav>
        <button
          type="button"
          onClick={() => logout()}
          className="mt-auto inline-flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <LogOut className="h-4 w-4" /> Sair
        </button>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-border px-6 text-sm text-muted-foreground">
          <div className="flex min-w-0 items-center">
            <Terminal className="mr-2 h-4 w-4 shrink-0" />
            <span className="truncate">
              Admin web para governança. Fluxo diário:{" "}
              <code className="mx-1 rounded bg-secondary px-1.5 py-0.5 text-foreground">
                central
              </code>
            </span>
          </div>
          <ThemeToggle />
        </header>
        <div className="flex-1 overflow-auto p-6">
          {canAccessCurrentPath ? <Outlet /> : <AccessDenied role={role} />}
        </div>
      </main>
    </div>
  );
}

function resolveDashboardPath(pathname: string): DashboardPath {
  const matches = Object.keys({
    "/dashboard/approvals": true,
    "/dashboard/requests": true,
    "/dashboard/sessions": true,
    "/dashboard/rules": true,
    "/dashboard/agents": true,
    "/dashboard/skills": true,
    "/dashboard/policies": true,
    "/dashboard/queue": true,
    "/dashboard/audit": true,
    "/dashboard/usage": true,
    "/dashboard/compliance": true,
    "/dashboard/inference": true,
    "/dashboard/settings/secrets": true,
    "/dashboard/settings/inference": true,
    "/dashboard/settings/ops": true,
    "/dashboard/org": true,
    "/dashboard/users": true,
  } satisfies Partial<Record<DashboardPath, true>>) as DashboardPath[];
  return (
    matches.find(
      (path) => pathname === path || pathname.startsWith(`${path}/`),
    ) ?? "/dashboard"
  );
}
