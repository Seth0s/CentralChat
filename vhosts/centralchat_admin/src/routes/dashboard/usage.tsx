import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchUsageSummary } from "@/lib/api/usage";

export const Route = createFileRoute("/dashboard/usage")({
  component: UsagePage,
});

function UsagePage() {
  const [window, setWindow] = useState<"24h" | "7d" | "30d">("7d");
  const { data, isLoading, error } = useQuery({
    queryKey: ["usage", window],
    queryFn: () => fetchUsageSummary({ data: { window } }),
  });

  const chartData = (data?.hours ?? [])
    .slice()
    .reverse()
    .map((h) => ({
      label: h.period_start.slice(5, 16).replace("T", " "),
      tokens: h.total_tokens,
      cost: h.total_cost,
    }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">Uso & custo</h2>
          <p className="text-sm text-muted-foreground">
            Rollup horário por tenant — tokens e custo estimado.
          </p>
        </div>
        <select
          className="rounded-md border border-border bg-background px-3 py-2 text-sm"
          value={window}
          onChange={(e) => setWindow(e.target.value as "24h" | "7d" | "30d")}
        >
          <option value="24h">24h</option>
          <option value="7d">7 dias</option>
          <option value="30d">30 dias</option>
        </select>
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">A carregar…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}

      {data && (
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat label="Tokens (janela)" value={data.total_tokens.toLocaleString()} />
          <Stat label="Custo (janela)" value={`$${data.total_cost.toFixed(4)}`} />
          <Stat
            label="Quota mensal"
            value={
              data.monthly_limit > 0
                ? `${data.monthly_pct.toFixed(1)}% de ${data.monthly_limit.toLocaleString()}`
                : "sem limite"
            }
          />
        </div>
      )}

      {chartData.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="mb-4 text-sm font-medium text-muted-foreground">Tokens por hora</h3>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
                <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip />
                <Bar dataKey="tokens" fill="hsl(var(--primary))" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}
