# CentralChat — Sistema de Contexto: Atual vs Proposto

> Documento de design com plano de implementação em fases. 2026-06-08.  
> **UPDATED:** 2026-06-18 — plano de execução e decisões consolidadas em [`CONTEXT_AND_AGENT_PLATFORM_PLAN.md`](./CONTEXT_AND_AGENT_PLATFORM_PLAN.md) (fonte de verdade).

---

## PARTE 1: Sistema Atual

### 1.1 Visão geral

Dois sistemas de contexto coexistem e se sobrepõem:

| Sistema | Arquivo | Linhas | Usado por |
|---------|---------|--------|-----------|
| ContextAssembler | `app/context.py` | 2493 | Chat normal (`/assistant/text`) |
| ContextEngine | `app/context_engine.py` | 759 | Agent trees + `agent_name` definido |

### 1.2 Fluxo completo do ContextAssembler

```
POST /assistant/text
│
├─ 1. _resolved_assistant_payload()
│     Aplica defaults salvos (assistant_preferences.json)
│
├─ 2. _apply_chat_session_history()
│     Se CHAT_SESSIONS_ENABLED: carrega histórico do event log
│     Senão: usa history do payload
│
├─ 3. ContextAssembler.build()
│   │
│   ├─ 3a. normalize_raw_history()
│   │      Normaliza roles, strip thinking tags
│   │
│   ├─ 3b. compact_conversation_history()
│   │      ┌─────────────────────────────────────────┐
│   │      │ Se include_long_session_memory=true:    │
│   │      │   Eco-summary SINCRONO (aux_llm):       │
│   │      │   Resume 60% antigas → insere summary   │
│   │      │   Mantém 40% recentes intactas          │
│   │      │                                         │
│   │      │ Senão:                                  │
│   │      │   Trunca para SESSION_MAX_MESSAGES      │
│   │      │   (corta as mais antigas)               │
│   │      └─────────────────────────────────────────┘
│   │
│   ├─ 3c. apply_multislot_context()
│   │      [Se WIDGET_MULTI_SLOT_ENABLED]
│   │      Particiona histórico por slot
│   │
│   ├─ 3d. build_prefix_sections()
│   │      ⚠️ Execução SEQUENCIAL — cada passo espera o anterior.
│   │      │
│   │      ├── System Prompt Injection (L6 anchor + product pack + bundled + overlay)
│   │      ├── Pre-injection ([SYSTEM] env info)
│   │      ├── Multi-slot system message
│   │      ├── Capability Digest (lista de tools em TEXTO)
│   │      ├── User Preferences (L2)
│   │      ├── Host Context (se trigger)
│   │      ├── Memory Recall (pgvector — project + prefs namespaces)
│   │      ├── Document RAG (pgvector — por doc_id)
│   │      ├── Session RAG (pgvector — por session_id)
│   │      ├── Product RAG (pgvector — SEMPRE ativo)
│   │      └── Playbook (token-matching local)
│   │
│   ├─ 3e. slim_injected_history_for_router()
│   │      TRIM: corta mensagens/chars que excedem caps do router
│   │
│   └─ 3f. TokenBudgetAllocator.build_accounting()
│          Estima tokens (chars/4 — heurística)
│
├─ 4. [Se agent_name definido] T15 ContextEngine.assemble()
│     Pipeline paralelo: 7+1 camadas com cache LRU
│     ⚠️ Duplica RAG, system prompt, tool digest do ContextAssembler
│
├─ 5. LLM Call
│     Se use_agent_tools=true:
│       build_agent_tools_protocol_text() → 
│       injeta [PROTOCOLO_AGENT_TOOLS] como TEXTO (string gigante)
│     Senão:
│       call_llm() direto
│
└─ 6. Pós-processamento
      Async summarization: se tokens > 80% → thread background
      Cache in-memory (volátil)
```

### 1.3 Problemas estruturais identificados

| # | Problema | Impacto |
|---|----------|---------|
| P1 | 2 sistemas de contexto duplicados | ~3250 linhas mantendo 70% de overlap |
| P2 | 4 chamadas RAG sequenciais | Latência acumulada: memory → document → session → product |
| P3 | Product RAG incondicional | Executa até em "Olá, tudo bem?" |
| P4 | Eco-summary síncrono | Bloqueia a request esperando aux_llm |
| P5 | Tool injection como texto | String `[PROTOCOLO_AGENT_TOOLS]` gigante em vez de tools[] nativas |
| P6 | 25 schemas de tools injetados | 4500 tokens fixos por request |
| P7 | Summarization cache volátil | In-memory → perde no restart |
| P8 | Token budget chars/4 | Heurística com até 30% de erro |
| P9 | Agent trees em endpoint separado | SSE, contexto, tools — tudo duplicado |
| P10 | Canvas sem wire-up | `htmlContent = ""` forever |

---

## PARTE 2: Sistema Proposto

### 2.1 Arquitetura: ContextPipeline (sistema único)

```
┌─────────────────────────────────────────────────────────────┐
│                    ContextPipeline                          │
│                                                             │
│  Entrada: user_text, session_id, agent_name (opcional)     │
│  Saída:  messages[], tools[], model_config                  │
│                                                             │
│  ┌──────────────────────────────────────────────────┐      │
│  │ FASE 1: GATHER (async paralelo, ~120ms)         │      │
│  │                                                  │      │
│  │  load_history   load_summary   load_agent_config │      │
│  │       │              │               │           │      │
│  │  ┌────┴────┐         │               │           │      │
│  │  │  RAG    │ ← ─ ─ ─ ┘               │           │      │
│  │  │ memory  │                         │           │      │
│  │  │ session │  (só se keywords)       │           │      │
│  │  │ product*│                         │           │      │
│  │  └─────────┘                         │           │      │
│  │       │                              │           │      │
│  │  select_tools (RAG-driven)   build_tool_schemas │      │
│  │       │                              │           │      │
│  │       └──────────────┬───────────────┘           │      │
│  │                      │                           │      │
│  │  Todas as tasks rodam em asyncio.gather()        │      │
│  └──────────────────────────────────────────────────┘      │
│                         │                                   │
│                         ▼                                   │
│  ┌──────────────────────────────────────────────────┐      │
│  │ FASE 2: ASSEMBLE (sequencial, <5ms)              │      │
│  │                                                  │      │
│  │  1. Compose system layers (L1-L4)                │      │
│  │  2. Merge RAG results (dedup, rank)              │      │
│  │  3. Compact history + inject summary              │      │
│  │  4. Track tool schemas (evitar re-injeção)       │      │
│  │  5. Apply token budget (tiktoken)                 │      │
│  │  6. Trim to context window                        │      │
│  │  7. Build final messages[] + tools[]              │      │
│  └──────────────────────────────────────────────────┘      │
│                         │                                   │
│                         ▼                                   │
│  ┌──────────────────────────────────────────────────┐      │
│  │ FASE 3: POST-PROCESS (background, não bloqueia)  │      │
│  │                                                  │      │
│  │  summarize_session (async)    audit_log          │      │
│  │  canvas_update (SSE)                             │      │
│  └──────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Política de Injeção de Tools (RAG-driven + rastreamento de esquemas)

#### Catálogo vs Schema

```
CATÁLOGO (sempre presente, ~30 tokens):
  "Ferramentas disponíveis: read_file, search_files, terminal, 
   patch, write_file, execute_code, delegate_task, browser_*, 
   vision_analyze, cronjob, process, clarify, memory, 
   session_search, skill_manage, skill_view, todo, ask_project"

SCHEMA (injetado sob demanda, ~180 tokens cada):
  {
    "type": "function",
    "function": {
      "name": "patch",
      "description": "Targeted find-and-replace edits...",
      "parameters": { ... }  ← JSON Schema completo
    }
  }
```

#### Algoritmo de seleção

```python
async def select_tools(user_text, history, active_schemas):
    """
    1. RAG: embedding da tarefa → cos-similarity contra todas as tools
    2. Keyword match: bónus se a pergunta contém trigger words da tool
    3. Top-5 por score + Tier 0 obrigatórias (ask_project, memory)
    4. Filtra as que JÁ têm schema ativo no contexto
    5. Retorna SÓ schemas novos
    """
    
    # Embedding da tarefa atual
    task = " ".join(h[-1]["content"] for h in history[-3:]) + " " + user_text
    task_vec = embed(task)
    
    candidates = []
    for name, tool in TOOL_REGISTRY.items():
        score = cosine_similarity(task_vec, tool.embedding)
        score += sum(0.2 for kw in tool.triggers if kw in task.lower())
        candidates.append((name, score))
    
    candidates.sort(key=lambda x: x[1], reverse=True)
    
    # Top-5 + Tier 0
    needed = TIER_0 | {name for name, _ in candidates[:5]}
    
    # Filtra schemas já presentes
    missing = {name for name in needed 
               if not is_schema_in_context(name, active_schemas)}
    
    # Injeta SÓ os que faltam
    return [TOOL_REGISTRY[name].schema for name in missing]
```

#### Rastreamento de esquemas ativos

```
Cada schema injetado é marcado com ID rastreável:

[TOOL_SCHEMA:id=b4f2|tool=patch]
{... schema completo ...}
[/TOOL_SCHEMA:id=b4f2]

O rastreador verifica se o marcador ainda está em current_messages.
Se saiu (por compactação/trim), reinjeta na próxima vez que o RAG selecionar.
```

#### Exemplo de ciclo de vida

```
Turno 1: "Lê user_config.py"
  RAG: read_file, search_files ← relevantes
  Contexto atual: vazio
  Injeta: read_file (180 tokens) + search_files (180 tokens) + Tier 0 (210 tokens)
  Total: 570 tokens em tool schemas

Turno 3: "Agora procura por endpoints nesse ficheiro"
  RAG: search_files, read_file ← relevantes
  Contexto atual: read_file ✓ presente, search_files ✓ presente
  Injeta: NADA
  Total: 0 tokens em tool schemas
  
Turno 31: Conversa muito longa, compactação removeu schemas
  RAG: patch, write_file ← relevantes (tarefa de edição)
  Contexto atual: schemas saíram
  Injeta: patch (180 tokens) + write_file (180 tokens)
  Total: 360 tokens em tool schemas
```

#### Economia de tokens

| Cenário | Atual (25 schemas) | Proposto (RAG-driven) | Ganho |
|---------|-------------------|----------------------|-------|
| "Olá, tudo bem?" | 4500 | 210 (só Tier 0) | **95%** |
| Leitura de código | 4500 | 850 (5 schemas) | **81%** |
| Edição de ficheiros | 4500 | 950 (5 schemas) | **79%** |
| Debug complexo | 4500 | 1440 (8 schemas) | **68%** |
| Turno com schemas já ativos | 4500 | 0 | **100%** |

### 2.3 Gestão de Contexto Unificada (compact + summary)

Em vez de dois mecanismos separados, um único `ContextWindowManager`:

```python
class ContextWindowManager:
    """
    Estratégia adaptativa única:
    
    1. Se history cabe nos tokens disponíveis → retorna intacto
    2. Se não cabe → sumarização progressiva:
       a. Resume bloco mais antigo (aux_llm)
       b. Insere summary + mantém recentes
       c. Se ainda não cabe → resume o summary (progressivo)
    3. Summaries persistidos no session_summaries (Postgres)
    4. Checkpoints a cada N mensagens, não a cada request
    """
```

**Summarization progressiva**:

```
Mensagens 0-50:   checkpoint → summary_v1 (300 palavras)
Mensagens 0-100:  checkpoint → summary_v2 = f(summary_v1 + msgs 51-100)
Mensagens 0-200:  checkpoint → summary_v3 = f(summary_v2 + msgs 101-200)

O modelo sempre vê: summary_N + últimas K mensagens intactas.
```

### 2.4 RAG Paralelo

```python
async def gather_rag(user_text, session_id, doc_id=None):
    """Todas as queries RAG em paralelo."""
    
    tasks = [
        rag_query("memory", user_text),
        rag_query("session", session_id, user_text),
    ]
    
    # Product RAG só se keywords indicam necessidade
    if has_product_keywords(user_text):
        tasks.append(rag_query("product", user_text))
    
    # Document RAG só se doc_id presente
    if doc_id:
        tasks.append(rag_query("document", doc_id, user_text))
    
    results = await asyncio.gather(*tasks)
    return merge_and_rank(results)
```

| Abordagem | Latência |
|-----------|----------|
| Atual (sequencial) | memory(120) + doc(80) + session(90) + product(100) = **390ms** |
| Proposta (paralela) | max(120, 80, 90, 100) = **120ms** |

---

## PARTE 3: Plano de Implementação em Fases

### Fase 1 — Fundação (substitui ContextAssembler)
**Objetivo**: Pipeline único funcional, sem quebrar o existente.

| Tarefa | Descrição |
|--------|-----------|
| F1.1 | Criar `app/context_pipeline.py` com `ContextPipeline` |
| F1.2 | Feature flag `CONTEXT_PIPELINE_ENABLED` — coexiste com legacy |
| F1.3 | Migrar system prompt injection (L1-L4) com cache LRU |
| F1.4 | Migrar pre-injection |
| F1.5 | Migrar user preferences (L2) |
| F1.6 | Testes: chat normal sem tools, sem RAG, sem agent |

**Duração estimada**: 2-3 sessões

### Fase 2 — RAG Paralelo + Tool Injection
**Objetivo**: Substituir `build_prefix_sections` RAG sequencial.

| Tarefa | Descrição |
|--------|-----------|
| F2.1 | `ToolRegistry` com embeddings de todas as tools |
| F2.2 | `ToolInjector` com seleção RAG-driven + tracking |
| F2.3 | `gather_rag()` paralelo com keyword gate no product RAG |
| F2.4 | Tool injection como OpenAI tools[] nativo (não texto) |
| F2.5 | Catálogo leve (~30 tokens) sempre presente |

**Duração estimada**: 2-3 sessões

### Fase 3 — Gestão de Contexto
**Objetivo**: Substituir compactação + summarization legados.

| Tarefa | Descrição |
|--------|-----------|
| F3.1 | `ContextWindowManager` com estratégia adaptativa única |
| F3.2 | Summarization progressiva com checkpoints |
| F3.3 | Cache persistente em `session_summaries` (Postgres) |
| F3.4 | Token budget com tiktoken (substitui chars/4) |
| F3.5 | Async summarization reentrante (não single-shot) |

**Duração estimada**: 2-3 sessões

### Fase 4 — Integração
**Objetivo**: Unificar agent trees e canvas no pipeline.

| Tarefa | Descrição |
|--------|-----------|
| F4.1 | Agent trees usam `ContextPipeline` (mesmo código que chat) |
| F4.2 | SSE unificado: chat + agent tree events no mesmo stream |
| F4.3 | Canvas wire-up: `manage_workspace_artifact` → SSE `canvas` event |
| F4.4 | LiveCanvas renderiza HTML em tempo real |

**Duração estimada**: 3-4 sessões

### Fase 5 — Desligamento do Legacy
**Objetivo**: Remover código duplicado.

| Tarefa | Descrição |
|--------|-----------|
| F5.1 | Desligar `ContextAssembler` (context.py, 2493 linhas) |
| F5.2 | Desligar `ContextEngine` (context_engine.py, 759 linhas) |
| F5.3 | Desligar `[PROTOCOLO_AGENT_TOOLS]` texto |
| F5.4 | Limpar feature flags e código morto |

**Duração estimada**: 1 sessão

---

## PARTE 4: Comparação Final

| Dimensão | Atual | Proposto |
|----------|-------|----------|
| Sistemas de contexto | 2 (3250 linhas) | 1 (~400 linhas) |
| RAG | Sequencial (390ms) | Paralelo (120ms) + keyword gate |
| Tool injection | 25 schemas texto (4500 tokens) | ~5 schemas nativos (850 tokens) + catálogo (30 tokens) |
| Tool re-injeção | Sempre 25 | Só schemas novos/ausentes (0-360 tokens) |
| Summarization | 2 mecanismos, cache volátil | 1 gestor, persistente, progressivo |
| Token budget | chars/4 (~30% erro) | tiktoken (preciso) |
| Agent trees | Endpoint separado | Mesmo pipeline |
| Canvas | Shell vazio | SSE canvas event |

---

## PARTE 5: Modos de Execução e Tool Scoping

### 5.1 Princípio fundamental

**O backend NUNCA executa ferramentas no seu próprio filesystem.** O backend é um orquestrador — só processa prompts, gere memória, faz RAG, e delega execução.

```
┌──────────────────────────────────────────────────────────────┐
│ BACKEND (VPS) — SEMPRE                                       │
│  ContextPipeline, RAG, orchestration, agent trees            │
│  NUNCA executa terminal, write_file, patch, browser          │
│                                                              │
│  ┌─────────────────────────────────────────────────┐        │
│  │ WEB (browser tab)                                │        │
│  │                                                  │        │
│  │  SEM connector:                                  │        │
│  │   Chat normal. Zero acesso a filesystem.         │        │
│  │   Tools: conhecimento e pesquisa.                │        │
│  │                                                  │        │
│  │  COM connector vivo:                             │        │
│  │   Backend delega tools ao connector.             │        │
│  │   Connector executa no PC do user.               │        │
│  │   Resultado volta → backend → modelo.            │        │
│  └─────────────────────────────────────────────────┘        │
│                                                              │
│  ┌─────────────────────────────────────────────────┐        │
│  │ CLI (terminal local)                             │        │
│  │  Todas as tools disponíveis.                     │        │
│  │  Execução LOCAL (o CLI é o connector).           │        │
│  └─────────────────────────────────────────────────┘        │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 Dois conjuntos de ferramentas

```python
# ═══ Sempre disponíveis (conhecimento, zero filesystem) ═══

KNOWLEDGE_TOOLS = {
    "ask_project",      # consulta AST do projeto (índice Postgres)
    "memory",           # memória persistente (Postgres)
    "session_search",   # histórico de conversas (SQLite)
    "skill_manage",     # gerir skills (Postgres)
    "skill_view",       # ver skills
    "clarify",          # pergunta ao utilizador
    "todo",             # lista de tarefas
}

# ═══ Só com connector vivo (delegadas ao PC do utilizador) ═══

DELEGATED_TOOLS = {
    "search_files",     # grep no diretório exposto
    "read_file",        # ler ficheiro no diretório exposto
    "write_file",       # criar/sobrescrever no diretório exposto
    "patch",            # editar no diretório exposto
    "terminal",         # shell no diretório exposto
    "execute_code",     # Python no diretório exposto
    "browser_navigate", "browser_click", "browser_type",
    "browser_snapshot", "browser_vision", "browser_scroll",
    "delegate_task",    # spawn subagentes
    "cronjob",          # agendamento
    "process",          # gestão de processos
    "text_to_speech",   # TTS
}
```

### 5.3 Tool injection por modo

```python
def available_tools(mode: str, connector: Connector | None) -> set[str]:
    tools = set(KNOWLEDGE_TOOLS)

    if connector is not None and connector.alive:
        tools |= set(DELEGATED_TOOLS)

    if mode == "cli":
        tools |= set(DELEGATED_TOOLS)  # CLI é o próprio connector

    return tools
```

**Na prática:**

| Modo | Connector | Tools disponíveis |
|------|-----------|-------------------|
| WEB | ❌ offline | Só KNOWLEDGE (chat puro) |
| WEB | ✅ vivo | KNOWLEDGE + DELEGATED |
| CLI | — (local) | KNOWLEDGE + DELEGATED |

O RAG-driven tool injection (secção 2.2) aplica-se sobre este conjunto já filtrado. Se o connector caiu, `DELEGATED_TOOLS` desaparece na próxima request — o modelo simplesmente não as vê.

### 5.4 Arquitetura do Connector

```
┌─────────────────────────────────────────────────────────┐
│ CONNECTOR (processo leve no PC do user)                 │
│                                                         │
│  Regista-se no backend:                                 │
│    POST /connector/register                             │
│    {                                                    │
│      "connector_id": "lucas-pc-2024",                   │
│      "exposed_dir": "/home/lucas/projetos",             │
│      "permissions": ["read", "write", "exec"]           │
│    }                                                    │
│                                                         │
│  Recebe comandos do backend:                            │
│    {                                                    │
│      "action": "search_files",                          │
│      "pattern": "main.py",                              │
│      "path": ".",                                       │
│      "exposed_dir": "/home/lucas/projetos"              │
│    }                                                    │
│                                                         │
│  Executa LOCALMENTE, retorna resultado.                 │
│                                                         │
│  Heartbeat: a cada 30s → "ainda estou vivo"            │
│  Se falha → backend marca offline                       │
│  → DELEGATED_TOOLS some na próxima request              │
└─────────────────────────────────────────────────────────┘
```

### 5.5 Bloco [ENV] por modo

```
# WEB sem connector
[ENV] CentralChat Web — chat.
      Sem acesso a ficheiros.
      Para eu poder ler, editar e executar no teu ambiente,
      instala o Central Connector no teu PC.

# WEB com connector vivo
[ENV] CentralChat Web + Connector (lucas-PC).
      Workspace: ~/projetos/

# CLI
[ENV] CentralChat CLI.
      workdir: ~/Workplace/Projects/CentralChat
```

---

## PARTE 6: Limpeza do System Prompt

### 6.1 O que sai

Análise de cada bloco do prefix sections atual e decisão de remoção:

| # | Bloco | Tokens | Porquê remover |
|---|-------|--------|----------------|
| 1 | L1 Anchor | ~150 | RLHF já cobre. "Sê preciso, não inventes" é treino base. |
| 2 | L2 Identity | ~40 | Backend autoriza. Modelo infere língua da conversa. |
| 3 | Bundled prompt | ~20 | Placeholder vazio, nunca usado. |
| 4 | User Preferences L2 | ~60 | Prefs de UI, não de comportamento. Agente (L3) já define estilo. |
| 5 | Capability Digest | ~800 | Redundante com tools[] nativo (Fase 2). |
| 6 | Pre-injection (5 linhas) | ~65 | Reduzido para 1 linha (15 tokens). |
| 7 | Host Context | ~400 | Keyword trigger mais restrito. |

### 6.2 O que fica

```markdown
[AGENT]
És especialista em backend Python/FastAPI no projeto CentralChat.

[SKILLS]
- .env ZERO na raiz. Um .env por serviço.
- Podman restart NÃO reexecuta entrypoint.
- Endpoints usam optimistic concurrency (version, 409).
- createServerFn só suporta GET/POST.
```

**Apenas o que o modelo precisa saber e não é óbvio.** Sem "és o Central", sem "princípios de precisão", sem ID do utilizador, sem preferences de UI.

### 6.3 Comparação de tokens

```
┌──────────────────────────────────────────────┐
│ ANTES: prefix sections                       │
│                                              │
│  L1 Anchor                    150 tokens     │
│  L2 Identity                   40 tokens     │
│  Bundled prompt                20 tokens     │
│  Overlay prompt               100 tokens     │
│  Pre-injection [SYSTEM]        80 tokens     │
│  Multi-slot (se ativo)         30 tokens     │
│  Capability Digest             800 tokens    │
│  User Preferences              60 tokens     │
│  Host Context (condicional)   400 tokens     │
│  RAG (4 queries sequenciais)  500 tokens     │
│  Playbook                     100 tokens     │
│  ─────────────────────────────────────       │
│  TOTAL FIXO (sem tools):     1480 tokens     │
│  TOTAL COM TOOLS:            6280 tokens     │
└──────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────┐
│ DEPOIS: prefix sections                      │
│                                              │
│  L3 Agent                     200 tokens     │
│  L4 Skills                    500 tokens     │
│  Pre-injection [ENV]           15 tokens     │
│  Tool catalog (só nomes)       30 tokens     │
│  RAG (paralelo, condicional)  300 tokens     │
│  ─────────────────────────────────────       │
│  TOTAL FIXO:                  745 tokens     │
│  + Tool schemas (média):      850 tokens     │
│  TOTAL MÉDIO:                1595 tokens     │
│                                              │
│  Redução: 75% vs atual                       │
│  Em turnos com schemas ativos: 745 tokens    │
└──────────────────────────────────────────────┘
```
