# T-1: Consolidation Status — Orchestrator Domain Files

> Status: ✅ TODAS AS FASES CONCLUÍDAS (1–13)

## Objetivo

Reorganizar o orchestrator backend de 147 ficheiros .py (monólito server.py de 3783 linhas) em ~20 ficheiros de domínio optimizados para IA. Cada ficheiro = 1 domínio completo.

## Estrutura Final Alvo

```
orchestrator/app/
├── server.py           (~400) thin router + factory
├── config.py           (~200) mantém como está
├── clients.py          (~100) mantém como está
├── health.py           (114)  ✓ DONE
├── playbook.py         (783)   ✓ DONE
├── workspace.py        (709)   ✓ DONE
├── sessions.py        (721)   ✓ DONE
├── approvals.py        (656)   ✓ DONE
├── actions.py          (1762)  ✓ DONE
├── inference.py        (1366)  ✓ DONE
├── rag.py              (1189)  ✓ DONE
├── tools.py            (3291)  ✓ DONE
├── connector.py        (1299)  ✓ DONE
├── auth.py             (824)   ✓ DONE
├── context.py          (2480)  ✓ DONE
├── assistant_routes.py (1274)  ✓ DONE
└── shared/             (~39 ficheiros utils estáveis)
```

## Progresso

| Fase | Domínio | Status | Ficheiros | Linhas | Notas |
|------|---------|--------|-----------|--------|-------|
| 1 | shared/ | ✅ DONE | 39 movidos | — | utils movidos, imports actualizados em 59 ficheiros |
| 2 | auth.py | ✅ DONE | 10 → 1 | 824 | circular config↔auth resolvida (lazy import) |
| 3 | connector.py | ✅ DONE | 9 → 1 | 1299 | — |
| 4 | tools.py | ✅ DONE | 10 → 1 | 3291 | 3 circular imports resolvidas (tools↔clients, tools→context→ambientacao→tools, filter_tool_specs ordering) |
| 5 | context.py | ✅ DONE | 15 → 1 | 2480 | context/ package removido (shadowava context.py), 3 circular imports resolvidas |
| 6 | playbook.py | ✅ DONE | 3 → 1 | 783 | playbook_routes.py + playbook_store.py + playbook_promotion_candidates.py; 5 imports actualizados (server, context, rag, orchestrator_audit, memory_context) |
| 7 | workspace.py | ✅ DONE | 4 → 1 | 709 | widget_slot_graph.py + workspace_canvas.py + workspace_store_pg.py + repositories/widget_slot_repository.py; 7 imports actualizados em 6 consumidores; circular import com canvas_write_context resolvida (lazy) |
| 8 | sessions.py | ✅ DONE | 4 → 1 | 721 | shared/chat_sessions.py + session_summary_store.py + repositories/chat_sessions_repository.py; 4 consumers actualizados (assistant_routes, context, memory_context, server); circular import sessions↔context resolvida (lazy) |
| 9 | approvals.py | ✅ DONE | 3 → 1 | 656 | action_policy.py + approval_via_tool.py; 4 consumers actualizados (tools, ambientacao, request_shell_tool, old_tools/platform_dispatch) |
| 10 | actions.py | ✅ DONE | 4 → 1 | 1762 | desktop_actions.py + probe_actions.py + request_shell_tool.py; 3 consumers actualizados (tools, server, approvals); circular import approvals↔actions resolvida (lazy em approvals) |
| 11 | inference.py | ✅ DONE | 12 → 1 | 1366 | 11 files consolidados (inference_resolve/routing/context/model_gate + vendor_catalog_cache + model_router_* + cloud_models_allowlist + auto_tier_policies); 7 consumers actualizados (context, clients, assistant_preferences, modality_models, assistant_routes, server, session_rag_worker); 2 circular imports resolvidas (modality_models, assistant_preferences) |
| 12 | rag.py | ✅ DONE | 13 → 1 | 1189 | 12 files consolidados (document_rag*/session_rag*/product_rag*/memory_*/agent_tools_rag*/ui_document_rag); 5 consumers actualizados (tools, context, server, sessions); 3 circular imports resolvidas (context↔rag via lazy get_embedding_service/search_memory/upsert_memory_item/load_context_settings) |
| 13 | cleanup | ✅ DONE | — | — | Verificação final: 0 stale imports, 0 syntax errors, 13/13 domain files import OK, server.py 437 linhas |

## Estado Actual

### Ficheiros concluídos (Fases 1–7)

| Ficheiro | Linhas | Domínio |
|----------|--------|---------|
| `app/health.py` | 114 | Health checks, metrics, host summary |
| `app/assistant_routes.py` | 1274 | ChatMessage, assistant_text/stream/voice, plan, compose |
| `app/auth.py` | 824 | Users, OIDC, JWT, rate limiting, production policy, refresh revocation |
| `app/connector.py` | 1299 | Connector registry/status, client jobs, file tools, shell gateway |
| `app/tools.py` | 3291 | Tool loop, registry, policy, metrics, embedding, modality |
| `app/context.py` | 2480 | Types, config, assembler, compaction, sections, session events, projection, graph, embedding, stream errors |
| `app/playbook.py` | 783 | CRUD, export, promotion candidates, feedback, RAG léxico |
| `app/workspace.py` | 709 | Slot graph, canvas, multi-artifact, PG store, metrics |

### Ficheiros existentes (pré-refactoring, não alterados)

| Ficheiro | Linhas | Domínio |
|----------|--------|---------|
| `app/server.py` | ~436 | Thin router + app factory |
| `app/config.py` | ~200 | Configuration (env vars, constants) |
| `app/clients.py` | ~1250 | LLM/STT/TTS calls, host fetchers |
| `app/http/auth_routes.py` | 297 | Auth endpoints |
| `app/http/router_connector.py` | 151 | Connector endpoints |
| `app/http/middleware*.py` | — | CORS, error handling |

### Ficheiros em shared/ (39 utils)

Movidos na Fase 1. Incluem: orchestrator_audit, pg_tenant, tenant_*, perception, modality_models, profiles, ambientacao, system_prompt_*, prompt_injection, l8_pipeline_policy, plan, approvals_store, chat_sessions, session_summary_store, workspace_canvas, workspace_store_pg, widget_slot_graph, etc.

## Padrões de Consolidação

Cada fase segue o mesmo processo:

1. **Ler** todos os módulos do domínio e mapear dependências internas
2. **Consolidar** com script AST: remover imports internos, manter imports externos
3. **Actualizar imports** em todos os ficheiros que dependem do domínio
4. **Remover** ficheiros antigos
5. **Resolver circular imports** com lazy imports (inside function bodies)
6. **Verificar** syntax (ast.parse) + import check de todos os domain files

### Circular Imports — Padrão de Resolução

Circular imports são resolvidas com lazy imports dentro de funções:

```python
# ❌ Top-level (causa circular)
from app.tools import get_agent_tools_catalog

def build_digest():
    rows = get_agent_tools_catalog()

# ✅ Lazy (dentro da função)
def build_digest():
    from app.tools import get_agent_tools_catalog
    rows = get_agent_tools_catalog()
```

### Casos Especiais Conhecidos

| Problema | Resolução |
|----------|-----------|
| context/ package shadowing context.py | Remover package, manter ficheiro |
| SessionEventStore() a nível de módulo | Lazy init via `_get_store()` |
| TOOLS_VECTOR_DIM import circular | Inline constant (384) |
| config.py → auth.py → config.py | Mover validate_auth_production_policy para server.py startup |

## Fases Pendentes — Detalhe

### Fase 6: playbook.py

Módulos a consolidar:
- `app/playbook_routes.py` (211) — endpoints
- `app/shared/playbook_store.py` (328) — storage
- `app/shared/playbook_promotion_candidates.py` (273) — promotion logic

Imports a actualizar: server.py, approvals.py, context.py, ambientacao.py

### Fase 7: workspace.py

Módulos a consolidar:
- `app/workspace.py` (65) — endpoints existentes
- `app/shared/workspace_canvas.py` (408) — canvas patches
- `app/shared/workspace_store_pg.py` (145) — PostgreSQL storage
- `app/shared/widget_slot_graph.py` (113) — slot graph

Imports a actualizar: server.py, tools.py, context.py

### Fase 8: sessions.py

Módulos a consolidar:
- `app/sessions.py` (131) — endpoints existentes
- `app/shared/chat_sessions.py` (399) — session management
- `app/shared/session_summary_store.py` (181) — summary storage

Imports a actualizar: server.py, context.py, assistant_routes.py, memory_context.py

### Fase 9: approvals.py

Módulos a consolidar:
- `app/approvals.py` (179) — endpoints existentes
- `app/shared/action_policy.py` (117) — action classification
- `app/shared/approval_via_tool.py` (361) — approval from tool calls

Imports a actualizar: server.py, tools.py, connector.py

### Fase 10: actions.py

Módulos a consolidar:
- `app/actions.py` (1185) — endpoints existentes
- `app/desktop_actions.py` (157) — desktop action handlers
- `app/probe_actions.py` (207) — probe/sensor handlers
- `app/request_shell_tool.py` (207) — shell request dispatch

Imports a actualizar: server.py, connector.py, tools.py

### Fase 11: inference.py

Módulos a consolidar:
- `app/inference.py` (301) — endpoints existentes
- `app/inference_resolve.py` (158) — model resolution
- `app/inference_routing.py` (22) — routing logic
- `app/inference_context.py` (25) — context cap
- `app/inference_model_gate.py` (62) — model gating
- `app/vendor_catalog_cache.py` (47) — vendor cache
- `app/model_router_client.py` (30) — router client
- `app/model_router_http_client.py` (94) — HTTP client
- `app/model_router_transport.py` (51) — transport layer
- `app/model_router_vendor_models.py` (95) — vendor models
- `app/cloud_models_allowlist.py` (205) — cloud allowlist
- `app/auto_tier_policies.py` (171) — auto-tier

Imports a actualizar: server.py, clients.py, tools.py

### Fase 12: rag.py

Módulos a consolidar:
- `app/rag.py` (190) — endpoints existentes
- `app/document_rag.py` (47) — document search
- `app/document_rag_chunking.py` (118) — chunking
- `app/document_rag_store_pgvector.py` (254) — pgvector store
- `app/session_rag.py` (112) — session RAG
- `app/session_rag_worker.py` (87) — async worker
- `app/product_rag.py` (141) — product RAG
- `app/product_rag_store_pgvector.py` (271) — pgvector store
- `app/memory_store_pgvector.py` (249) — memory store
- `app/memory_context.py` (161) — memory context builder
- `app/agent_tools_rag.py` (149) — agent tools RAG
- `app/agent_tools_store_pgvector.py` (156) — pgvector store
- `app/ui_document_rag.py` (84) — UI document RAG

Imports a actualizar: server.py, context.py, tools.py, assistant_routes.py

### Fase 13: Cleanup Final

- Verificar todos os imports
- Correr testes (pytest)
- Verificar que server.py inclui todos os routers
- Contagem final de ficheiros

## Métricas

| Métrica | Antes | Actual | Alvo |
|---------|-------|--------|------|
| Ficheiros .py (app/) | 147 | 67 | ~20 |
| server.py linhas | 3783 | 437 | ~400 |
| Domain files | 0 | 16 | 15 |
| Fases concluídas | 0 | 13 | 13 |

## Referências

- `server.py` — thin router com todos os includes
- `shared/` — 39 utils estáveis (não consolidar)
- Circular import patterns: lazy imports inside function bodies
- AST-based merge script: lê módulos, remove imports internos, concatena
