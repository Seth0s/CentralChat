import { Copy, RotateCcw, ThumbsUp, ThumbsDown, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

export type Message = {
  id: string;
  role: "user" | "ai";
  content: string;
  isTyping?: boolean;
  tokens?: number;
  provider?: string;
  turnTime?: string;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
};

export function MessageBlock({ message }: { message: Message }) {
  const isAi = message.role === "ai";
  return (
    <div className="flex gap-4 py-6 animate-in fade-in-0 slide-in-from-bottom-1 duration-300">
      <div className="shrink-0">
        {isAi ? (
          <div
            className={cn(
              "grid h-8 w-8 place-items-center rounded-md bg-gradient-to-br from-primary to-primary-hover text-primary-foreground shadow-sm",
              message.isTyping && "animate-pulse",
            )}
            style={{ animationDuration: "1000ms" }}
          >
            <Sparkles className="h-4 w-4" />
          </div>
        ) : (
          <div className="grid h-8 w-8 place-items-center rounded-md bg-secondary text-secondary-foreground text-xs font-semibold">
            VC
          </div>
        )}
      </div>

      <div className="min-w-0 flex-1">
        <div className="mb-1 text-[13px] font-semibold tracking-tight">
          {isAi ? "Central" : "Você"}
        </div>

        {message.isTyping ? (
          <div className="flex items-center gap-1.5 py-2 text-muted-foreground">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:0ms]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:200ms]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground/60 [animation-delay:400ms]" />
          </div>
        ) : (
          <div className="doc-prose">
            {message.content.split("\n\n").map((para, i) => (
              <p key={i}>{para}</p>
            ))}
          </div>
        )}

        {isAi && !message.isTyping && (
          <div className="mt-3 flex items-center gap-1 opacity-70 transition-opacity hover:opacity-100">
            <ActionBtn icon={<Copy className="h-3.5 w-3.5" />} label="Copiar" />
            <ActionBtn icon={<RotateCcw className="h-3.5 w-3.5" />} label="Regenerar" />
            <ActionBtn icon={<ThumbsUp className="h-3.5 w-3.5" />} label="Gostei" />
            <ActionBtn icon={<ThumbsDown className="h-3.5 w-3.5" />} label="Não gostei" />
            {(message.tokens || message.provider || message.turnTime) && (
              <>
                <div className="mx-2 h-3 w-px bg-border" />
                {message.provider && (
                  <span className="text-[10px] text-muted-foreground/50 font-mono">{message.provider}</span>
                )}
                {message.tokens != null && message.tokens > 0 && (
                  <>
                    {message.provider && <span className="text-[11px] text-muted-foreground/60">·</span>}
                    <span className="text-[11px] text-muted-foreground tabular-nums">
                      {message.tokens.toLocaleString()} tokens
                    </span>
                  </>
                )}
                {message.turnTime && (
                  <>
                    <span className="text-[11px] text-muted-foreground/60">·</span>
                    <span className="text-[11px] text-muted-foreground tabular-nums">{message.turnTime}</span>
                  </>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ActionBtn({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <button
      aria-label={label}
      className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
    >
      {icon}
    </button>
  );
}