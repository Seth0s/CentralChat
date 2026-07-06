# CentralChat — Plano Canónico: Context Engine, RAG, Multi-dev e Agent Platform

> **UPDATED:** 2026-06-26  
> **Status:** EM IMPLEMENTAÇÃO — backend das Ondas 0–5 + AST (H4) + HERMES-ADAPT (H1, H6) concluídos.  
> **Pendente (14 itens):** UI (3.4), OpenAPI cleanup (3.5), e2e tests (3.6), CLI WI bootstrap (4.7), Timeline API (5.5), Pentest (5.8), SKILL.md migration (AST-6), connector infra (H-2 a H-5)  
> **Audiência:** engenharia backend, UI, CLI, product  
> **Origem:** discussões de hardening de agente, unificação de contexto e plataforma multi-dev (2026-06-18)

**Ver também:** [`CLI_RUNTIME_MODES.md`](./CLI_RUNTIME_MODES.md) (TEAM/SOLO) · [`CONTEXT_SECURITY_AND_TRUST.md`](./CONTEXT_SECURITY_AND_TRUST.md) (trust L5, precedência, CQS).

---

## CHANGELOG

| Data | Resumo |
|------|--------|
| 2026-06-18 | Documento canónico criado: decisões, arquitectura alvo, RAG, multi-dev, AST, roadmap com checklists |
| 2026-06-18 | Referência a `CLI_RUNTIME_MODES.md` (TEAM híbrido + SOLO) |
| 2026-06-18 | Referência a `CONTEXT_SECURITY_AND_TRUST.md` |
| **2026-06-26** | **Onda 0–5 + AST (H4) + HERMES-ADAPT (H1, H6) implementados** |
| 2026-06-26 | Unificação de tools: `app/tool_catalog.py` como fonte única |

---

## 1. Resumo executivo

### Tese

O CentralChat deixa de ser um chat com **flags opt-in** fragmentadas e passa a um **sistema operativo de trabalho assistido por IA para equipas**, com:

1. **Um único pipeline de contexto** (`ContextEngine`) — plugável, testável, escalável.
2. **Política server-side** (`ContextPolicy`) — o servidor decide o que injectar; o cliente observa via `ui_trace`.
3. **RAG como camada controlada** (L5) — nunca substitui barreiras determinísticas (L0–L4) nem histórico verbatim recente (L6).
4. **Work Item como âncora de contexto** — continuidade entre devs, não memória pessoal monolítica.
5. **AST como ferramenta** (`ask_project`) — consulta sob demanda; não injecção automática no hot path.

### Decisões aprovadas (registo)

| ID | Decisão | Estado |
|----|---------|--------|
| **D-CTX-1** | Unificar `ContextAssembler` + `ContextPipeline` em `ContextEngine` com steps plugáveis | Aprovado |
| **D-CTX-2** | Remover flags HTTP de contexto (`include_*`); substituir por `ContextPolicy` + gates automáticos | Aprovado |
| **D-CTX-3** | RAG válido no hardening como L5 opt-in automático (gates), com delimitadores e trust levels | Aprovado |
| **D-CTX-4** | Uma única compactação (`ContextWindowManager` + PG `session_summaries`); eliminar duplicidade legado | Aprovado |
| **D-CTX-5** | Tools: catálogo leve + schemas OpenAI nativos + RAG-driven selection + schema tracking | Aprovado |
| **D-AST-1** | AST = tool `ask_project` (H4); não substitui skills L3 nem injecção automática | Aprovado (alinhado `HARDENING_PLAN` D-AST-1) |
| **D-WI-1** | Work Item (WI) como camada L2 obrigatória quando `work_item_id` presente | Aprovado |
| **D-WI-2** | Memória em namespaces: `user_profile`, `team`/`repo`, `work_item:{id}` | Aprovado |
| **D-WI-3** | Handoff/fork de sessão entre devs com ACL + audit | Aprovado |
| **D-WI-4** | Contexto sensível ao papel RBAC (`developer` ≠ `reviewer` ≠ `auditor`) | Aprovado |
| **D-WI-5** | Coordenação anti-clobber: file lease, branch por WI, stale diff detection | Aprovado |
| **D-HERMES-1** | Técnicas Hermes (infinite tools, `execute_code`, `delegate_task`) — fase posterior, adaptadas a connector + policy | Aprovado (roadmap Fase D) |
| **D-CLI-1** | CLI: runtime único; modos SOLO e TEAM (`CLI_RUNTIME_MODES.md`) | Aprovado |
| **D-CLI-2** | TEAM: inferência local + InferencePlan VPS; SOLO: autosustentável `~/.central/` | Aprovado |

### Documentos relacionados

| Documento | Relação |
|-----------|---------|
| `CONTEXT_SYSTEM_REDESIGN.md` | Design inicial do `ContextPipeline` (2026-06-08); **este doc supersede o plano de execução** |
| `CONTEXT_PIPELINE_ANALYSIS.md` | Análise do estado legado |
| `AST_CONTEXT_DESIGN.md` | Schema AST + `ask_project` |
| `HARDENING_PLAN.md` | Ondas A–D enterprise; AST congelado até H4 |
| `MVP_REPOSITIONING.md` | Work Queue §8, sessões, approvals |
| `ADMIN_PROFESSIONALIZATION_PLAN.md` | UI queue/sessions colaborativa |
| `RBAC_MATRIX.md` | Roles → permissões |
| `CLI_RUNTIME_MODES.md` | **Canónico** — TEAM (híbrido + WS + performance) e SOLO |
| `CONTEXT_SECURITY_AND_TRUST.md` | **Canónico** — trust L5, precedência, connector, CQS, fuzz |
| `CLI_UX_SPEC.md` | TUI, tabs, slash commands |

---

## 2. Estado actual e gaps (baseline 2026-06-18)

### 2.1 O que já existe

| Componente | Localização | Notas |
|------------|-------------|-------|
| `ContextPipeline` (parcial) | `app/context_pipeline.py` | L1–L5 + `ToolInjector` keyword; caminho activo em `assistant_routes.py` |
| `ContextAssembler` (legado) | `app/context.py` (~2480 linhas) | RAG, pre-injeção, memory recall — **não no hot path actual** |
| RAG consolidado | `app/rag.py` | document / session / product / agent-tools / memory |
| Sessões + event log | `app/sessions.py` | `append_completed_turn` + `ingest_session_turn_facts` |
| Work Queue | `app/work_queue.py` | WI com `session_id`, `approval_ids`, assignee |
| Session ACL | `app/session_acl.py` | share user/role: read/write/admin |
| Agent trees | `app/agent_tree.py` | `inherit_mode`: none/summary/full |
| Team rules (HITL) | `app/memory_service.py` | só `approved=true` no prompt |
| DLP pré-prompt | `app/shared/dlp_scanner.py` | regex secrets/PII |
| Policy + approvals | `app/approvals.py`, policy PG | four-eyes, path rules |

### 2.2 Gaps críticos

| Gap | Impacto |
|-----|---------|
| **Assimetria write/read session RAG** | Indexação pós-turno activa; recall no `ContextPipeline` **ausente** |
| **Flags HTTP audadas mas ignoradas** | `include_document_rag`, `include_session_rag`, etc. — confusão API/UI |
| **Dupla compactação** | `CompactionService` (legado) vs `ContextWindowManager` (pipeline) |
| **Product RAG incondicional no legado** | Desperdício em saudações (corrigido no desenho, não no pipeline activo) |
| **Pre-injeção / capability digest** | Não religados ao pipeline activo |
| **Token budget** | `chars/4` vs tiktoken |
| **Multi-dev** | WI, ACL, queue existem; **não alimentam o contexto do agente** |

---

## 3. Arquitectura alvo: ContextEngine

### 3.1 Visão em 4 fases

```
POST /assistant/text/stream
│
├─ FASE 1 — RESOLVE (sync, <5ms)
│    ResolveSessionHistory, ResolveWorkItem, ResolveActiveDocument,
│    ResolveAgentProfile, ResolveExecutionMode, ResolveContextPolicy
│
├─ FASE 2 — GATHER (async paralelo, ~120ms budget)
│    SystemLayersStep (L0–L4), RetrievalOrchestrator (L5),
│    ToolSelectionStep (L7), CompactionPrep (L6 input)
│
├─ FASE 3 — ASSEMBLE (sync, determinístico)
│    MergeSections, TokenBudgetAllocator (tiktoken), SchemaTracker,
│    BuildMessagesAndTools
│
├─ LLM / Agent tool loop
│
└─ FASE 4 — POST (background)
     SessionIndexStep, AsyncCompactionCheckpoint, AuditEmit
```

### 3.2 Contrato de step (escalabilidade)

Cada passo futuro regista-se no `STEP_REGISTRY` sem alterar `assistant_routes.py`.

```python
@dataclass
class ContextState:
    request: AssistantRequest
    tenant_id: str
    user_id: str
    role: str                    # RBAC: developer | reviewer | lead | auditor | admin
    session_id: str | None
    work_item_id: str | None
    history: list[Message]
    policy: ContextPolicy
    sections: list[PromptSection]
    tools: list[OpenAITool]
    meta: dict[str, Any]
    budget: TokenBudget

class ContextStep(Protocol):
    name: str
    phase: Literal["resolve", "gather", "assemble", "post"]
    priority: int

    async def should_run(self, state: ContextState) -> bool: ...
    async def run(self, state: ContextState) -> ContextState: ...
```

### 3.3 Estrutura de pacote alvo

```
app/context_engine/
├── __init__.py              # assemble_context() — entry point único
├── state.py                 # ContextState, PromptSection, TokenBudget
├── policy.py                # ContextPolicy, resolve_policy()
├── registry.py              # STEP_REGISTRY, run_phase()
├── orchestrator.py
├── steps/
│   ├── resolve/
│   │   ├── session_history.py
│   │   ├── work_item.py
│   │   ├── active_document.py
│   │   └── execution_mode.py
│   ├── gather/
│   │   ├── system_layers.py      # L0–L4
│   │   ├── retrieval.py          # L5 RetrievalOrchestrator
│   │   ├── pending_state.py      # approvals + blockers
│   │   ├── tool_selection.py     # L7
│   │   └── compaction_prep.py
│   ├── assemble/
│   │   ├── merge_sections.py
│   │   ├── token_budget.py
│   │   └── build_messages.py
│   └── post/
│       ├── session_index.py
│       ├── async_checkpoint.py
│       └── audit_emit.py
└── tests/
    ├── golden/
    └── test_gates.py
```

`context_pipeline.py` → thin wrapper até absorção completa. `context.py` → só types/utils até remoção.

---

## 4. Camadas de contexto (L0–L7)

| Layer | Nome | Origem | Natureza | Quando |
|-------|------|--------|----------|--------|
| **L0** | `security_anchor` | Pré-injeção mínima + DLP | Determinístico | Sempre |
| **L1** | `system_identity` | Agent + product pack | Determinístico | Sempre (exceto focus mode) |
| **L2** | `workspace` + **work_item** | Connector/git + WI | Determinístico | Se bound / WI activo |
| **L3** | `agent_skills` | Team catalog / user agents | Determinístico | Se `agent_name` |
| **L4** | `governance_rules` | Team rules aprovadas | Determinístico | Sempre (tenant) |
| **L5** | `retrieved_context` | RAG merge | Probabilístico | Gates automáticos |
| **L6** | `session_window` | Histórico verbatim + summary | Híbrido | Sempre |
| **L7** | `tools_surface` | Catálogo + schemas activos | Policy-driven | Se `use_agent_tools` |

### Regra de ouro (hardening)

- **L0–L4** nunca dependem de embedding.
- **L5** nunca substitui **L6 verbatim recente** (tail sagrado).
- **L7** least-privilege por `role` + `execution_mode` + connector alive.

### PromptSection uniforme

```python
@dataclass
class PromptSection:
    layer: str
    kind: str                    # session_rag | document_rag | work_item | pending_state | ...
    content: str
    provenance: str              # pgvector:product_rag_chunks | work_items | ...
    trust_level: Literal["curated", "retrieved", "user_upload", "operational"]
    char_budget: int
    score: float | None = None
```

Prefixos existentes mantidos: `[CONTEXT_RETRIEVED — session namespace]`, `[DOCUMENT_RAG — excerpts only; ...]`.

---

## 5. ContextPolicy — substitui flags HTTP

### 5.1 Flags a remover do contrato API

| Flag actual | Substituição |
|-------------|--------------|
| `include_long_session_memory` | Compactação automática por token budget |
| `include_memory_recall` | Gate semântico + policy |
| `include_document_rag` + `document_rag_doc_id` | `active_document_id` na sessão/WI |
| `include_session_rag` | Gate: sessão longa ou query referencia passado |
| `include_playbook` | Keyword gate interno |
| `include_capability_digest` | Remover (redundante com `tools[]`) |
| `include_host_context` | Trigger server-side + policy |
| `use_saved_assistant_defaults` | `resolve_policy()` no servidor |

### 5.2 Flags a manter

| Flag | Motivo |
|------|--------|
| `chat_session_id` | Identidade da sessão |
| `work_item_id` | **Novo** — âncora de contexto de equipa |
| `agent_name` | Routing de agente |
| `use_agent_tools` | Modo agente vs chat |
| `model_override` | Governança validada |
| `widget_active_slot` | Multi-slot futuro |

### 5.3 Modelo ContextPolicy

```python
@dataclass
class ContextPolicy:
    max_context_tokens: int = 128_000
    rag_char_budget: int = 6_000
    verbatim_tail_messages: int = 20

    session_rag: AutoGate = AutoGate.ALWAYS_IF_SESSION
    document_rag: AutoGate = AutoGate.IF_ACTIVE_DOC
    memory_recall: AutoGate = AutoGate.SEMANTIC_GATE
    product_rag: AutoGate = AutoGate.INTENT_GATE
    playbook: AutoGate = AutoGate.KEYWORD_GATE

    dlp_enabled: bool = True
    focus_mode: bool = False
    pre_injection_path: str | None = None

    tool_selection: Literal["rag", "keyword", "full"] = "rag"
    max_tool_schemas: int = 5

    role_tool_allowlist: frozenset[str]  # por RBAC
```

Resolução: `resolve_policy(tenant_id, user_prefs, role, execution_mode)`.

Transparência: `ui_trace.injection_summary_pt` lista o que o servidor aplicou (sem corpo de system messages sensíveis).

---

## 6. RetrievalOrchestrator (L5)

### 6.1 Gather paralelo

Todas as queries RAG em `asyncio.gather` com timeout por step (150ms default); falha → omitir secção (fail-open controlado).

### 6.2 Gates (substituem flags)

| Retrieval | Gate | Default |
|-----------|------|---------|
| Session RAG | `chat_session_id` + (msgs > 20 **ou** intent temporal) | On |
| Document RAG | `active_document_id` na sessão/WI | Off até haver doc |
| Memory recall | Score semântico > threshold | Off em saudações |
| Product RAG | Intent keywords; não focus mode | Off em "olá" |
| Playbook | Token overlap > threshold | Off |

### 6.3 Segurança RAG

| Técnica | Implementação |
|---------|---------------|
| Tenant isolation | `tenant_id` + RLS em todas as queries |
| Prompt injection mitigation | Delimitadores + `trust_level` |
| DLP no ingest | Session facts + memory writes (pós-turno) |
| Never-store | Segredos, PII, dumps brutos — spec em memória externa |
| Focus mode | Kill-switch total de embeddings/RAG na superfície HTTP |

---

## 7. Compactação e budget (L6)

### 7.1 Estratégia única

1. Estimar tokens L0–L5 + L7 (tiktoken; fallback `chars/4`).
2. Calcular espaço para L6.
3. Se cabe → verbatim intacto.
4. Se não → summary progressivo + tail verbatim (`KEEP_RECENT=20`).
5. Persistir em PG `session_summaries`; checkpoint async pós-turno.

### 7.2 Eliminar

- `CompactionService` legado (após migração).
- Flag `include_long_session_memory`.
- Cache in-memory volátil de summaries.

---

## 8. Tools (L7)

### 8.1 Modelo

- **Catálogo leve** (~30 tokens): nomes apenas.
- **Schemas OpenAI nativos**: top-5 por embedding + Tier-0.
- **Schema tracker**: reinjecta só schemas ausentes após compactação.
- **Scoping**: `KNOWLEDGE_TOOLS` vs `DELEGATED_TOOLS` (connector alive / modo CLI).

### 8.2 Tier-0 (sempre candidatos)

`memory`, `session_search`, `clarify`, `ask_project` (quando AST H4 activo).

### 8.3 Modos de execução

| Modo | Connector | Tools |
|------|-----------|-------|
| WEB | offline | KNOWLEDGE apenas |
| WEB | vivo | KNOWLEDGE + DELEGATED |
| CLI | local | KNOWLEDGE + DELEGATED |

`execute_code` — **só via connector** (nunca no VPS). Fase D (estilo Hermes).

---

## 9. Plataforma multi-dev e Work Queue

### 9.1 Work Item como âncora (L2)

Quando `work_item_id` presente, injectar bloco determinístico:

- título, descrição, labels, status, priority
- assignee, reporter, `workspace_path`, `repo`
- `approval_ids` pendentes
- últimos eventos da timeline (`work_item_events`)
- sessões anteriores ligadas (IDs + resumos)

Comando CLI alvo: `central work WI-142` → abre/retoma sessão com contexto WI.

### 9.2 Pending state injection

Bloco `[PENDING_STATE]` antes do LLM:

- Approvals aguardando revisão
- WI blocked por policy
- `team_requests` abertos (lead_decision, policy_exception, …)

### 9.3 Handoff e fork de sessão

| Acção | Comportamento |
|-------|---------------|
| **Handoff** | Dev A → Dev B: mesma sessão (ACL write) + resumo executivo injectado |
| **Fork** | Nova sessão com contexto importado do WI; histórico limpo |
| **Observer** | Lead/auditor: ACL read; não polluta contexto do agente activo |

Audit: `session.handoff`, `session.fork` com actor, target, work_item_id.

### 9.4 Memória em namespaces

| Namespace | Escopo | Escrita | Leitura |
|-----------|--------|---------|---------|
| `user_profile` | Preferências do dev | UI / tool `memory` | L5 gate |
| `team` / `repo:{name}` | Decisões curadas | HITL / lead | L4 + L5 |
| `work_item:{id}` | Factos do chamado | Pós-turno extract | L2 + L5; expira ao fechar WI |

Session RAG: filtrar também por `work_item_id` quando aplicável.

### 9.5 Contexto por papel (RBAC → ContextPolicy)

| Papel | Tools write | Contexto extra |
|-------|-------------|----------------|
| `developer` | Se policy + connector | WI, código, pending próprio |
| `reviewer` | Negado | Diff, audit, violations |
| `lead` | Conforme policy | Queue project, team requests |
| `auditor` | Negado | Audit export scope; zero delegated |

### 9.6 Coordenação anti-clobber

| Técnica | Momento |
|---------|---------|
| File lease (`path_prefix` no WI em `in_progress`) | Claim WI |
| Branch sugerida `wi-{id}-{slug}` | Criação sessão |
| Stale diff (SHA antes de apply) | Pré-approval |
| Conflict card no agente | Pós-read_file se SHA mudou |

### 9.7 WI como trigger de agente

Fontes automáticas (já no schema `source`):

`rejection` | `ci` | `policy` | `tool_failure` → criar WI + **bootstrap sessão** com contexto do evento + assignee on-call do path.

### 9.8 Session search de equipa

Tool `session_search` Tier-0 com filtros: `repo`, `path_prefix`, `work_item_id`, `assignee`, `date_range`. Respeita `session_acl`.

### 9.9 Subagentes com scope de WI

`delegate_task` / `agent_tree`:

- `work_item_id` obrigatório em contexto de equipa
- `toolsets` = intersecção(parent, policy, role)
- `inherit_mode`: preferir `summary` para filhos
- Audit: árvore ligada a `work_item_id` + `parent_session_id`

### 9.10 Triângulo de conhecimento

| Fonte | Pergunta |
|-------|----------|
| `ask_project` (AST) | Como está estruturado o código? |
| `session_search` | O que o time já decidiu/tentou? |
| `memory` (team/repo) | Que regras duráveis existem? |

---

## 10. AST (H4)

Alinhado a `AST_CONTEXT_DESIGN.md` e decisão D-AST-1:

- **Não** injecção automática no `RetrievalOrchestrator`.
- **Sim** tool `ask_project` no Tier-0 L7.
- **Sim** `POST /ast/query` com pgvector + graph expansion.
- Skills L3 coexistem; AST complementa impacto/dependências.

### Fases AST

| Fase | Entrega |
|------|---------|
| AST-A | Parser Python + schema `ast_nodes` |
| AST-B | Convenções SKILL.md → nós CONVENTION/PITFAIL |
| AST-C | `/ast/query` + tool `ask_project` |
| AST-D | Canvas visual (opcional) |

---

## 11. Mapa de adopção Hermes (fase posterior)

| Técnica Hermes | CentralChat | Fase |
|----------------|-------------|------|
| Progressive tool disclosure | `ToolInjector` + vector RAG | B ctx / D hermes |
| `execute_code` RPC | Via connector apenas | D |
| `delegate_task` orchestrator/leaf | `agent_tree` + WI scope | C |
| FTS session search | `session_search` team-scoped | B |
| Skills auto-criadas | **Não** — team skills com HITL | — |
| Honcho user modeling | **Não** — perfil mínimo + team memory | — |
| MCP progressive | Com policy filter | D |
| LSP pós-write | Connector pós-patch aprovado | D |
| Environment gates | Gates por WI labels / repo / role | B |

---

## 12. Migração de API

### 12.1 Request simplificado (breaking change)

```json
{
  "text": "...",
  "chat_session_id": "abc12345",
  "work_item_id": "WI-142",
  "agent_name": "coder",
  "use_agent_tools": true,
  "model_override": null,
  "widget_active_slot": 1
}
```

### 12.2 Período de transição

1. **Sprint 1–2:** aceitar flags legadas; log `deprecated_flag`; ignorar no pipeline novo.
2. **Sprint 3:** remover flags da OpenAPI; UI remove checkboxes.
3. **Sprint 4:** remover código morto de defaults `include_*`.

### 12.3 Novos campos

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `work_item_id` | string? | Liga sessão ao WI; activa L2 work_item |
| `handoff_from_session_id` | string? | Handoff audit trail |
| `session_mode` | enum? | `continue` \| `fork` \| `observe` |

---

## 13. Hardening (checklist transversal)

Aplicar em todas as ondas:

- [x] DLP pré-prompt (L0)
- [x] DLP no ingest RAG/memory
- [x] Tenant RLS em todos os retrievals
- [x] `trust_level` em todas as secções L5
- [x] Role → tool allowlist
- [x] Audit por step em `injection_meta`
- [x] Métricas: `context_step_duration_ms`, `rag_hit_count`, `compaction_rate`
- [x] Timeout gather 150ms/step; fail-open documentado
- [x] Golden tests antes de remover legado
- [x] `ui_trace` transparente para o utilizador

---

## 14. Plano de implementação — Onda CONTEXT (8 semanas)

### Onda 0 — Fundação (semana 1)

| # | Tarefa | Done |
|---|--------|------|
| 0.1 | Criar pacote `app/context_engine/` (state, policy, registry) | [x] |
| 0.2 | Golden tests baseline `ContextAssembler` / comportamento actual | [x] |
| 0.3 | Implementar `ContextPolicy` + `resolve_policy()` | [x] |
| 0.4 | Wrapper: `ContextPipeline` → usa registry (sem mudança comportamento) | [x] |
| 0.5 | Documentar métricas Prometheus para context steps | [x] |

**Critério de done:** testes verdes; zero regressão no stream.

---

### Onda 1 — GATHER + RAG (semanas 2–3)

| # | Tarefa | Done |
|---|--------|------|
| 1.1 | `RetrievalOrchestrator` com `asyncio.gather` | [x] |
| 1.2 | Steps: SessionRag, DocumentRag, MemoryRecall, ProductRag, Playbook | [x] |
| 1.3 | Gates automáticos (tabela §6.2) | [x] |
| 1.4 | Campo `active_document_id` em meta de sessão/WI | [x] |
| 1.5 | Religar pre-injeção L0 + preferences L2 no pipeline | [x] |
| 1.6 | Deprecar flags HTTP (log only) | [x] |
| 1.7 | Métricas `rag_hit_count` por kind | [x] |

**Critério de done:** session RAG read+write no mesmo request; latência RAG ≤ max(paralelo).

---

### Onda 2 — ASSEMBLE + budget (semana 4)

| # | Tarefa | Done |
|---|--------|------|
| 2.1 | `CompactionStep` único (absorver legado) | [x] |
| 2.2 | tiktoken em `TokenBudgetAllocator` | [x] |
| 2.3 | `SchemaTracker` para tools | [x] |
| 2.4 | `MergeSectionsStep` ordem L0→L7 | [x] |
| 2.5 | `PendingStateStep` (approvals + WI blockers) | [x] |
| 2.6 | Remover `include_long_session_memory` do contrato | [x] |

**Critério de done:** uma política de compactação; golden tests de budget.

---

### Onda 3 — Legado + API (semana 5)

| # | Tarefa | Done |
|---|--------|------|
| 3.1 | Migrar steps restantes de `context.py` | [x] |
| 3.2 | Remover `ContextAssembler` do hot path | [x] |
| 3.3 | Unificar `agent_tree` no mesmo `ContextEngine` | [x] |
| 3.4 | UI: remover checkboxes memória/RAG; expandir `ui_trace` | [ ] |
| 3.5 | OpenAPI: request simplificado §12.1 | [ ] |
| 3.6 | Testes e2e: conversa longa + document upload | [ ] |

**Critério de done:** `context.py` só utils; um entry point `assemble_context()`.

---

### Onda 4 — Multi-dev L2 (semanas 6–7)

| # | Tarefa | Done |
|---|--------|------|
| 4.1 | `work_item_id` no `AssistantTextRequest` + validação tenant | [x] |
| 4.2 | `WorkItemContextStep` (L2) | [x] |
| 4.3 | Role-scoped `ContextPolicy` (RBAC → tools + layers) | [x] |
| 4.4 | Handoff/fork API + audit events | [x] |
| 4.5 | Memory namespace `work_item:{id}` + expiração ao fechar WI | [x] |
| 4.6 | `session_search` com ACL + filtros team | [x] |
| 4.7 | CLI: `central work WI-142` com bootstrap contexto | [ ] |

**Critério de done:** dois devs no mesmo WI com handoff; reviewer sem tools write.

---

### Onda 5 — Coordenação + triggers (semana 8)

| # | Tarefa | Done |
|---|--------|------|
| 5.1 | File lease por WI (`path_prefix`) | [x] |
| 5.2 | Branch sugerida + metadata no WI | [x] |
| 5.3 | Stale diff detection pré-approval | [x] |
| 5.4 | WI-triggered session bootstrap (ci, policy, tool_failure) | [x] |
| 5.5 | Timeline unificada API (WI + session + approval) | [x] |
| 5.6 | DLP no ingest session facts | [x] |
| 5.7 | `ContextPolicy` por tenant em PG | [x] |
| 5.8 | Pentest interno: document upload prompt injection | [ ] |

**Critério de done:** policy.violation → WI → sessão automática; lease impede clobber documentado.

---

## 15. Plano de implementação — Onda AST (H4, paralelo pós-Onda 3)

| # | Tarefa | Done |
|---|--------|------|
| AST-1 | Schema `ast_nodes` + migrations | [x] |
| AST-2 | Parser Python (walk + ast.parse) | [x] |
| AST-3 | Upsert com `source_hash` + hook git | [x] |
| AST-4 | `POST /ast/query` + graph expansion | [x] |
| AST-5 | Tool `ask_project` no Tier-0 | [x] |
| AST-6 | Migrar 10–15 convenções críticas da SKILL | [ ] |
| AST-7 | Testes: query não vaza tenant | [x] |

---

## 16. Plano de implementação — Onda HERMES-ADAPT (pós-Onda 5)

| # | Tarefa | Done |
|---|--------|------|
| H-1 | Vector RAG para tool selection (unificar com `rag.py`) | [x] |
| H-2 | `execute_code` via connector job type | [ ] |
| H-3 | `delegate_task` com `work_item_id` + policy intersect | [ ] |
| H-4 | MCP server registry + policy filter | [ ] |
| H-5 | LSP diagnostics pós-patch (connector) | [ ] |
| H-6 | Environment gates (WI labels → skill relevance) | [x] |

---

## 17. Riscos e mitigações

| Risco | Mitigação |
|-------|-----------|
| Regressão ao remover flags | Golden tests + deprecação com log |
| RAG automático infla tokens | Gates + `rag_char_budget` hard cap |
| Latência gather | Timeout 150ms/step; métricas P95 |
| Handoff vaza contexto entre tenants | RLS + validação WI tenant |
| AST scope creep | Tool-only; review gate em PR |
| Dois sistemas em paralelo prolongado | Onda 3 deadline fixa para remover legado |

---

## 18. Definition of Done — programa completo

- [x] Um único `assemble_context()` no hot path
- [ ] Zero flags `include_*` no contrato público (deprecated, ainda presentes no modelo)
- [x] RAG L5 read+write coerente (session, document, memory)
- [x] WI como L2 quando `work_item_id` presente
- [x] Handoff auditável entre devs
- [x] Role-scoped tools e contexto
- [x] `ContextPolicy` configurável por tenant (PG)
- [ ] Golden + e2e verdes em CI (golden ok, e2e pendente)
- [x] `ui_trace` documentado para UI/CLI
- [x] AST `ask_project` em staging (H4)
- [ ] Pentest document upload sem bypass crítico

---

## 19. Referências de código (baseline)

| Área | Ficheiro |
|------|----------|
| Pipeline actual | `vhosts/CentralChat_Backend/app/context_pipeline.py` |
| Legado | `vhosts/CentralChat_Backend/app/context.py` |
| Assistant routes | `vhosts/CentralChat_Backend/app/assistant_routes.py` |
| RAG | `vhosts/CentralChat_Backend/app/rag.py` |
| Sessões | `vhosts/CentralChat_Backend/app/sessions.py` |
| Work queue | `vhosts/CentralChat_Backend/app/work_queue.py` |
| Session ACL | `vhosts/CentralChat_Backend/app/session_acl.py` |
| Agent trees | `vhosts/CentralChat_Backend/app/agent_tree.py` |
| DLP | `vhosts/CentralChat_Backend/app/shared/dlp_scanner.py` |
| Prompt builders | `vhosts/CentralChat_Backend/app/shared/prompt_injection.py` |

---

*Fonte de verdade para context engine, RAG, multi-dev e agent platform. Actualizar em conclusão de ondas ou novas decisões (secção 1).*
