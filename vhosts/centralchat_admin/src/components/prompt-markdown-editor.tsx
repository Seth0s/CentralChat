import { useId } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Label } from "@/components/ui/label";
import {
  CATALOG_PROMPT_MAX_CHARS,
  estimatePromptTokens,
} from "@/lib/catalog-limits";
import { cn } from "@/lib/utils";

type PromptMarkdownEditorProps = {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
  label?: string;
};

export function PromptMarkdownEditor({
  value,
  onChange,
  placeholder = "Prompt em Markdown…",
  className,
  label = "Prompt",
}: PromptMarkdownEditorProps) {
  const fieldId = useId();
  const chars = value.length;
  const tokens = estimatePromptTokens(chars);
  const nearLimit = chars > CATALOG_PROMPT_MAX_CHARS * 0.9;

  const handleChange = (next: string) => {
    if (next.length <= CATALOG_PROMPT_MAX_CHARS) {
      onChange(next);
    }
  };

  return (
    <div className={cn("space-y-2", className)}>
      <Label htmlFor={fieldId}>{label}</Label>
      <Tabs defaultValue="edit">
        <TabsList>
          <TabsTrigger value="edit">Editar</TabsTrigger>
          <TabsTrigger value="preview">Pré-visualização</TabsTrigger>
        </TabsList>
        <TabsContent value="edit">
          <textarea
            id={fieldId}
            className="min-h-[280px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 font-mono text-sm leading-relaxed"
            placeholder={placeholder}
            value={value}
            onChange={(e) => handleChange(e.target.value)}
            maxLength={CATALOG_PROMPT_MAX_CHARS}
          />
        </TabsContent>
        <TabsContent value="preview">
          <div className="min-h-[280px] overflow-auto rounded-md border border-border bg-muted/20 px-4 py-3">
            {value.trim() ? (
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {value}
                </ReactMarkdown>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Nada para pré-visualizar — escreva o prompt no separador Editar.
              </p>
            )}
          </div>
        </TabsContent>
      </Tabs>
      <p
        className={cn(
          "text-xs tabular-nums",
          nearLimit
            ? "text-amber-600 dark:text-amber-500"
            : "text-muted-foreground",
        )}
      >
        {chars.toLocaleString("pt-PT")} /{" "}
        {CATALOG_PROMPT_MAX_CHARS.toLocaleString("pt-PT")} caracteres · ~
        {tokens.toLocaleString("pt-PT")} tokens
      </p>
    </div>
  );
}
