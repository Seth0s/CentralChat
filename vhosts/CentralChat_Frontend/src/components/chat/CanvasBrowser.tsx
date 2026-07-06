import { useState } from "react";
import { ExternalLink, RefreshCw, AlertTriangle } from "lucide-react";

type Props = {
  htmlContent: string;
};

export function CanvasBrowser({ htmlContent }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [key, setKey] = useState(0); // force iframe remount on refresh

  if (!htmlContent) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border bg-muted/20 p-8 text-center">
        <AlertTriangle className="h-8 w-8 text-muted-foreground" />
        <div>
          <div className="text-sm font-semibold">Sem conteúdo</div>
          <div className="mt-1 text-xs text-muted-foreground">
            Peça à Central para gerar código HTML e ele aparecerá aqui.
          </div>
        </div>
      </div>
    );
  }

  function handleOpenNewWindow() {
    const blob = new Blob([htmlContent], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    window.open(url, "_blank", "noopener,noreferrer");
  }

  function handleRefresh() {
    setError(null);
    setKey((k) => k + 1);
  }

  // Listen for errors from the iframe
  function handleIframeLoad(e: React.SyntheticEvent<HTMLIFrameElement>) {
    try {
      const iframe = e.currentTarget;
      const win = iframe.contentWindow;
      if (win) {
        win.onerror = (msg) => {
          setError(String(msg));
        };
      }
    } catch {
      // cross-origin — ignore
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-xs text-muted-foreground">
          Sandbox preview
        </span>
        <div className="flex items-center gap-1">
          <button
            onClick={handleRefresh}
            className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground"
            aria-label="Recarregar"
          >
            <RefreshCw className="h-3 w-3" />
          </button>
          <button
            onClick={handleOpenNewWindow}
            className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground"
            aria-label="Abrir em nova janela"
          >
            <ExternalLink className="h-3 w-3" />
          </button>
        </div>
      </div>
      {error && (
        <div className="border-b border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {error}
        </div>
      )}
      <div className="flex-1 bg-white">
        <iframe
          key={key}
          sandbox="allow-scripts"
          srcDoc={htmlContent}
          title="Canvas Preview"
          className="h-full w-full border-0"
          onLoad={handleIframeLoad}
        />
      </div>
    </div>
  );
}
