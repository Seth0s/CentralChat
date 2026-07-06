# Métricas Prometheus — ContextEngine

Métricas expostas pelo ContextEngine para observabilidade.

## Visão geral

| Métrica | Tipo | Descrição |
|---------|------|-----------|
| `context_build_duration_ms` | Histogram | Tempo total de build (resolve→post) |
| `context_step_duration_ms` | Histogram | Tempo por step, label `step` |
| `context_step_errors_total` | Counter | Steps que falharam, label `step` |
| `context_layers_applied` | Gauge | 1 se a layer foi aplicada, labels `layer`, `mode` |
| `context_rag_hit_count` | Gauge | Número de chunks RAG recuperados, label `kind` |
| `context_rag_build_ms` | Gauge | Tempo de retrieval RAG |
| `context_tools_injected` | Gauge | Número de tool schemas injectados |
| `context_compaction_rate` | Gauge | 1 se houve compactação neste turno, 0 caso contrário |
| `context_token_budget_total` | Gauge | Tokens totais alocados (l0_l4 + l5_rag + l6_window + l7_tools) |
| `context_token_budget_usage_ratio` | Gauge | Rácio tokens usados / max_total |

## Labels padrão

Todas as métricas incluem:
- `tenant_id` — tenant (default para single-tenant)
- `mode` — web | cli
- `role` — developer | reviewer | lead | auditor | admin

## Step timing (context_step_duration_ms)

Labels adicionais:
- `step` — nome do step (ex: "gather.system_layers")
- `phase` — resolve | gather | assemble | post

Registado para cada step via `state.meta[f"step_ms.{step.name}"]`.

## RAG hit count (context_rag_hit_count)

Labels adicionais:
- `kind` — session_rag | document_rag | memory_recall | product_rag

Registado via `state.meta["rag_hit_count"]` (dict[namespace → count]).

## Integração

Adicionar ao `app/metrics.py` (ou equivalente) usando a biblioteca `prometheus_client`:

```python
from prometheus_client import Histogram, Gauge, Counter

context_build_duration = Histogram(
    "context_build_duration_ms",
    "ContextEngine total build time",
    ["tenant_id", "mode", "role"],
    buckets=[5, 10, 25, 50, 100, 200, 500, 1000, 2000],
)

context_step_duration = Histogram(
    "context_step_duration_ms",
    "ContextEngine step duration",
    ["tenant_id", "step", "phase"],
    buckets=[1, 2, 5, 10, 25, 50, 100, 200],
)

context_step_errors = Counter(
    "context_step_errors_total",
    "ContextEngine step errors",
    ["step"],
)

context_rag_hit = Gauge(
    "context_rag_hit_count",
    "RAG hit count by kind",
    ["kind"],
)

context_tools_injected = Gauge(
    "context_tools_injected",
    "Number of tool schemas injected",
    ["mode"],
)

context_compaction = Gauge(
    "context_compaction_rate",
    "Compaction triggered this turn",
    ["mode"],
)
```

## Emissão

Após `assemble_context()`, o caller emite métricas a partir do `ContextState`:

```python
# No caller (assistant_routes.py ou equivalente):
context_build_duration.labels(
    tenant_id=tenant_id, mode=mode, role=role
).observe(state.build_ms)

for step_name, step_ms in state.meta.items():
    if step_name.startswith("step_ms."):
        context_step_duration.labels(
            tenant_id=tenant_id,
            step=step_name.replace("step_ms.", ""),
            phase=...  # inferido do nome do step
        ).observe(step_ms)

# RAG
for kind, count in state.meta.get("rag_hit_count", {}).items():
    context_rag_hit.labels(kind=kind).set(count)

context_tools_injected.labels(mode=mode).set(len(state.tools))
context_compaction.labels(mode=mode).set(1 if state.session_truncated else 0)
```
