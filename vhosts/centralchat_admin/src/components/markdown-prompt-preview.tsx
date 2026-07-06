import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

type MarkdownPromptPreviewProps = {
  text: string;
  className?: string;
};

export function MarkdownPromptPreview({
  text,
  className,
}: MarkdownPromptPreviewProps) {
  if (!text.trim()) return null;

  return (
    <div
      className={cn(
        "relative mt-2 max-h-36 overflow-hidden rounded-md border border-border/60 bg-muted/25 px-3 py-2",
        className,
      )}
    >
      <div className="prose prose-sm dark:prose-invert max-w-none text-muted-foreground">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
      </div>
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t from-background to-transparent"
        aria-hidden
      />
    </div>
  );
}
