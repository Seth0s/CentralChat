import { createFileRoute } from "@tanstack/react-router";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  createAuditExportJob,
  downloadAuditExportJob,
  exportAuditCsv,
  exportAuditReportPdf,
  fetchAuditEvents,
  fetchAuditExportJobs,
} from "@/lib/api/audit";
import { fetchSessionRole } from "@/lib/auth/role";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import { toast } from "sonner";

export const Route = createFileRoute("/dashboard/audit")({
  component: AuditPage,
});

function AuditPage() {
  const qc = useQueryClient();
  const [since, setSince] = useState("7d");
  const [action, setAction] = useState("");
  const [userId, setUserId] = useState("");
  const [pathPrefix, setPathPrefix] = useState("");

  const { data: roleData } = useQuery({
    queryKey: ["session-role"],
    queryFn: () => fetchSessionRole(),
  });
  const canExport =
    roleData?.role === "admin" || roleData?.role === "auditor";

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["audit", since, action, userId, pathPrefix],
    queryFn: () =>
      fetchAuditEvents({
        data: {
          since,
          limit: 200,
          action: action || undefined,
          user_id: userId || undefined,
          path_prefix: pathPrefix || undefined,
        },
      }),
  });

  const exportsQuery = useQuery({
    queryKey: ["audit-export-jobs"],
    queryFn: () => fetchAuditExportJobs(),
    enabled: canExport,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? [];
      return items.some((j) => j.status === "pending" || j.status === "running")
        ? 3000
        : false;
    },
  });

  const asyncExportMut = useMutation({
    mutationFn: () =>
      createAuditExportJob({
        data: {
          since,
          userId: userId || undefined,
          action: action || undefined,
          pathPrefix: pathPrefix || undefined,
          format: "csv",
        },
      }),
    onSuccess: () => {
      toast.success("Export assíncrono iniciado (até 50k linhas).");
      qc.invalidateQueries({ queryKey: ["audit-export-jobs"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const downloadMut = useMutation({
    mutationFn: (jobId: string) => downloadAuditExportJob({ data: { jobId } }),
    onSuccess: (result, jobId) => {
      const blob = new Blob([result.body], {
        type: result.contentType || "text/csv",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `audit-export-${jobId.slice(0, 8)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    },
    onError: (e) => toast.error((e as Error).message),
  });

  const items = data?.items ?? [];
  const exportJobs = exportsQuery.data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">Auditoria</h2>
          <p className="text-sm text-muted-foreground">
            Log append-only — leitura para papéis <code className="rounded bg-secondary px-1">auditor</code> e{" "}
            <code className="rounded bg-secondary px-1">admin</code>.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            className="rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={since}
            onChange={(e) => setSince(e.target.value)}
          >
            <option value="24h">24h</option>
            <option value="7d">7 dias</option>
            <option value="30d">30 dias</option>
          </select>
          <input
            className="w-36 rounded-md border border-border bg-background px-3 py-2 text-sm"
            placeholder="Acção"
            value={action}
            onChange={(e) => setAction(e.target.value)}
          />
          <input
            className="w-36 rounded-md border border-border bg-background px-3 py-2 text-sm"
            placeholder="User ID"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
          />
          <input
            className="w-36 rounded-md border border-border bg-background px-3 py-2 text-sm"
            placeholder="path_prefix"
            value={pathPrefix}
            onChange={(e) => setPathPrefix(e.target.value)}
          />
          <Button variant="outline" size="sm" onClick={() => refetch()}>
            Actualizar
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              const b64 = await exportAuditReportPdf({
                data: { since, pathPrefix: pathPrefix || undefined, userId: userId || undefined, action: action || undefined },
              });
              const bin = atob(b64);
              const bytes = new Uint8Array(bin.length);
              for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
              const blob = new Blob([bytes], { type: "application/pdf" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `audit-report-${since}.pdf`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export PDF
          </Button>
          <Button
            size="sm"
            onClick={async () => {
              const csv = await exportAuditCsv({
                data: { since, pathPrefix: pathPrefix || undefined, userId: userId || undefined, action: action || undefined },
              });
              const blob = new Blob([csv], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `audit-${since}.csv`;
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Export CSV
          </Button>
          {canExport && (
            <Button
              size="sm"
              variant="secondary"
              disabled={asyncExportMut.isPending}
              onClick={() => asyncExportMut.mutate()}
            >
              Export async (50k)
            </Button>
          )}
        </div>
      </div>

      {canExport && exportJobs.length > 0 && (
        <section className="rounded-lg border border-border p-4">
          <h3 className="text-sm font-medium">Exports assíncronos</h3>
          <ul className="mt-2 space-y-2 text-sm">
            {exportJobs.map((job) => (
              <li
                key={job.id}
                className="flex flex-wrap items-center justify-between gap-2"
              >
                <span className="font-mono text-xs">
                  {job.id.slice(0, 8)}… · {job.status}
                  {job.row_count != null ? ` · ${job.row_count} linhas` : ""}
                </span>
                {job.download_ready && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={downloadMut.isPending}
                    onClick={() => downloadMut.mutate(job.id)}
                  >
                    Descarregar
                  </Button>
                )}
                {job.error && (
                  <span className="text-xs text-destructive">{job.error}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">A carregar…</p>}
      {error && <p className="text-sm text-destructive">{(error as Error).message}</p>}

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border bg-secondary/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2">Quando</th>
              <th className="px-3 py-2">Acção</th>
              <th className="px-3 py-2">Recurso</th>
              <th className="px-3 py-2">Utilizador</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-muted-foreground">
                  Sem eventos no período.
                </td>
              </tr>
            ) : (
              items.map((ev) => (
                <tr key={ev.id} className="border-b border-border/60">
                  <td className="px-3 py-2 font-mono text-xs">{ev.created_at?.slice(0, 19) ?? "—"}</td>
                  <td className="px-3 py-2">{ev.action}</td>
                  <td className="px-3 py-2 text-muted-foreground">{ev.resource ?? "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs">{ev.user_id?.slice(0, 8) ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
