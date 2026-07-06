import { useState } from "react";
import {
  PanelLeftClose, PanelLeftOpen, Plus, MessageSquare,
  Pencil, Trash2, Search, Settings, Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChatSession } from "@/lib/api/sessions";
import { deleteSession, updateSession } from "@/lib/api/sessions";

type SessionGroup = { label: string; items: ChatSession[] };

function groupByDate(sessions: ChatSession[]): SessionGroup[] {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const weekAgo = new Date(today.getTime() - 7 * 86400000);

  const todayItems: ChatSession[] = [];
  const yesterdayItems: ChatSession[] = [];
  const weekItems: ChatSession[] = [];
  const olderItems: ChatSession[] = [];

  for (const s of sessions) {
    const d = new Date(s.created_at);
    if (d >= today) todayItems.push(s);
    else if (d >= yesterday) yesterdayItems.push(s);
    else if (d >= weekAgo) weekItems.push(s);
    else olderItems.push(s);
  }

  const groups: SessionGroup[] = [];
  if (todayItems.length) groups.push({ label: "Hoje", items: todayItems });
  if (yesterdayItems.length) groups.push({ label: "Ontem", items: yesterdayItems });
  if (weekItems.length) groups.push({ label: "Últimos 7 dias", items: weekItems });
  if (olderItems.length) groups.push({ label: "Mais antigo", items: olderItems });
  return groups;
}

export function Sidebar({
  collapsed, onToggle, activeId, onSelect,
  sessions, loading, onNewSession, onOpenSettings,
  onSessionsChanged, userEmail,
}: {
  collapsed: boolean;
  onToggle: () => void;
  activeId: string | null;
  onSelect: (id: string, title: string) => void;
  sessions: ChatSession[];
  loading: boolean;
  onNewSession: () => void;
  onOpenSettings: () => void;
  onSessionsChanged: () => void;
  userEmail?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  // Derive initials from email
  const initials = userEmail
    ? userEmail.split("@")[0].slice(0, 2).toUpperCase()
    : "VC";
  const displayName = userEmail ? userEmail.split("@")[0] : "Voce";
  const groups = groupByDate(sessions);

  async function handleRename(id: string) {
    if (!editTitle.trim()) return;
    try {
      await updateSession({ data: { id, title: editTitle.trim() } });
      setEditing(null);
      onSessionsChanged();
    } catch {
      // ignore
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteSession({ data: { id } });
      onSessionsChanged();
    } catch {
      // ignore
    }
  }

  return (
    <aside
      className={cn(
        "relative flex h-full shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-300",
        collapsed ? "w-[60px]" : "w-[260px]",
      )}
      style={{ transitionTimingFunction: "cubic-bezier(0.16,1,0.3,1)" }}
    >
      <div className="flex items-center justify-between px-2.5 py-3">
        <button
          onClick={onToggle}
          className="grid h-8 w-8 place-items-center rounded-md text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
          aria-label="Alternar menu lateral"
        >
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
        <span className={cn(
          "text-sm font-semibold tracking-tight whitespace-nowrap transition-opacity",
          collapsed ? "opacity-0 pointer-events-none" : "opacity-100",
        )}>
          Central
        </span>
        <button
          className={cn(
            "grid h-8 w-8 place-items-center rounded-md text-sidebar-foreground/70 transition-all hover:bg-sidebar-accent hover:text-sidebar-foreground",
            collapsed && "opacity-0 pointer-events-none",
          )}
          aria-label="Buscar"
        >
          <Search className="h-4 w-4" />
        </button>
      </div>

      <div className="px-2">
        <button
          onClick={onNewSession}
          className={cn(
            "flex w-full items-center gap-2 rounded-md border border-sidebar-border bg-sidebar px-2.5 py-2 text-sm font-medium text-sidebar-foreground transition-colors hover:bg-sidebar-accent",
            collapsed && "justify-center px-0",
          )}
        >
          <Plus className="h-4 w-4 shrink-0" />
          <span className={cn("whitespace-nowrap transition-opacity", collapsed ? "opacity-0 hidden" : "opacity-100")}>
            Nova conversa
          </span>
        </button>
      </div>

      <div className="mt-4 flex-1 overflow-y-auto px-2">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="px-2 py-8 text-center text-xs text-muted-foreground">
            {collapsed ? "" : "Sem conversas ainda."}
          </div>
        ) : (
          !collapsed && groups.map((g) => (
            <div key={g.label} className="mb-4">
              <div className="px-2 pb-1.5 text-[11px] font-medium uppercase tracking-wider text-sidebar-foreground/45">
                {g.label}
              </div>
              <div className="flex flex-col gap-0.5">
                {g.items.map((it) => {
                  const active = it.id === activeId;
                  return (
                    <div key={it.id} className="relative">
                      {editing === it.id ? (
                        <div className="flex items-center gap-1 px-2">
                          <input
                            autoFocus
                            value={editTitle}
                            onChange={(e) => setEditTitle(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") handleRename(it.id);
                              if (e.key === "Escape") setEditing(null);
                            }}
                            onBlur={() => handleRename(it.id)}
                            className="flex-1 rounded border border-sidebar-border bg-sidebar px-2 py-1 text-xs text-sidebar-foreground outline-none"
                          />
                        </div>
                      ) : (
                        <div
                          onMouseEnter={() => setHovered(it.id)}
                          onMouseLeave={() => setHovered(null)}
                          onClick={() => onSelect(it.id, it.title)}
                          className={cn(
                            "group relative flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors",
                            active
                              ? "bg-sidebar-accent text-sidebar-accent-foreground"
                              : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60",
                          )}
                        >
                          <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />
                          <span className="flex-1 truncate">{it.title}</span>
                          <div className={cn(
                            "flex items-center gap-0.5 transition-opacity",
                            hovered === it.id ? "opacity-100" : "opacity-0",
                          )}>
                            <button
                              className="grid h-6 w-6 place-items-center rounded text-sidebar-foreground/60 hover:bg-sidebar-border hover:text-sidebar-foreground"
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditing(it.id);
                                setEditTitle(it.title);
                              }}
                              aria-label="Editar"
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                            <button
                              className="grid h-6 w-6 place-items-center rounded text-sidebar-foreground/60 hover:bg-sidebar-border hover:text-destructive"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDelete(it.id);
                              }}
                              aria-label="Excluir"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="border-t border-sidebar-border p-2">
        <button
          onClick={onOpenSettings}
          className={cn(
          "flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-sidebar-foreground/80 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground",
          collapsed && "justify-center px-0",
        )}>
          <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-gradient-to-br from-primary to-primary-hover text-[11px] font-semibold text-primary-foreground">
            {initials}
          </div>
          <div className={cn(
            "flex flex-1 items-center justify-between whitespace-nowrap transition-opacity",
            collapsed ? "opacity-0 hidden" : "opacity-100",
          )}>
            <div className="flex flex-col items-start leading-tight">
              <span className="text-xs font-medium">{displayName}</span>
              <span className="text-[10px] text-sidebar-foreground/50">Pro</span>
            </div>
            <Settings className={cn(
              "h-3.5 w-3.5 opacity-60 transition-all",
              "group-hover/settings:opacity-100 group-hover/settings:text-sidebar-foreground"
            )} />
          </div>
        </button>
      </div>
    </aside>
  );
}
