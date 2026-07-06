import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Dialog, DialogContent, DialogTitle, DialogDescription,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  Brain, Bot, Wrench, Settings as SettingsIcon,
  Search, Plus, Monitor, Moon, Sun, Trash2,
  Loader2, SlidersHorizontal, Zap, Activity,
  ArrowDown, ArrowUp, BarChart3,
} from "lucide-react";
import { fetchConfig, saveProviderRouting, type OrchestratorConfig } from "@/lib/api/config";
import { useAISettingsStore } from "@/stores/useAISettingsStore";
import { useFetchModels, type ModelEntry } from "@/hooks/useFetchModels";
import { useAgents, useSaveAgent, useSkills, useSaveSkill, type IAgent, type ISkill } from "@/services/PromptService";
import { fetchUsage, type UsageStats } from "@/lib/api/usage";

type TabId = "usage" | "models" | "agents" | "skills" | "advanced";

const TABS: { id: TabId; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "usage", label: "Usage", icon: BarChart3 },
  { id: "models", label: "Model Hub", icon: Brain },
  { id: "agents", label: "Agents", icon: Bot },
  { id: "skills", label: "Skills", icon: Wrench },
  { id: "advanced", label: "Advanced", icon: SettingsIcon },
];

interface SettingsModalProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function SettingsModal({ open, defaultOpen, onOpenChange }: SettingsModalProps) {
  const [active, setActive] = useState<TabId>("usage");
  const [config, setConfig] = useState<OrchestratorConfig | null>(null);
  const [loadingConfig, setLoadingConfig] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoadingConfig(true);
    fetchConfig().then(setConfig).catch(() => null).finally(() => setLoadingConfig(false));
  }, [open]);

  return (
    <Dialog open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-full h-[80vh] flex overflow-hidden p-0 rounded-xl border border-border bg-background shadow-2xl gap-0">
        <DialogTitle className="sr-only">Settings</DialogTitle>
        <DialogDescription className="sr-only">Manage usage, models, agents, skills, and advanced configuration.</DialogDescription>

        <aside className="w-64 bg-muted/20 border-r border-border p-4 flex flex-col gap-2">
          <div className="px-2 pb-3 pt-1">
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">Settings</div>
            <div className="mt-0.5 text-sm font-semibold text-foreground">Command Center</div>
          </div>
          {TABS.map((t) => {
            const Icon = t.icon;
            return (
              <button key={t.id} onClick={() => setActive(t.id)}
                className={cn("flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors text-left",
                  active === t.id ? "bg-primary/10 text-primary font-medium" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground")}>
                <Icon className="h-4 w-4 shrink-0" /> {t.label}
              </button>
            );
          })}
        </aside>

        <section className="flex-1 overflow-y-auto p-6 md:p-8">
          {active === "usage" && <UsagePane config={config} loading={loadingConfig} />}
          {active === "models" && <ModelsPane />}
          {active === "agents" && <AgentsPane />}
          {active === "skills" && <SkillsPane />}
          {active === "advanced" && <AdvancedPane config={config} />}
        </section>
      </DialogContent>
    </Dialog>
  );
}

function PaneHeader({ title, description }: { title: string; description: string }) {
  return <div className="mb-6"><h2 className="text-xl font-semibold tracking-tight text-foreground">{title}</h2><p className="mt-1 text-sm text-muted-foreground">{description}</p></div>;
}

// ═══════════ A. Usage ═══════════

function UsagePane({ config, loading }: { config: OrchestratorConfig | null; loading: boolean }) {
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [loadingUsage, setLoadingUsage] = useState(false);

  useEffect(() => {
    setLoadingUsage(true);
    fetchUsage().then(setUsage).catch(() => setUsage(null)).finally(() => setLoadingUsage(false));
  }, []);

  if (loading || loadingUsage) return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;

  const tokensInput = usage?.tokens_input ?? 0;
  const tokensOutput = usage?.tokens_output ?? 0;
  const totalTokens = tokensInput + tokensOutput;
  const totalCost = usage?.total_cost ?? 0;
  const quotaPct = usage?.quota_pct ?? 0;
  const quotaLimit = usage?.quota_limit ?? 0;
  const quotaEnabled = usage?.quota_enabled ?? false;

  return (
    <div>
      <PaneHeader title="Usage" description="Estatísticas de uso do serviço." />

      <div className="grid grid-cols-2 gap-3 mb-6">
        <MetricCard icon={ArrowDown} label="Tokens In" value={tokensInput.toLocaleString()} color="text-blue-500" bg="bg-blue-500/10" />
        <MetricCard icon={ArrowUp} label="Tokens Out" value={tokensOutput.toLocaleString()} color="text-emerald-500" bg="bg-emerald-500/10" />
        <MetricCard icon={Zap} label="Total Tokens" value={totalTokens.toLocaleString()} color="text-amber-500" bg="bg-amber-500/10" />
        <MetricCard icon={Activity} label="Custo" value={`$${totalCost.toFixed(4)}`} color="text-purple-500" bg="bg-purple-500/10" />
      </div>

      {quotaEnabled && (
        <div className="rounded-lg border border-border bg-card p-5 mb-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold">Quota (hora corrente)</span>
            <span className={cn("text-xs font-mono", quotaPct > 80 ? "text-destructive" : "text-muted-foreground")}>
              {totalTokens.toLocaleString()} / {quotaLimit.toLocaleString()} tokens
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all duration-500", quotaPct > 80 ? "bg-destructive" : "bg-primary")}
              style={{ width: `${Math.min(quotaPct, 100)}%` }}
            />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            {usage?.period_label} · Reinicia às {usage?.period_end?.slice(11, 16) ?? "—"} UTC
          </p>
        </div>
      )}

      <div className="rounded-lg border border-border bg-card p-5">
        <h3 className="mb-3 text-sm font-semibold">Serviço</h3>
        <div className="space-y-2 text-xs text-muted-foreground">
          <div className="flex items-center justify-between">
            <span>Orchestrator</span>
            <span className={cn("font-mono", config?.model_router_configured ? "text-emerald-500" : "text-amber-500")}>
              {config?.model_router_configured ? "Conectado" : "Sem chave"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span>Endpoint</span>
            <span className="font-mono">{config?.api_host}:{config?.api_port}</span>
          </div>
          {config?.connector_status && (
            <div className="flex items-center justify-between">
              <span>Connector</span>
              <span className={cn("font-mono", config.connector_status.online ? "text-emerald-500" : "text-muted-foreground")}>
                {config.connector_status.online ? "Online" : "Offline"}
              </span>
            </div>
          )}
        </div>
      </div>

      {!usage && !loadingUsage && (
        <p className="mt-3 text-xs text-muted-foreground">Métricas de uso indisponíveis — endpoint /ui/usage não retornou dados.</p>
      )}
    </div>
  );
}

function MetricCard({ icon: Icon, label, value, color, bg }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string; color: string; bg: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className={cn("mb-1 inline-flex h-8 w-8 items-center justify-center rounded-md", bg)}>
        <Icon className={cn("h-4 w-4", color)} />
      </div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-mono text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}

// ═══════════ Provider grouping ═══════════

function extractProvider(modelId: string): string {
  const slash = modelId.indexOf("/");
  if (slash === -1) return "Outros";
  const provider = modelId.slice(0, slash);
  // Capitalize first letter of each segment
  return provider
    .split(/[-_.]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

type ModelGroup = { provider: string; models: ModelEntry[] };

function groupByProvider(models: ModelEntry[]): ModelGroup[] {
  const map = new Map<string, ModelEntry[]>();
  for (const m of models) {
    const p = extractProvider(m.id);
    const list = map.get(p) || [];
    list.push(m);
    map.set(p, list);
  }
  // Sort groups alphabetically by provider name
  return Array.from(map.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([provider, models]) => ({ provider, models }));
}

// ═══════════ B. Model Hub ═══════════

function ModelsPane() {
  const { data: models, isLoading } = useFetchModels();
  const { enabledModels, toggleModel, modelParams, setModelParams } = useAISettingsStore();
  const [query, setQuery] = useState("");

  // Debounced search: update filter 150ms after user stops typing
  const [debouncedQuery, setDebouncedQuery] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 150);
    return () => clearTimeout(t);
  }, [query]);

  const groups = useMemo(() => {
    if (!models) return [];
    const q = debouncedQuery.toLowerCase().trim();
    let filtered = models;
    if (q) {
      filtered = models.filter(
        (m) =>
          (m.label || m.id).toLowerCase().includes(q) ||
          m.id.toLowerCase().includes(q),
      );
    }
    return groupByProvider(filtered);
  }, [models, debouncedQuery]);

  const enabledSet = useMemo(() => new Set(enabledModels), [enabledModels]);

  if (isLoading) return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* ═══ Header fixo: título + busca ═══ */}
      <div className="flex-none space-y-4 pb-4">
        <PaneHeader title="Model Hub" description="Ative os modelos que pretende usar no chat. Use a busca para filtrar." />
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar modelos..."
            className="h-11 pl-10"
          />
        </div>
      </div>

      {/* ═══ Lista scrollable: ocupa o resto do espaço ═══ */}
      <div className="flex-1 overflow-y-auto min-h-0 border border-border rounded-lg bg-card shadow-sm">
        {!models || models.length === 0 ? (
          <div className="px-4 py-10 text-center text-sm text-muted-foreground">Nenhum modelo disponível.</div>
        ) : groups.length === 0 ? (
          <div className="px-4 py-10 text-center text-sm text-muted-foreground">Nenhum modelo encontrado para "{debouncedQuery}".</div>
        ) : (
          groups.map((group) => (
            <div key={group.provider}>
              {/* ═══ Sticky provider header ═══ */}
              <div className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm border-b border-border px-4 py-2 font-semibold text-xs tracking-wider text-muted-foreground uppercase">
                {group.provider}
                <span className="ml-2 font-normal normal-case text-[10px] tabular-nums">
                  {group.models.filter((m) => enabledSet.has(m.id)).length}/{group.models.length}
                </span>
              </div>
              {group.models.map((m) => (
                <ModelRow
                  key={m.id}
                  model={m}
                  enabled={enabledSet.has(m.id)}
                  onToggle={() => toggleModel(m.id)}
                  params={modelParams[m.id] || {}}
                  onParamsChange={(p) => setModelParams(m.id, p)}
                />
              ))}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function ModelRow({ model, enabled, onToggle, params, onParamsChange }: {
  model: ModelEntry; enabled: boolean; onToggle: () => void;
  params: Partial<{ temperature: number; topP: number; nitro: boolean; reasoning: boolean }>;
  onParamsChange: (p: Partial<{ temperature: number; topP: number; nitro: boolean; reasoning: boolean }>) => void;
}) {
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-border last:border-0 hover:bg-muted/50 transition-colors">
      <div className="min-w-0 flex-1">
        <span className="truncate text-xs text-foreground/90">{model.label || model.id}</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Popover>
          <PopoverTrigger asChild>
            <button
              className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground transition-colors"
              aria-label="Parâmetros do modelo"
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-48 p-3 bg-card border border-border shadow-md rounded-lg" align="end">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <Label className="text-xs cursor-pointer" htmlFor={`nitro-${model.id}`}>Nitro</Label>
                <Switch
                  id={`nitro-${model.id}`}
                  checked={params.nitro ?? false}
                  onCheckedChange={(v) => onParamsChange({ ...params, nitro: v })}
                  className="scale-75 data-[state=checked]:bg-primary"
                />
              </div>
              <div className="flex items-center justify-between">
                <Label className="text-xs cursor-pointer" htmlFor={`reasoning-${model.id}`}>Reasoning</Label>
                <Switch
                  id={`reasoning-${model.id}`}
                  checked={params.reasoning ?? false}
                  onCheckedChange={(v) => onParamsChange({ ...params, reasoning: v })}
                  className="scale-75 data-[state=checked]:bg-primary"
                />
              </div>
            </div>
          </PopoverContent>
        </Popover>
        <Switch checked={enabled} onCheckedChange={onToggle} className="data-[state=checked]:bg-primary" />
      </div>
    </div>
  );
}

// ═══════════ C. Agents ═══════════

function AgentsPane() {
  const { data: agents, isLoading } = useAgents();
  const saveAgent = useSaveAgent();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");

  const selected = agents?.find((a) => a.id === selectedId);

  useEffect(() => {
    if (selected) { setName(selected.name); setPrompt(selected.prompt); }
  }, [selected]);

  if (isLoading) return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">Agents</h2>
          <p className="mt-1 text-sm text-muted-foreground">Personas globais com pré-prompts.</p>
        </div>
        <Button size="sm" onClick={() => { const id = crypto.randomUUID(); setSelectedId(id); setName(""); setPrompt(""); }}>
          <Plus className="h-4 w-4" /> Create Agent
        </Button>
      </div>
      <div className="grid grid-cols-[220px_1fr] gap-5">
        <div className="rounded-lg border border-border bg-card p-2 max-h-[400px] overflow-auto">
          {(agents || []).map((a) => (
            <button key={a.id} onClick={() => setSelectedId(a.id)}
              className={cn("flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
                selectedId === a.id ? "bg-primary/10 text-primary font-medium" : "text-muted-foreground hover:bg-muted/50 hover:text-foreground")}>
              <Bot className="h-3.5 w-3.5" /> {a.name}
            </button>
          ))}
        </div>
        <div className="space-y-4">
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Agent Name</label>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div>
            <label className="mb-1.5 block text-xs font-medium text-muted-foreground">Master Pre-prompt</label>
            <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} className="min-h-[260px] font-mono text-xs leading-relaxed" />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm">Cancel</Button>
            <Button size="sm" onClick={() => saveAgent.mutate({ id: selectedId || undefined, name, prompt })} disabled={!name.trim()}>Save Agent</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ═══════════ D. Skills ═══════════

function SkillsPane() {
  const { data: skills, isLoading } = useSkills();
  const saveSkill = useSaveSkill();

  if (isLoading) return <div className="flex items-center justify-center py-20"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">Skills</h2>
          <p className="mt-1 text-sm text-muted-foreground">Blocos de instrução injetáveis nos agentes.</p>
        </div>
        <Button size="sm" variant="outline"><Plus className="h-4 w-4" /> New Skill</Button>
      </div>
      <div className="grid grid-cols-2 gap-4">
        {(skills || []).map((s) => (
          <div key={s.id} className="group rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/40">
            <div className="mb-3 flex items-start justify-between">
              <div className="grid h-9 w-9 place-items-center rounded-md bg-primary/10 text-primary"><Wrench className="h-4 w-4" /></div>
              <Switch checked={s.enabled} className="data-[state=checked]:bg-primary" />
            </div>
            <h3 className="text-sm font-semibold text-foreground">{s.name}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{s.description}</p>
            <Button variant="ghost" size="sm" className="mt-3 -ml-3 h-7 text-xs">Edit Prompt</Button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════ E. Advanced ═══════════

function AdvancedPane({ config }: { config: OrchestratorConfig | null }) {
  const { parameters, setParameters, providerRouting, setProviderRouting, clearHistory } = useAISettingsStore();
  const [prefsVersion, setPrefsVersion] = useState(0);

  function handleProviderRoutingChange(routing: string) {
    setProviderRouting(routing);
    // Save to server (user_preferences)
    saveProviderRouting({ data: { routing: routing as "cheapest" | "fastest" | "highest_throughput", version: prefsVersion } })
      .then((res) => { if (res && typeof res === "object" && "version" in res) setPrefsVersion(res.version as number); })
      .catch(() => {}); // best-effort, state is already local
  }

  return (
    <div>
      <PaneHeader title="Advanced" description="Parametros globais de inferencia e preferencias." />
      <div className="space-y-8">
        <section className="rounded-lg border border-border bg-card p-5">
          <h3 className="mb-4 text-sm font-semibold text-foreground">Provider Routing</h3>
          <p className="mb-4 text-xs text-muted-foreground">Como o OpenRouter seleciona provedores para cada chamada — independe do modelo escolhido.</p>
          <div className="grid grid-cols-3 gap-3">
            {([
              { id: "cheapest", label: "Mais Barato", desc: "Menor preco por token", icon: ArrowDown },
              { id: "fastest", label: "Mais Rapido", desc: "Menor latencia", icon: Zap },
              { id: "highest_throughput", label: "Maior Throughput", desc: "Mais tokens/segundo", icon: Activity },
            ]).map(({ id, label, desc, icon: Icon }) => (
              <button key={id} onClick={() => handleProviderRoutingChange(id)}
                className={cn(
                  "flex flex-col items-center justify-center gap-2 rounded-md border p-4 text-xs transition-colors",
                  providerRouting === id
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border text-muted-foreground hover:bg-muted/40 hover:text-foreground"
                )}>
                <Icon className="h-5 w-5" />
                <span className="font-medium">{label}</span>
                <span className="text-[10px] leading-tight opacity-70">{desc}</span>
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card p-5">
          <h3 className="mb-4 text-sm font-semibold text-foreground">Sampling Parameters</h3>
          <div className="space-y-6">
            <ParamSlider label="Temperature" hint="Criatividade vs determinismo (0.0 – 2.0)" min={0} max={2} step={0.05}
              value={[parameters.temperature]} onChange={([v]) => setParameters({ temperature: v })} />
            <ParamSlider label="Top P" hint="Nucleus sampling (0.0 – 1.0)" min={0} max={1} step={0.01}
              value={[parameters.topP]} onChange={([v]) => setParameters({ topP: v })} />
          </div>
        </section>

        <section className="rounded-lg border border-border bg-card p-5">
          <h3 className="mb-4 text-sm font-semibold text-foreground">Appearance</h3>
          <div className="grid grid-cols-3 gap-3">
            {(["dark", "light", "system"] as const).map((t) => (
              <button key={t}
                className={cn("flex flex-col items-center justify-center gap-2 rounded-md border p-4 text-xs transition-colors",
                  "border-border text-muted-foreground hover:bg-muted/40 hover:text-foreground")}>
                {t === "dark" ? <Moon className="h-4 w-4" /> : t === "light" ? <Sun className="h-4 w-4" /> : <Monitor className="h-4 w-4" />}
                {t === "dark" ? "Dark" : t === "light" ? "Light" : "System"}
              </button>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-destructive/40 bg-destructive/5 p-5">
          <h3 className="text-sm font-semibold text-destructive">Danger Zone</h3>
          <p className="mt-1 text-xs text-muted-foreground">Apaga permanentemente todo o histórico de conversas locais.</p>
          <div className="mt-4">
            <Button variant="destructive" size="sm" onClick={clearHistory}><Trash2 className="h-4 w-4" /> Clear Chat History</Button>
          </div>
        </section>
      </div>
    </div>
  );
}

function ParamSlider({ label, hint, min, max, step, value, onChange }: {
  label: string; hint: string; min: number; max: number; step: number;
  value: number[]; onChange: (v: number[]) => void;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-medium">{label}</span>
        <span className="text-xs tabular-nums text-muted-foreground">{value[0]?.toFixed(2)}</span>
      </div>
      <Slider min={min} max={max} step={step} value={value} onValueChange={onChange} className="[&>span]:bg-primary" />
      <p className="mt-1 text-[11px] text-muted-foreground">{hint}</p>
    </div>
  );
}
