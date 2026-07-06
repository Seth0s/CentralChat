import { X, Code2, Eye, Globe } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { CanvasBrowser } from "./CanvasBrowser";

type TabId = "preview" | "code" | "browser";

export function LiveCanvas({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<TabId>("preview");
  const [htmlContent, setHtmlContent] = useState("");
  if (!open) return null;

  return (
    <aside
      className="flex h-full w-full max-w-[480px] shrink-0 flex-col border-l border-border bg-card animate-in slide-in-from-right duration-300"
      style={{ animationTimingFunction: "cubic-bezier(0.16,1,0.3,1)" }}
    >
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span className="text-sm font-semibold tracking-tight">Live Canvas</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="flex items-center gap-0.5 rounded-md bg-secondary p-0.5">
            <TabBtn current={tab} id="preview" onClick={setTab} icon={Eye} label="Preview" />
            <TabBtn current={tab} id="code" onClick={setTab} icon={Code2} label="Code" />
            <TabBtn current={tab} id="browser" onClick={setTab} icon={Globe} label="Browser" />
          </div>
          <button
            onClick={onClose}
            className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            aria-label="Fechar canvas"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {tab === "browser" ? (
          <CanvasBrowser htmlContent={htmlContent} />
        ) : tab === "preview" ? (
          <div className="flex h-full flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border bg-muted/20 p-8 text-center">
            <div className="grid h-12 w-12 place-items-center rounded-xl bg-gradient-to-br from-primary to-primary-hover text-primary-foreground">
              <Eye className="h-5 w-5" />
            </div>
            <div>
              <div className="text-sm font-semibold">Preview ao vivo</div>
              <div className="mt-1 text-xs text-muted-foreground">
                Componentes gerados pela Central aparecem aqui em tempo real.
              </div>
            </div>
          </div>
        ) : (
          <pre className="m-0 rounded-lg border border-border bg-muted/30 p-4 text-[12px] leading-relaxed">
            <code>{`// generated.tsx
export function HelloCanvas() {
  return (
    <div className="p-4">
      <h1>Olá, Canvas!</h1>
    </div>
  );
}`}</code>
          </pre>
        )}
      </div>
    </aside>
  );
}

function TabBtn({
  current, id, onClick, icon: Icon, label,
}: {
  current: TabId; id: TabId; onClick: (id: TabId) => void;
  icon: React.ComponentType<{ className?: string }>; label: string;
}) {
  return (
    <button
      onClick={() => onClick(id)}
      className={cn(
        "flex items-center gap-1 rounded px-2 py-1 text-xs transition-colors",
        current === id
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      <Icon className="h-3 w-3" />
      {label}
    </button>
  );
}
