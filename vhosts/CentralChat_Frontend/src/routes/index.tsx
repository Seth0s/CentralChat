import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState, useCallback } from "react";
import { Sidebar } from "@/components/chat/Sidebar";
import { MessageBlock, type Message } from "@/components/chat/MessageBlock";
import { TerminalInput } from "@/components/chat/TerminalInput";
import { LiveCanvas } from "@/components/chat/LiveCanvas";
import { SettingsModal } from "@/components/chat/SettingsModal";
import { Moon, Sun, Share2, LogOut } from "lucide-react";
import { listSessions, createSession, getSession, type ChatSession } from "@/lib/api/sessions";
import { useAuth } from "@/lib/auth/client";
import { useAISettingsStore } from "@/stores/useAISettingsStore";
import { refresh } from "@/lib/auth/refresh";
import { validateSession } from "@/lib/auth/session";

// Refresh proactively at 75% of TTL (22.5 min for 30 min token)
const REFRESH_INTERVAL_MS = 20 * 60 * 1000; // 20 min

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Central — AI Chat" },
      { name: "description", content: "Workspace de IA com canvas ao vivo." },
    ],
  }),
  component: Index,
});

function Index() {
  const { logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeTitle, setActiveTitle] = useState("");
  const [canvasOpen, setCanvasOpen] = useState(false);
  const [dark, setDark] = useState(true);
  const [messages, setMessages] = useState<Message[]>([]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [loadingSessions, setLoadingSessions] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Load sessions on mount
  const loadSessions = useCallback(async () => {
    try {
      const result = await listSessions();
      setSessions(result.sessions || []);
    } catch (err) {
      console.error("Failed to load sessions:", err);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    loadSessions();

    // ── Fetch user info ──
    validateSession().then((s) => {
      if (s.valid && s.email) setUserEmail(s.email);
    }).catch(() => {});

    // ── Proactive token refresh ──
    const interval = setInterval(async () => {
      try {
        await refresh();
      } catch {
        // Token refresh failed — redirect to login
        window.location.href = "/login";
      }
    }, REFRESH_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [loadSessions]);

  // Create new session
  async function handleNewSession() {
    try {
      const s = await createSession({ data: { title: "Nova conversa" } });
      setSessions((prev) => [s, ...prev]);
      setActiveId(s.id);
      setActiveTitle(s.title);
      setMessages([]);
    } catch (err) {
      console.error("Failed to create session:", err);
    }
  }

  // Select session and load its messages
  async function handleSelectSession(id: string, title: string) {
    setActiveId(id);
    setActiveTitle(title);
    try {
      const session = await getSession({ data: { id } });
      if (session && session.messages) {
        const msgs: Message[] = session.messages.map((m: { role: string; content: string }, i: number) => ({
          id: `${id}-${i}`,
          role: (m.role === "assistant" ? "ai" : "user") as "user" | "ai",
          content: m.content,
        }));
        setMessages(msgs);
      } else {
        setMessages([]);
      }
    } catch {
      setMessages([]);
    }
  }

  // Send message with SSE streaming
  async function handleSend(text: string) {
    if (streaming) return;

    const startTime = performance.now();
    const updateTokenUsage = useAISettingsStore.getState().updateTokenUsage;
    const setActiveProvider = useAISettingsStore.getState().setActiveProvider;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    };
    const aiMsg: Message = {
      id: crypto.randomUUID(),
      role: "ai",
      content: "",
      isTyping: true,
    };
    setMessages((m) => [...m, userMsg, aiMsg]);
    setStreaming(true);

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          session_id: activeId || undefined,
          stream: true,
        }),
      });

      if (!response.ok) {
        const err = await response.text();
        throw new Error(err || `HTTP ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response stream");

      const decoder = new TextDecoder();
      let buffer = "";
      let fullContent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
            continue;
          }
          if (!line.startsWith("data: ")) continue;
          const raw = line.slice(6).trim();
          if (!raw || raw === "[DONE]") continue;

          try {
            const parsed = JSON.parse(raw);

            // ── SSE event routing ──
            if (currentEvent === "token" && parsed.d) {
              fullContent += parsed.d;
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === aiMsg.id ? { ...msg, content: fullContent } : msg,
                ),
              );
            }
            if (currentEvent === "provider" && parsed.d) {
              setActiveProvider(parsed.d);
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === aiMsg.id ? { ...msg, provider: parsed.d } : msg,
                ),
              );
            }
            if (currentEvent === "usage" && parsed.d) {
              const u = parsed.d;
              updateTokenUsage({
                promptTokens: u.prompt_tokens ?? 0,
                completionTokens: u.completion_tokens ?? 0,
                totalTokens: u.total_tokens ?? 0,
              });
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === aiMsg.id ? {
                    ...msg,
                    usage: u,
                    tokens: u.total_tokens ?? 0,
                  } : msg,
                ),
              );
            }
            if (currentEvent === "done") {
              const elapsed = ((performance.now() - startTime) / 1000).toFixed(1) + "s";
              setMessages((m) =>
                m.map((msg) =>
                  msg.id === aiMsg.id
                    ? { ...msg, isTyping: false, content: fullContent || parsed.reply || msg.content, turnTime: elapsed }
                    : msg,
                ),
              );
            }
          } catch {
            // ignore malformed SSE
          }
        }
      }

      // Mark as done if stream ended without explicit done event
      setMessages((m) =>
        m.map((msg) =>
          msg.id === aiMsg.id ? { ...msg, isTyping: false } : msg,
        ),
      );

      // Refresh session list (may have new session)
      loadSessions();
    } catch (err) {
      setMessages((m) =>
        m.map((msg) =>
          msg.id === aiMsg.id
            ? { ...msg, isTyping: false, content: `Erro: ${err instanceof Error ? err.message : "Stream falhou"}` }
            : msg,
        ),
      );
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
      <Sidebar
        collapsed={collapsed}
        onToggle={() => setCollapsed((c) => !c)}
        activeId={activeId}
        onSelect={handleSelectSession}
        sessions={sessions}
        loading={loadingSessions}
        onNewSession={handleNewSession}
        onOpenSettings={() => setSettingsOpen(true)}
        onSessionsChanged={loadSessions}
        userEmail={userEmail}
      />

      <div className="flex h-full min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold tracking-tight">
              {activeTitle || "Central"}
            </span>
            {activeId && (
              <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                Sessão ativa
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              aria-label="Compartilhar"
            >
              <Share2 className="h-4 w-4" />
            </button>
            <button
              onClick={() => setDark((d) => !d)}
              className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              aria-label="Alternar tema"
            >
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            <button
              onClick={() => logout()}
              className="grid h-8 w-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              aria-label="Sair"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1">
          <div className="flex min-w-0 flex-1 flex-col">
            <div ref={scrollRef} className="flex-1 overflow-y-auto">
              <div className="mx-auto w-full max-w-3xl px-4 py-8">
                {messages.length === 0 && !streaming && (
                  <div className="flex h-full flex-col items-center justify-center py-20 text-center">
                    <h2 className="text-lg font-semibold text-foreground">Central</h2>
                    <p className="mt-2 text-sm text-muted-foreground">
                      {activeId ? "Envie uma mensagem para começar." : "Crie uma nova conversa para começar."}
                    </p>
                  </div>
                )}
                {messages.map((m) => (
                  <MessageBlock key={m.id} message={m} />
                ))}
              </div>
            </div>
            <TerminalInput
              onSend={handleSend}
              canvasOpen={canvasOpen}
              onToggleCanvas={() => setCanvasOpen((c) => !c)}
              disabled={streaming}
            />
          </div>
          <LiveCanvas open={canvasOpen} onClose={() => setCanvasOpen(false)} />
        </div>
      </div>
      <SettingsModal open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
