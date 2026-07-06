

# CentralChat CLI — Modos de Runtime: TEAM (híbrido) e SOLO

> **UPDATED:** 2026-06-26  
> **Status:** EM IMPLEMENTAÇÃO — Backend TEAM completo (Python), CLI Go com TeamBackend + WS client + TUI badge.  
> **Pendente:** SOLO-3 polish, TEAM-4 unificação processo, TEAM-5 hardening, audit local, e2e tests  
> **Audiência:** engenharia CLI (Go), backend (Python), product  
> **Relacionado:** `CONTEXT_AND_AGENT_PLATFORM_PLAN.md`, `CONTEXT_SECURITY_AND_TRUST.md`, `CLI_UX_SPEC.md`, `HARDENING_PLAN.md`

---

## CHANGELOG


| Data       | Resumo                                                                                                                |
| ---------- | --------------------------------------------------------------------------------------------------------------------- |
| 2026-06-18 | Documento canónico: modos TEAM (híbrido + performance) e SOLO (autosustentável), runtime único, protocolo, checklists |
| 2026-06-26 | TEAM-0: InferencePlan API + POST /assistant/plan (backend) |
| 2026-06-26 | TEAM-1/2: WebSocket handler, inference-complete, fast path, context push (backend) |
| 2026-06-26 | TEAM-3/5: context_version delta, exposed_root, SHA256, approval flow, gzip (backend) |
| 2026-06-26 | CLI Go: TeamBackend, WS client, AgentRuntime wire, TUI TEAM badge, delta cache, doctor |


---

## 1. Resumo executivo

O binário `central` suporta **dois modos** no mesmo **AgentRuntime**, sem forks de produto:


| Modo     | Utilizador                   | VPS                           | Inferência          | Governação                   |
| -------- | ---------------------------- | ----------------------------- | ------------------- | ---------------------------- |
| **SOLO** | Single-user, offline-capable | Opcional / ausente            | **PC** (in-process) | Local mínima                 |
| **TEAM** | Equipa + enterprise          | **Control plane** obrigatório | **PC** (híbrido)    | VPS: policy, audit, WI, HITL |


**Princípio TEAM (híbrido):** VPS monta contexto e autoriza; **tokens e tools correm no PC** — sensação de inferência local com governação na nuvem.

**Princípio SOLO:** Tudo no PC; versatilidade máxima; sem work queue, RBAC, four-eyes (explícito na UI).

### Decisões aprovadas


| ID          | Decisão                                                                          | Estado                    |
| ----------- | -------------------------------------------------------------------------------- | ------------------------- |
| **D-CLI-1** | Um runtime (`AgentRuntime`); backends `SoloBackend` e `TeamBackend`              | Aprovado                  |
| **D-CLI-2** | TEAM: inferência local + `InferencePlan` do VPS; não stream de tokens via VPS    | Aprovado                  |
| **D-CLI-3** | SOLO: autosustentável em `~/.central/`; sem login obrigatório                    | Aprovado                  |
| **D-CLI-4** | TEAM: WebSocket único substitui poll HTTP de jobs (performance)                  | Aprovado                  |
| **D-CLI-5** | Fast path in-process: tools sem PG quando runtime local serve a sessão           | Aprovado                  |
| **D-CLI-6** | SOLO Fase 1: `central serve --local` (orchestrator loopback); Fase 2: core em Go | Aprovado                  |
| **D-CLI-7** | Bridge opcional: `central sync` entre SOLO e tenant TEAM                         | Aprovado (fase posterior) |


---

## 2. Estado actual (baseline)

```
Hoje (problemático para “local”):

  central ask  ──SSE──► VPS /assistant/text/stream  (inferência no VPS)
  central daemon ──poll 1s──► VPS /connector/jobs   (tools via PG)
  VPS wait_for_job_result: sleep 250ms em loop
```


| Problema                     | Impacto                                    |
| ---------------------------- | ------------------------------------------ |
| Inferência no VPS            | Latência percebida; não parece CLI moderno |
| Poll 1s + PG por tool        | 1–3 s por `read_file`                      |
| Dois processos desconectados | `ask` + `daemon`                           |
| T13 `connector_inference.py` | Protótipo não integrado no CLI             |


**Objectivo TEAM:** primeiro token <200 ms após plano; tool read <50 ms (mesmo host).  
**Objectivo SOLO:** zero hop de rede no hot path (excepto provider LLM).

---

## 3. Arquitectura alvo — runtime único

```
┌──────────────────────────────────────────────────────────────────┐
│                     central (TUI + AgentRuntime)                  │
│                                                                   │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │ Inference   │  │ Tool loop    │  │ Session / memory (iface) │ │
│  │ Engine      │  │ (in-process) │  │                          │ │
│  └──────┬──────┘  └──────┬───────┘  └────────────┬─────────────┘ │
│         │                │                        │               │
│         └────────────────┼────────────────────────┘               │
│                          ▼                                        │
│              ┌───────────────────────┐                              │
│              │   RuntimeBackend      │                              │
│              │   (interface Go)      │                              │
│              └───────────┬───────────┘                              │
│            ┌───────────────┴───────────────┐                        │
│            ▼                               ▼                        │
│   ┌─────────────────┐           ┌─────────────────┐              │
│   │  SoloBackend    │           │  TeamBackend    │              │
│   │  loopback/local │           │  VPS + WS       │              │
│   └─────────────────┘           └─────────────────┘              │
└──────────────────────────────────────────────────────────────────┘
```

### Selecção de modo

```toml
# ~/.central/config.toml

[runtime]
mode = "solo"   # "solo" | "team"

[team]
api_url = "https://api.example.com"
# token via login / device code / api key

[solo]
# provider keys via OS keychain ou env
provider = "openrouter"  # openrouter | ollama | custom
ollama_url = "http://127.0.0.1:11434"
data_dir = "~/.central"
```

**Regras de boot:**

1. `mode = solo` → `SoloBackend` (ignora token TEAM se ausente).
2. `mode = team` sem token válido → ecrã login (`CLI_UX_SPEC` §2).
3. `CENTRAL_API_URL` unset + sem config → default `solo`.

---

## 4. Modo TEAM (híbrido + performance)

### 4.1 Divisão control plane / data plane

```
┌──────────────── VPS (control plane) ─────────────────┐
│ Auth · RBAC · ContextEngine · Policy · Approvals      │
│ Work queue · Audit · Quota · RAG (pgvector)           │
│                                                       │
│ Output: InferencePlan (+ deltas)                        │
└────────────────────────┬──────────────────────────────┘
                         │ WebSocket (1 conexão persistente)
                         ▼
┌──────────────── PC (data plane) ───────────────────────┐
│ Chave API LLM (keychain) · stream tokens → TUI         │
│ Tools in-process · context cache quente (opcional)   │
│ Report: inference_complete · tool_audit · job results  │
└──────────────────────────────────────────────────────┘
```

### 4.2 Fluxo de um turno TEAM

```
1. User envia mensagem na TUI
2. TeamBackend → WS: assistant_turn { text, session_id, work_item_id?, ... }
3. VPS: policy check → ContextEngine.assemble() → InferencePlan
4. VPS → WS: inference_plan { request_id, messages[], tools[], model, caps, policy_digest }
5. AgentRuntime: chama provider LOCAL (OpenRouter/Ollama) com stream
6. Tokens → TUI directamente (VPS não vê cada token)
7. Se tool_call:
     a. Fast path: executor in-process (sem PG)
     b. Se write sensível: VPS pode exigir approval antes de executar
8. Tool results → próximo passo do loop (local ou WS tool_result sync)
9. Fim do turno → WS: turn_complete { usage, reply_hash, tool_summary }
10. VPS: audit, quota, append session, session RAG ingest, WI events
```

### 4.3 InferencePlan (contrato VPS → CLI)

```json
{
  "schema": "inference_plan/v1",
  "request_id": "req-abc123",
  "chat_session_id": "sess-xyz",
  "work_item_id": "WI-142",
  "model": {
    "model_id": "openai/gpt-4o-mini",
    "profile": "balanced",
    "max_tokens": 8192,
    "temperature": 0.7
  },
  "messages": [ { "role": "system", "content": "..." }, "..." ],
  "tools": [ { "type": "function", "function": { "name": "read_file", "..." } } ],
  "policy_digest": {
    "sha256": "...",
    "allowed_write_paths": ["src/"],
    "denied_tools": [],
    "requires_approval_for": ["file.write", "file.patch", "shell.exec"]
  },
  "context_meta": {
    "layers": ["L0", "L1", "L2", "L4", "L5", "L6"],
    "ui_trace_summary_pt": "..."
  },
  "delta": {
    "base_version": 12,
    "append_messages": []
  }
}
```

- **Turno 1:** plano completo.  
- **Turnos seguintes:** `delta` quando `context_version` coincide (menos rede).

### 4.4 WebSocket — transporte único (substitui poll)

**Endpoint:** `wss://{api}/connector/v1/ws` (autenticado JWT).


| Direcção | Tipo                | Prioridade | Descrição                    |
| -------- | ------------------- | ---------- | ---------------------------- |
| CLI→VPS  | `assistant_turn`    | P0         | Novo turno user              |
| CLI→VPS  | `tool_result`       | P0         | Resultado de tool            |
| CLI→VPS  | `turn_complete`     | P1         | Usage + fim de turno         |
| CLI→VPS  | `heartbeat`         | P2         | TTL connector                |
| CLI→VPS  | `context_push`      | P2         | Git branch, active file (L2) |
| VPS→CLI  | `inference_plan`    | P0         | Plano autorizado             |
| VPS→CLI  | `approval_required` | P0         | HITL card                    |
| VPS→CLI  | `policy_denied`     | P0         | Bloqueio com mensagem PT     |
| VPS→CLI  | `ping`              | P2         | Keepalive                    |


**Eliminado no TEAM moderno:** `GET /connector/jobs` poll 1s para sessão activa do mesmo host.

Jobs PG mantêm-se para: web+connector remoto, writes async pós-approval, retries.

### 4.5 Fast path in-process (performance crítica)

Quando `TeamBackend` deteta `connector_id` da sessão == runtime local:


| Acção                     | Hoje                          | TEAM alvo                |
| ------------------------- | ----------------------------- | ------------------------ |
| `read_file`               | PG job + poll 1s + wait 250ms | `executor.Exec` directo  |
| `grep`                    | idem                          | idem                     |
| `shell` (se policy allow) | idem                          | idem + approval gate VPS |
| Latência típica           | 1–3 s                         | **<50 ms**               |


PG jobs reservados para: outro connector, fila de approval, web client.

### 4.6 Metas de performance TEAM


| Métrica                     | Actual                | Meta                                     |
| --------------------------- | --------------------- | ---------------------------------------- |
| Primeiro token (após Enter) | 500 ms–2 s+ (VPS LLM) | **<200 ms** após plano (só rede plano)   |
| `read_file` mesmo host      | 1–3 s                 | **<50 ms** p95                           |
| Reconexão WS                | N/A                   | **<2 s**; retoma sessão                  |
| Tamanho plano turno N+1     | full                  | **delta** quando possível (>50% redução) |


### 4.7 O que permanece no VPS (TEAM)

- ContextEngine completo (`CONTEXT_AND_AGENT_PLATFORM_PLAN.md`)
- Policy engine (deny > break-glass > allow)
- Approvals / four-eyes / PR-only
- Work queue, session ACL, handoff
- Audit + SIEM + quota
- RAG pgvector (team namespaces)
- Model allowlist global + tenant

### 4.8 Chaves e inferência

- **Chave OpenRouter/Ollama:** keychain local (`secret-service` / Keychain / cred manager).
- VPS **nunca** recebe a chave; só `model_id` permitido no plano.
- `turn_complete` reporta `usage` para quota — confiança com audit de modelo declarado.

---

## 5. Modo SOLO (autosustentável)

### 5.1 Propósito

- Dev individual, repo pessoal, offline (excepto chamada ao provider LLM).
- **Sem** dependência de VPS para funcionar.
- UI mostra badge: `[SOLO — governação local]`.

### 5.2 O que SOLO inclui


| Capacidade          | Implementação                                  |
| ------------------- | ---------------------------------------------- |
| Chat + stream       | Provider local (Ollama/OpenRouter)             |
| Tool loop           | `internal/executor` in-process                 |
| Sessões             | `~/.central/sessions/` (SQLite ou JSONL)       |
| Memória             | `~/.central/memory.db` (sqlite-vec opcional)   |
| Skills / agents     | `~/.central/skills/`, `~/.central/agents.yaml` |
| Contexto L0–L6      | Subconjunto local (sem WI, sem team rules PG)  |
| Compactação         | Local + summary em SQLite                      |
| Policy mínima       | `~/.central/policy.yaml` + denylist shell      |
| Audit               | `~/.central/audit.jsonl` (exportável)          |
| AST / ask_project   | Parser local + sqlite (fase AST)               |
| Workspace multi-tab | `CLI_UX_SPEC`                                  |


### 5.3 O que SOLO não inclui (por desenho)


| Capacidade TEAM          | SOLO                                          |
| ------------------------ | --------------------------------------------- |
| Multi-tenant / RBAC      | —                                             |
| Work queue / WI          | Todo local opcional (`~/.central/todos.json`) |
| Approvals enterprise     | Confirmação TUI simples (“aplicar patch?”)    |
| Policy PG bundles        | YAML local                                    |
| Session ACL / handoff    | —                                             |
| Git PR-only / GitHub App | git local                                     |
| OIDC / Keycloak          | —                                             |
| SIEM / retenção 1 ano    | log local                                     |
| Connector poll / PG jobs | in-process apenas                             |


### 5.4 Arquitectura SOLO — duas fases de implementação

#### Fase SOLO-1: loopback (reuso Python, entrega rápida)

```
central (Go TUI)
  └── SoloBackend
        └── subprocess: central serve --local
              └── FastAPI 127.0.0.1:{port}
                    ├── ContextPipeline (local adapters)
                    ├── /assistant/text/stream
                    └── tools → executor via IPC ou shared workspace
```

- **Prós:** reutiliza `ContextEngine` Python; um comando `central` para o user.
- **Contras:** dois processos; latência IPC aceitável em localhost.

#### Fase SOLO-2: nativo Go (performance máxima)

```
central (Go)
  └── SoloBackend
        ├── context-lite (Go) — L0,L1,L3,L6
        ├── inference (HTTP → Ollama/OpenRouter)
        └── executor (já existe)
```

- Portar gradualmente steps do `ContextEngine`; Python loopback como fallback.

### 5.5 Layout `~/.central/`

```
~/.central/
├── config.toml
├── policy.yaml
├── sessions/
│   └── {session_id}.jsonl
├── memory.db
├── audit.jsonl
├── skills/
├── agents.yaml
├── cache/
│   └── embeddings/
└── state/
    └── daemon.pid          # SOLO-1: serve --local
```

### 5.6 Metas de performance SOLO


| Métrica                       | Meta                                       |
| ----------------------------- | ------------------------------------------ |
| Boot até TUI                  | **<1.5 s**                                 |
| Primeiro token (Ollama local) | **<100 ms** após prompt ready              |
| `read_file`                   | **<10 ms** p95                             |
| Offline (sem provider)        | TUI + histórico + edição; banner “sem LLM” |


---

## 6. Comparativo TEAM vs SOLO


| Dimensão          | SOLO                   | TEAM                     |
| ----------------- | ---------------------- | ------------------------ |
| Login             | Opcional               | Obrigatório              |
| Rede no hot path  | Só provider LLM        | Plano VPS + provider LLM |
| Onde corre LLM    | PC                     | PC (híbrido)             |
| Contexto completo | Local lite             | VPS ContextEngine        |
| Writes perigosos  | Confirm local          | HITL + policy            |
| Multi-dev         | Não                    | Sim                      |
| Audit             | Ficheiro local         | PG + SIEM                |
| Ideal para        | Uso pessoal, protótipo | Empresa, piloto          |


---

## 7. Bridge SOLO ↔ TEAM (`central sync`)

Fase posterior; permite adoptar TEAM sem perder histórico SOLO.

```bash
central sync push --tenant my-org    # sessões + memory local → VPS (opt-in)
central sync pull --rules            # team rules aprovadas → ~/.central/skills/
```

- Conflitos: last-write-wins com audit; nunca auto-push de secrets.

---

## 8. Segurança por modo

### TEAM


| Controlo                             | Onde                             |
| ------------------------------------ | -------------------------------- |
| JWT + tenant RLS                     | VPS                              |
| InferencePlan assinado (futuro: JWS) | VPS emite; CLI valida            |
| `policy_digest` no plano             | CLI verifica antes de tool write |
| `exposed_root` no registo connector  | CLI                              |
| SHA256 em file reads                 | CLI → VPS context                |
| mTLS connector (fase C3)             | Transporte                       |


### SOLO


| Controlo                | Onde              |
| ----------------------- | ----------------- |
| Workspace path guard    | CLI executor      |
| Shell denylist          | CLI executor      |
| Confirmação patch/write | TUI               |
| DLP opcional            | CLI pré-prompt    |
| Sem four-eyes           | **Disclosure UI** |


---

## 9. Impacto na UI (`CLI_UX_SPEC`)


| Ecrã        | SOLO                   | TEAM                                  |
| ----------- | ---------------------- | ------------------------------------- |
| Splash boot | `API: local`           | `API: {host}` + WS status             |
| Login       | Skip ou opcional       | Obrigatório                           |
| Daemon gate | `serve --local` auto   | AgentRuntime WS (sem daemon separado) |
| Sidebar     | `[SOLO]` badge         | `[TEAM]` + connector ●                |
| `/doctor`   | local providers + disk | + VPS ready + WS + policy             |


**Mudança UX TEAM:** fundir `central daemon` no processo principal — eliminar “daemon gate” como processo externo obrigatório.

---

## 10. Estrutura de código alvo (Go)

```
vhosts/CentralChat_CLI/
├── internal/
│   ├── runtime/
│   │   ├── agent.go              # AgentRuntime: loop inferência + tools
│   │   ├── backend.go            # interface RuntimeBackend
│   │   ├── solo_backend.go
│   │   └── team_backend.go
│   ├── inference/
│   │   ├── provider.go           # OpenRouter, Ollama
│   │   └── stream.go
│   ├── ws/
│   │   ├── client.go             # TEAM WebSocket
│   │   └── messages.go           # tipos protocolo
│   ├── executor/                 # (existente)
│   └── solo/
│       ├── store.go              # ~/.central sessions
│       └── serve.go              # SOLO-1 subprocess manager
```

**Backend Python (TEAM):**

```
vhosts/CentralChat_Backend/app/
├── http/ws_connector.py          # WebSocket handler (novo)
├── inference_plan.py             # build + sign InferencePlan (novo)
└── assistant_routes.py           # legado SSE; deprecar para CLI TEAM
```

---

## 11. Plano de implementação — SOLO

### SOLO-0 — Fundação config (semana 1)


| #    | Tarefa                                        | Done |
| ---- | --------------------------------------------- | ---- |
| S0.1 | `~/.central/config.toml` com `runtime.mode`   | [x] |
| S0.2 | `central doctor` detecta modo e paths         | [x] |
| S0.3 | Badge `[SOLO]` na TUI                         | [x] |
| S0.4 | Boot sem API_URL → solo default               | [x] |


### SOLO-1 — Loopback local (semanas 2–3)


| #    | Tarefa                                        | Done |
| ---- | --------------------------------------------- | ---- |
| S1.1 | `central serve --local` (FastAPI 127.0.0.1)   | [x] |
| S1.2 | `SoloBackend` arranca/serve subprocesso       | [x] |
| S1.3 | TUI `AskStream` → loopback em modo solo       | [x] |
| S1.4 | Sessões em `~/.central/sessions/`             | [x] |
| S1.5 | Provider Ollama + OpenRouter via env/keychain | [x] |
| S1.6 | Policy YAML mínima + confirmação write        | [x] |
| S1.7 | `audit.jsonl` local                           | [ ] |


**Done:** `central` funciona sem VPS; chat + tools + sessões.

### SOLO-2 — Nativo Go (semanas 4–6)


| #    | Tarefa                                           | Done |
| ---- | ------------------------------------------------ | ---- |
| S2.1 | `AgentRuntime` em Go (inferência + tool loop)    | [x] |
| S2.2 | Context-lite L0,L1,L3,L6 em Go                   | [x] |
| S2.3 | Memória SQLite local                             | [ ] |
| S2.4 | Remover dependência subprocess (flag `--native`) | [ ] |
| S2.5 | Testes offline boot                              | [ ] |


### SOLO-3 — Polish (semana 7)


| #    | Tarefa                               | Done |
| ---- | ------------------------------------ | ---- |
| S3.1 | `/model` com Ollama model list local | [ ]  |
| S3.2 | Export/import sessão                 | [ ]  |
| S3.3 | Documentação utilizador SOLO         | [ ]  |


---

## 12. Plano de implementação — TEAM (híbrido + performance)

### TEAM-0 — InferencePlan API (semana 1–2)


| #    | Tarefa                                    | Done |
| ---- | ----------------------------------------- | ---- |
| T0.1 | Schema `InferencePlan` Pydantic + OpenAPI           | [x] |
| T0.2 | `POST /assistant/plan` (sync, sem LLM)              | [x] |
| T0.3 | `policy_digest` no plano                            | [x] |
| T0.4 | Testes: plano respecta RBAC + policy                | [x] |


### TEAM-1 — Inferência local no CLI (semanas 2–3)


| #    | Tarefa                                            | Done |
| ---- | ------------------------------------------------- | ---- |
| T1.1 | `TeamBackend` pede plano antes de inferir | [x] |
| T1.2 | `internal/inference` stream OpenRouter/Ollama | [x] |
| T1.3 | Tool loop local consumindo `tools[]` do plano | [x] |
| T1.4 | `POST /connector/inference-complete` (usage) | [x] |
| T1.5 | TUI tokens do runtime local (não SSE VPS) | [x] |
| T1.6 | Fallback `inference_destination=api` (SSE legado) | [ ] |


**Done:** tokens locais; VPS só plano + audit.

### TEAM-2 — WebSocket + fast path (semanas 3–5)


| #    | Tarefa                                            | Done |
| ---- | ------------------------------------------------- | ---- |
| T2.1 | `wss://.../connector/v1/ws` handler FastAPI       | [x]  |
| T2.2 | Mensagens: turn, plan, tool_result, turn_complete | [x]  |
| T2.3 | Go `ws/client.go` com reconnect | [x] |
| T2.4 | Fast path: tools sem PG para sessão local         | [x]  |
| T2.5 | Deprecar poll para sessão WS activa               | [ ]  |
| T2.6 | Context push L2 no mesmo WS                       | [x]  |
| T2.7 | Métricas: `plan_latency_ms`, `first_token_ms`     | [ ]  |


**Done:** read_file <50 ms; sem poll 1s.

### TEAM-3 — Delta context + rigidez (semanas 5–6)


| #    | Tarefa                                       | Done |
| ---- | -------------------------------------------- | ---- |
| T3.1 | `context_version` + `delta` no InferencePlan | [x] |
| T3.2 | Cache plano no CLI entre turnos | [x] |
| T3.3 | `exposed_root` no register + validação path | [x] |
| T3.4 | SHA256 em results de `file.read` | [x] |
| T3.5 | Approval flow via WS `approval_required` | [x] |


### TEAM-4 — Unificação processo (semana 7)


| #    | Tarefa                                                     | Done |
| ---- | ---------------------------------------------------------- | ---- |
| T4.1 | Remover `central daemon` como comando separado obrigatório | [ ]  |
| T4.2 | `AgentRuntime` único no processo TUI                       | [ ]  |
| T4.3 | `CLI_UX_SPEC` actualizado (daemon gate → WS status)        | [ ]  |
| T4.4 | e2e: login → workspace → ask → tool → approval             | [ ]  |


### TEAM-5 — Performance hardening (semana 8)


| #    | Tarefa                                              | Done |
| ---- | --------------------------------------------------- | ---- |
| T5.1 | Benchmarks CI: plan latency, first token, read_file | [ ]  |
| T5.2 | PG NOTIFY para jobs remotos (opcional)              | [ ]  |
| T5.3 | Compressão gzip em planos grandes | [x] |
| T5.4 | Pentest: plano forjado rejeitado no CLI             | [ ]  |


---

## 13. Ordem de execução recomendada

```
Paralelo possível:
  SOLO-0 ──► SOLO-1 ──► SOLO-2     (versatilidade pessoal)
  TEAM-0 ──► TEAM-1 ──► TEAM-2     (piloto enterprise)

Convergência:
  AgentRuntime Go partilhado entre SOLO-2 e TEAM-1
  executor/ partilhado (já existe)

Posterior:
  central sync (bridge)
  mTLS + JWS signed plans
```

---

## 14. Definition of Done — programa CLI

### SOLO

- [x] `central` arranca sem VPS e completa turno com tools
- [x] Sessões persistem em `~/.central/`
- [x] Badge `[SOLO]` visível
- [x] Ollama e OpenRouter funcionam
- [ ] Audit local exportável

### TEAM

- [x] Tokens stream no PC; VPS não proxy de tokens
- [x] InferencePlan com policy_digest
- [x] WebSocket activo; poll desactivado para sessão local
- [ ] `read_file` p95 <50 ms mesmo host (fast path existe, não medido)
- [x] Approvals via WS
- [ ] Um processo (sem daemon separado)
- [ ] Fallback API mode documentado

---

## 15. Referências de código (baseline)


| Componente      | Path                                                        |
| --------------- | ----------------------------------------------------------- |
| CLI TUI + ask   | `vhosts/CentralChat_CLI/internal/ui/app.go`                 |
| CLI API client  | `vhosts/CentralChat_CLI/internal/api/client.go`             |
| Daemon poll     | `vhosts/CentralChat_CLI/internal/commands/daemon.go`        |
| Executor        | `vhosts/CentralChat_CLI/internal/executor/runner.go`        |
| Connector jobs  | `vhosts/CentralChat_Backend/app/connector.py`               |
| Connector HTTP  | `vhosts/CentralChat_Backend/app/http/router_connector.py`   |
| Inference proto | `vhosts/CentralChat_Backend/scripts/connector_inference.py` |
| Job wait        | `vhosts/CentralChat_Backend/app/file_change_service.py`     |


---

## 16. Referências cruzadas


| Documento                            | Secção relevante           |
| ------------------------------------ | -------------------------- |
| `CONTEXT_AND_AGENT_PLATFORM_PLAN.md` | ContextEngine, WI, L0–L7   |
| `CLI_UX_SPEC.md`                     | TUI, daemon gate, `/model` |
| `HARDENING_PLAN.md`                  | Policy, audit, OIDC        |
| `MVP_REPOSITIONING.md`               | Work queue §8              |


---

*Fonte de verdade para modos CLI TEAM e SOLO. Actualizar em conclusão de fases ou novas decisões (§1).*