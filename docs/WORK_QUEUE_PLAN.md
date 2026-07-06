# CentralChat — Work Queue: Plano de Implementação

> **UPDATED:** 2026-06-26  
> **Status:** EM IMPLEMENTAÇÃO — Blocos A,B,C,D,E,F,G,I backend concluídos (19 endpoints). Pendente: C2 blocks, UI badges, WS notifications, webhooks, Bloco H CLI (parcialmente implementado)  
> **Audiência:** engenharia backend (Python), CLI (Go), frontend  
> **Origem:** auditoria do work_queue existente + propostas de melhoria (2026-06-26)

**Ver também:** [`CONTEXT_AND_AGENT_PLATFORM_PLAN.md`](./CONTEXT_AND_AGENT_PLATFORM_PLAN.md) §9 (Work Queue) · [`CLI_RUNTIME_MODES.md`](./CLI_RUNTIME_MODES.md) (TEAM/SOLO) · [`ADMIN_PROFESSIONALIZATION_PLAN.md`](./ADMIN_PROFESSIONALIZATION_PLAN.md) (UI queue/sessions)

---

## CHANGELOG

| Data | Resumo |
|------|--------|
| 2026-06-26 | Revisão Bloco H: comandos CLI já parcialmente implementados; gaps reais identificados (--mine, --agent, comment, SOLO) |
| 2026-06-26 | Documento criado: baseline, gaps, plano de features A–H |

---

## 1. Baseline — o que já existe

### 1.1 Tabelas (PG com RLS)

| Tabela | Colunas | Descrição |
|--------|---------|-----------|
| `work_items` | 19 | id, tenant_id, title, description, status, priority, assignee_id, reporter_id, workspace_path, repo, session_id, approval_ids, labels, source, external_url, external_id, created_at, updated_at, closed_at |
| `work_item_events` | 8 | event_id, tenant_id, work_item_id, actor_id, event_type, from_status, to_status, metadata — log imutável |
| `work_item_comments` | 6 | id, tenant_id, work_item_id, author_id, body, created_at |
| `work_item_counters` | 2 | tenant_id, next_seq — auto-increment WI-{seq} |

### 1.2 Endpoints (10)

| Método | Rota | Descrição | RBAC |
|--------|------|-----------|------|
| `GET` | `/ui/work-items` | Listar (filtro: status, assignee) | — |
| `POST` | `/ui/work-items` | Criar | dev+ |
| `GET` | `/ui/work-items/{id}` | Ler um | — |
| `PATCH` | `/ui/work-items/{id}` | Editar (status, assignee, title, session, priority, external) | dev+ |
| `GET` | `/ui/work-items/{id}/events` | Histórico de eventos | viewer+ |
| `GET` | `/ui/work-items/{id}/comments` | Listar comentários | viewer+ |
| `POST` | `/ui/work-items/{id}/comments` | Adicionar comentário | dev+ |
| `POST` | `/ui/work-items/{id}/link` | Link externo (Linear/Jira/GitHub) | dev+ |
| `POST` | `/ui/work-items/{id}/work` | Criar sessão + marcar in_progress | dev+ |
| `GET` | `/timeline` | Timeline unificada (WI + sessions + approvals) | — |

### 1.3 Funcionalidades existentes

- CRUD completo (delete: soft via status=cancelled)
- Alocação de dev (`assignee_id`, filtrável)
- Auto-sessão (`POST .../work` cria sessão automaticamente)
- Histórico imutável com actor e status transitions
- Auto-WI por rejeição (`maybe_create_work_item_from_denial()`)
- Link externo para Linear/Jira/GitHub
- Tenant RLS em todas as tabelas
- Audit trail em create/close/link
- Integração com ContextEngine (`WorkItemContextStep` injecta WI como L2)

---

## 2. Gaps identificados

| # | Gap | Impacto |
|---|-----|---------|
| G1 | Sem `agent_name` / `skills` no WI | O plano §9.1 promete contexto de agente; não implementado |
| G2 | Sem `repo` no create/patch | Coluna existe mas inacessível via API |
| G3 | Sem busca textual | Só filtra por status e assignee |
| G4 | Sem filtro por label | Labels existem mas não filtráveis |
| G5 | Sem watchers/subscribers | Zero notificações em mudanças de status |
| G6 | Sem `due_date` / deadline | Sem noção de prazo |
| G7 | Sem dependências entre WIs | Bloqueios não modelados |
| G8 | Sem templates | Todos os WIs criados manualmente do zero |
| G9 | Timeline duplicada | `/ui/work-items/{id}/events` vs `GET /timeline` — deviam ser unificados |

---

## 3. Plano de features — 8 blocos (A–H)

### Bloco A — Agente & Contexto

| # | Tarefa | Done |
|---|--------|------|
| A1 | Campo `agent_name` no `work_items` + `WorkItemCreateBody` + `WorkItemPatchBody` | [x] |
| A2 | Campo `skills` (TEXT[]) no `work_items` + create/patch | [x] |
| A3 | Campo `context_links` (TEXT[]) — URLs de docs/KB pre-carregados no contexto | [x] |
| A4 | WorkItemContextStep injecta agent_name + skills como L3 | [x] |
| A5 | Migração PG: adicionar colunas `agent_name`, `skills`, `context_links` | [x] |
| A6 | Testes: WI criado com agente → contexto L3 injectado | [x] |

**Critério de done:** Criar WI com `agent_name: "coder"` → ContextEngine injecta skills do agente no L3.

---

### Bloco B — Planeamento & Estimativa

| # | Tarefa | Done |
|---|--------|------|
| B1 | Campo `due_date` (DATE) no `work_items` + create/patch | [x] |
| B2 | Campo `estimated_hours` (FLOAT) | [x] |
| B3 | Campo `sprint_id` ou `milestone` (TEXT) | [x] |
| B4 | Campo `story_points` (INT, 1/2/3/5/8/13) | [x] |
| B5 | Migração PG: adicionar colunas | [x] |
| B6 | Filtro: `GET /ui/work-items?sprint_id=X` | [x] |

**Critério de done:** WI com due_date aparece ordenado por prazo; filtro por sprint funcional.

---

### Bloco C — Dependências & Bloqueios

| # | Tarefa | Done |
|---|--------|------|
| C1 | Campo `blocked_by` (TEXT[]) — lista de WI IDs | [x] |
| C2 | Campo `blocks` (TEXT[]) — lista de WI IDs bloqueados (denormalized) | [ ] |
| C3 | Status propagation: se A bloqueia B, B não pode → `in_progress` | [x] |
| C4 | Endpoint `GET /ui/work-items/{id}/blocked-by` — resolução de dependências | [x] |
| C5 | UI badge: "🔒 Blocked" na listagem | [ ] |
| C6 | Migração PG + testes | [x] |

**Critério de done:** WI-2 tem `blocked_by: ["WI-1"]` → `POST /work` em WI-2 retorna erro "blocked_by_WI-1".

---

### Bloco D — Templates

| # | Tarefa | Done |
|---|--------|------|
| D1 | Tabela `wi_templates` | [x] |
| D2 | `POST /ui/work-items/templates` — criar template | [x] |
| D3 | `GET /ui/work-items/templates` — listar templates | [x] |
| D4 | `POST /ui/work-items/from-template/{id}` — criar WI a partir de template | [x] |
| D5 | Template defaults: priority, labels, skills preenchidos automaticamente | [x] |

**Critério de done:** Admin cria template "Bug Fix" com `agent: coder, skills: [debugging, testing]`. Dev cria WI a partir do template com 1 clique.

---

### Bloco E — Review & Quality Gates

| # | Tarefa | Done |
|---|--------|------|
| E1 | Campo `reviewer_id` (UUID) no `work_items` | [x] |
| E2 | Campo `required_approvals` (INT DEFAULT 1) — quantos approvals para `done` | [x] |
| E3 | Campo `attached_artifacts` (JSONB) — diffs, PRs, test reports | [x] |
| E4 | Auto-transição: quando `approval_ids` aprovados ≥ `required_approvals` → `done` | [x] |
| E5 | Hook: `POST /ui/work-items/{id}/review` transita para `review` e notifica reviewer | [x] |
| E6 | Badge "👁 Review" na listagem para WIs em `review` | [ ] |

**Critério de done:** WI com `required_approvals: 2` só transita para `done` quando 2 approvals aprovados.

---

### Bloco F — Colaboração

| # | Tarefa | Done |
|---|--------|------|
| F1 | Tabela `wi_watchers` (tenant_id, work_item_id, user_id) | [x] |
| F2 | Notificação em status change — evento no WebSocket TEAM | [x] |
| F3 | Webhook: `POST` para URL externa em status change | [x] |
| F4 | Campo `watchers` no `WorkItemCreateBody` | [x] |
| F5 | Migração PG + testes | [x] |

**Critério de done:** User adicionado como watcher recebe notificação WS quando WI muda de status.

---

### Bloco G — Métricas & Kanban

| # | Tarefa | Done |
|---|--------|------|
| G1 | Endpoint `GET /ui/work-items/metrics/cycle-time` — tempo médio created→done | [x] |
| G2 | Endpoint `GET /ui/work-items/metrics/lead-time?assignee_id=X` | [x] |
| G3 | Endpoint `GET /ui/work-items/metrics/cumulative-flow` — WIs por status/dia | [x] |
| G4 | Campo `sort_order` (INT) para drag-and-drop Kanban | [x] |
| G5 | `PATCH /ui/work-items/reorder` — batch reorder | [x] |
| G6 | `PATCH /ui/work-items/batch` — batch status change | [x] |

**Critério de done:** Dashboard com cycle time médio por assignee visível na UI.

---

### Bloco H — CLI (Go)

| # | Tarefa | Done |
|---|--------|------|
| H1 | `central queue list [--mine] [--status open]` — listar WIs | [x] |
| H2 | `central queue add "título" [--agent name] [--skills a,b] [--priority high]` | [x] |
| H3 | `central queue work WI-142` — abrir/retomar sessão com contexto WI | [x] |
| H4 | `central queue done WI-142` — marcar done | [x] |
| H5 | `central queue assign WI-142 <user-uuid>` — assign via CLI | [x] |
| H6 | `central queue comment WI-142 "texto"` — adicionar comentário | [x] |
| H7 | `central queue show WI-142` — detalhes do WI | [x] |
| H8 | `central queue link WI-142 <url>` — link externo (Linear/Jira) | [x] |
| H9 | Comandos queue funcionam offline (SOLO via SQLite) e online (TEAM via API) | [x] |

**Critério de done:** `central queue list --mine` funciona offline (SOLO) e online (TEAM).

**Notas de implementação:**
- `queue list --mine` extrai `sub` do JWT para filtrar por `assignee_id` no TEAM; em SOLO não há assignee (todos os WIs são do user local).
- `queue add --agent` e `--skills` mapeiam para `agent_name` e `skills` no `WorkItemCreateBody`.
- `queue comment` chama `POST /ui/work-items/{id}/comments`.
- Em SOLO, todos os comandos queue usam `solo.AddWorkItem`/`solo.ListWorkItems`/`solo.UpdateWorkItemStatus` em vez da API.
- O TUI hub (`login_hub.go`) carrega WIs do SQLite em SOLO e da API em TEAM via `loadWorkItemsCmd()`.
- O agente tem acesso à tool `manage_work_item` (ContextLite) para CRUD local em SOLO.

---

### Bloco I — Agent Tools para Work Queue

Tools TIER_0 que permitem ao agente criar, actualizar, listar e reivindicar WIs durante a sessão — fechando o ciclo entre Agent Platform e Work Queue. Isto substitui `delegate_task` como mecanismo de delegação multi-agente, com audit trail persistente, RBAC, e visibilidade humana.

| # | Tarefa | Done |
|---|--------|------|
| I1 | Tool `create_work_item` — agente cria WI (title, description, agent_name?, skills?, priority?, assignee_id?) | [x] |
| I2 | Tool `update_work_item` — agente muda status, assignee, adiciona comment | [x] |
| I3 | Tool `list_work_items` — agente consulta queue (filtro: assignee, status) | [x] |
| I4 | Tool `claim_work_item` — agente pega WI aberto e inicia sessão com contexto WI | [x] |
| I5 | Novo `source: "agent"` — distingue WIs criados por agentes vs humanos | [x] |
| I6 | Tools no TIER_0 — sempre disponíveis para o agente | [x] |
| I7 | Testes: agente cria WI → WI aparece na queue → outro agente pega | [x] |

**Critério de done:** Agente diz "cria um WI para revisão de código" → WI aparece em `GET /ui/work-items` com `source: "agent"`, `agent_name: "reviewer"`.

**Comparação com `delegate_task`:** WI delegation tem audit trail persistente, RBAC, visibilidade na queue, e handoff entre devs — `delegate_task` é efêmero e invisível para humanos.

---

## 4. Ordem de implementação recomendada

```
Semana 1: Bloco A (agente/contexto) — fecha gap prometido no plano §9.1
Semana 2: Bloco C (dependências) — evita trabalho em WIs bloqueados
Semana 3: Bloco D (templates) + Bloco E (quality gates)
Semana 4: Bloco B (estimativa) + Bloco G (métricas)
Semana 5: Bloco F (colaboração) + Bloco H (CLI)
```

---

## 5. Definition of Done — Work Queue completo

- [x] WI criado com agent_name + skills → injectados no ContextEngine L3
- [x] Dependências entre WIs: bloqueio propaga em status transitions
- [x] Templates reutilizáveis por tenant
- [x] Review flow: reviewer atribuído, required_approvals, auto-transição (backend)
- [ ] Notificações WS em status change para watchers
- [x] Métricas: cycle time, lead time (cumulative flow pendente)
- [x] CLI: `central queue` funcional em SOLO e TEAM
- [ ] Search textual por título/descrição
- [x] Filtro por labels, sprint, prioridade
- [ ] Timeline unificada (substitui eventos isolados do work_queue)

---

## 6. Referências de código

| Área | Ficheiro |
|------|----------|
| Work Queue | `vhosts/CentralChat_Backend/app/work_queue.py` |
| ContextEngine WI step | `vhosts/CentralChat_Backend/app/context_engine/steps/resolve/work_item.py` |
| Timeline API | `vhosts/CentralChat_Backend/app/timeline_routes.py` |
| CLI commands | `vhosts/CentralChat_CLI/internal/commands/` |
| Approvals store | `vhosts/CentralChat_Backend/app/shared/approvals_store.py` |

---

*Fonte de verdade para Work Queue. Actualizar em conclusão de blocos.*
