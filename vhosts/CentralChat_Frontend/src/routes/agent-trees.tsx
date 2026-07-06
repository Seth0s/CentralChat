import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Plus, Trash2, ChevronRight, Loader2, ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { listAgentTrees, createAgentTree, deleteAgentTree, type AgentTree } from "@/lib/api/agent-trees";

export const Route = createFileRoute("/agent-trees")({
  component: AgentTreesPage,
});

function AgentTreesPage() {
  const [trees, setTrees] = useState<AgentTree[]>([]);
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  async function load() {
    try {
      const result = await listAgentTrees();
      setTrees(Array.isArray(result) ? result : []);
    } catch { /* empty */ }
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  async function handleCreate() {
    if (!name.trim()) return;
    setCreating(true);
    try {
      await createAgentTree({ data: { name: name.trim() } });
      setName("");
      await load();
    } catch { /* empty */ }
    setCreating(false);
  }

  async function handleDelete(id: string) {
    try {
      await deleteAgentTree({ data: { id } });
      await load();
    } catch { /* empty */ }
  }

  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <Link to="/" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <span className="text-sm font-semibold">Agent Trees</span>
      </header>

      <div className="flex-1 overflow-auto p-6">
        <Card className="mx-auto max-w-2xl">
          <CardContent className="space-y-4 pt-6">
            <div className="flex gap-2">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Nome da árvore..."
                onKeyDown={(e) => e.key === "Enter" && handleCreate()}
              />
              <Button onClick={handleCreate} disabled={creating || !name.trim()}>
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              </Button>
            </div>

            {loading ? (
              <div className="flex justify-center py-8">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : trees.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                Nenhuma árvore. Crie uma acima.
              </p>
            ) : (
              <div className="space-y-1">
                {trees.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-center justify-between rounded-md px-3 py-2 transition-colors hover:bg-secondary/50"
                  >
                    <div className="flex items-center gap-2">
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      <span className="text-sm">{t.name}</span>
                      {t.description && (
                        <span className="text-xs text-muted-foreground">{t.description}</span>
                      )}
                    </div>
                    <button
                      onClick={() => handleDelete(t.id)}
                      className="grid h-7 w-7 place-items-center rounded text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                      aria-label="Apagar"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
