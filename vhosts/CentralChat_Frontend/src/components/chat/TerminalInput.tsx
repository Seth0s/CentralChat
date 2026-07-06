import { useRef, useEffect, useState, useMemo } from "react";
import {
  Paperclip, PanelRightOpen, ArrowUp, Zap,
  Brain, ChevronDown, Check, Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchCloudModels, type ModelEntry } from "@/lib/api/config";
import { useAISettingsStore } from "@/stores/useAISettingsStore";

type SelectableModel = { id: string; name: string; contextLimit: number };

// ── Token Progress Bar ──

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

function TokenProgressBar() {
  const { totalTokens, promptTokens, completionTokens } = useAISettingsStore((s) => s.tokenUsage);
  const contextLimit = useAISettingsStore((s) => s.contextLimit);

  const pct = contextLimit > 0 ? Math.min((totalTokens / contextLimit) * 100, 100) : 0;

  const fillColor =
    pct <= 60 ? "bg-emerald-500" :
    pct <= 85 ? "bg-amber-500" :
    "bg-rose-500";

  const textColor =
    pct <= 60 ? "text-emerald-400" :
    pct <= 85 ? "text-amber-400" :
    "text-rose-400";

  if (totalTokens === 0 && promptTokens === 0 && completionTokens === 0) return null;

  return (
    <div
      className={cn(
        "group/tb absolute inset-x-0 top-0 z-10 overflow-hidden rounded-t-2xl transition-all duration-300 ease-out",
        "h-1 hover:h-7",
      )}
    >
      {/* Track background */}
      <div className="absolute inset-0 bg-gray-800/50" />

      {/* Fill bar */}
      <div
        className={cn(
          "absolute inset-y-0 left-0 transition-all duration-500 ease-out",
          fillColor,
        )}
        style={{ width: `${pct}%` }}
      />

      {/* Text — visible only on hover */}
      <div className="absolute inset-0 flex items-center justify-end px-3 opacity-0 group-hover/tb:opacity-100 transition-opacity duration-200">
        <span className={cn("font-mono text-[10px] tabular-nums", textColor)}>
          {formatTokens(totalTokens)} / {formatTokens(contextLimit)} ({Math.round(pct)}%)
        </span>
      </div>
    </div>
  );
}

// ── Terminal Input ──

export function TerminalInput({
  onSend,
  onToggleCanvas,
  canvasOpen,
  disabled,
}: {
  onSend: (text: string) => void;
  onToggleCanvas: () => void;
  canvasOpen: boolean;
  disabled?: boolean;
}) {
  const [value, setValue] = useState("");
  const [modelOpen, setModelOpen] = useState(false);
  const [model, setModel] = useState<SelectableModel | null>(null);
  const [allModels, setAllModels] = useState<SelectableModel[]>([]);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const enabledModels = useAISettingsStore((s) => s.enabledModels);
  const setContextLimit = useAISettingsStore((s) => s.setContextLimit);

  // Fetch all models once, build lookup map
  useEffect(() => {
    fetchCloudModels()
      .then((cat) => {
        const list: SelectableModel[] = (cat.models || []).map((m: ModelEntry) => ({
          id: m.id,
          name: m.label || m.id,
          contextLimit: m.context_length || 128_000,
        }));
        setAllModels(list);
      })
      .catch(() => {});
  }, []);

  // Derive visible models: only those in enabledModels from store
  const visibleModels = useMemo(() => {
    if (enabledModels.length === 0) return [];
    const enabledSet = new Set(enabledModels);
    return allModels.filter((m) => enabledSet.has(m.id));
  }, [allModels, enabledModels]);

  // Auto-select first enabled model if none selected
  useEffect(() => {
    if (!model && visibleModels.length > 0) {
      setModel(visibleModels[0]);
    }
  }, [visibleModels, model]);

  // Sync context limit to store when model changes
  useEffect(() => {
    if (model) {
      setContextLimit(model.contextLimit);
    }
  }, [model, setContextLimit]);

  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 240) + "px";
  }, [value]);

  const submit = () => {
    const t = value.trim();
    if (!t) return;
    onSend(t);
    setValue("");
  };

  return (
    <div className="w-full max-w-3xl mx-auto px-4 md:px-0 pb-4">
      <div
        className="relative flex flex-col gap-2 rounded-2xl border border-border bg-muted/30 p-3 shadow-[0_8px_30px_-12px_rgba(0,0,0,0.25)] backdrop-blur-sm transition-shadow focus-within:border-primary/40 focus-within:shadow-[0_8px_40px_-8px_color-mix(in_oklab,var(--color-primary)_30%,transparent)]"
      >
        {/* ═══ Token Progress Bar (top edge, expands on hover) ═══ */}
        <TokenProgressBar />

        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Escreva à Central… (use / para atalhos)"
          rows={1}
          disabled={disabled}
          className="w-full resize-none border-0 bg-transparent px-1 py-1.5 text-[15px] leading-relaxed text-foreground placeholder:text-muted-foreground/70 focus:outline-none disabled:opacity-50"
        />

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <IconBtn label="Anexar"><Paperclip className="h-4 w-4" /></IconBtn>
            <IconBtn label="Live Canvas" active={canvasOpen} onClick={onToggleCanvas}>
              <PanelRightOpen className="h-4 w-4" />
            </IconBtn>

            {/* ═══════ Model selector ═══════ */}
            <div className="relative">
              <button
                onClick={() => setModelOpen((o) => !o)}
                className="ml-1 flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <Zap className="h-3.5 w-3.5" />
                <span>{model?.name ?? "Nenhum modelo"}</span>
                <ChevronDown className="h-3 w-3 opacity-60" />
              </button>
              {modelOpen && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setModelOpen(false)} />
                  <div className="absolute bottom-full left-0 z-50 mb-2 w-72 origin-bottom-left rounded-xl border border-border bg-popover shadow-xl animate-in fade-in-0 zoom-in-95 slide-in-from-bottom-2 duration-150">
                    <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Modelos disponíveis
                    </div>

                    {/* ═══ Scrollable list — max height ═══ */}
                    <div className="max-h-[300px] overflow-y-auto">
                      {visibleModels.length === 0 ? (
                        <div className="flex flex-col items-center gap-2 px-3 py-6 text-center">
                          <Settings className="h-5 w-5 text-muted-foreground/40" />
                          <p className="text-xs text-muted-foreground leading-relaxed">
                            Nenhum modelo ativado.
                            <br />
                            Vá em <span className="font-medium text-foreground/70">Configurações → Model Hub</span>
                          </p>
                        </div>
                      ) : (
                        visibleModels.map((m) => {
                          const active = m.id === model?.id;
                          return (
                            <button
                              key={m.id}
                              onClick={() => { setModel(m); setModelOpen(false); }}
                              className="flex w-full items-start gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-accent"
                            >
                              <div className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-secondary text-foreground/80">
                                <Brain className="h-3.5 w-3.5" />
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-medium truncate">{m.name}</span>
                                </div>
                              </div>
                              {active && <Check className="h-3.5 w-3.5 text-primary mt-1 shrink-0" />}
                            </button>
                          );
                        })
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>

          <button
            onClick={submit}
            disabled={!value.trim() || disabled}
            className={cn(
              "grid h-8 w-8 place-items-center rounded-lg transition-all",
              value.trim()
                ? "bg-primary text-primary-foreground hover:bg-primary-hover shadow-sm"
                : "bg-secondary text-muted-foreground cursor-not-allowed",
            )}
            aria-label="Enviar"
          >
            <ArrowUp className="h-4 w-4" />
          </button>
        </div>
      </div>
      <div className="mt-2 text-center text-[10px] text-muted-foreground/60">
        Central pode cometer erros. Verifique informações importantes.
      </div>
    </div>
  );
}

function IconBtn({
  children,
  label,
  active,
  onClick,
}: {
  children: React.ReactNode;
  label: string;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      aria-label={label}
      onClick={onClick}
      className={cn(
        "grid h-8 w-8 place-items-center rounded-md transition-colors",
        active
          ? "bg-primary/15 text-primary"
          : "text-muted-foreground hover:bg-secondary hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}
