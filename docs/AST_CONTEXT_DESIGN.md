# CentralChat AST — Documento de Design

> Brainstorm 2026-06-08. Status: **exploração arquitetural**. Nada implementado.

## Decisão de escopo (2026-06-08)

Após simulação crítica, **AST será ferramenta de análise de fluxo, não substituta de contexto**.

| Uso | Papel | Quem provê |
|-----|-------|------------|
| **Fluxo** (AST) | "O que chama o quê? Impacto de mexer aqui?" | Parser automático de código |
| **Contexto** (skills) | "Quais as regras? Como não quebrar?" | SKILL.md mantida manualmente |

**Não vamos**: migrar convenções pra AST, usar AST como injeção de contexto, substituir skills.
**Vamos**: parser automático de estrutura (arquivos → funções → endpoints → imports), ferramenta `ask_project` para consulta de fluxo, overview de bootstrapping no nó raiz.

Skills e AST coexistem. AST complementa o que skills não fazem: análise de impacto e rastreamento de dependências.

---

## 1. Motivação

### Problema atual

Modelos recebem conhecimento do projeto via **skills markdown flat** (ex: `centralchat/SKILL.md`, ~500 linhas). Isso causa:

| Problema | Impacto |
|----------|---------|
| Carga upfront de tokens | ~4000 tokens antes da primeira ação |
| Desatualização | Skills manuais divergem do código real |
| Inferência de convenções | Modelo aplica padrões genéricos, não os do projeto |
| Escala | Projeto cresce → skill vira monólito ilegível |
| Contexto irrelevante | Modelo recebe regras de Docker mexendo em endpoint |

### Visão

Substituir skills markdown por uma **AST híbrida** (código auto-parseado + convenções anotadas) que o modelo consulta sob demanda via busca semântica em grafo.

---

## 2. Conceitos fundamentais

### 2.1 Separação SYSTEM vs CONTEXT

```
┌──────────────────────────────────────────────┐
│ SYSTEM (como se comportar)                   │
│  L1-L7 injection layers                      │
│  Agent Trees (orquestração determinística)   │
│  Tools / protocolo de ferramentas            │
│  → Instruções imutáveis por sessão           │
├──────────────────────────────────────────────┤
│ CONTEXT — AST (o que existe)                 │
│  Estrutura de código (arquivos, classes)     │
│  Convenções (@convention, @pitfall)          │
│  Relações (imports, deps, contratos)         │
│  → Consultado sob demanda                    │
└──────────────────────────────────────────────┘
```

### 2.2 AST híbrida

- **Nós de código**: gerados automaticamente por parser (arquivos → classes → funções → endpoints)
- **Nós de convenção**: anotados manualmente nos pontos relevantes da árvore

### 2.3 Backend falante (single round-trip)

Em vez de tool calls sequenciais (search → expand → navigate → ...), o modelo faz **uma pergunta** e recebe o subgrafo relevante:

```
Modelo: ask_project("Como criar endpoint com optimistic concurrency?")

Backend:
  1. pgvector cos-similarity sobre todos os nós indexados
  2. Graph expansion: sobe 1 nível + desce 1 nível dos hits
  3. Deduplica, rankeia, formata subgrafo
  4. Retorna em 1 round-trip
```

---

## 3. Schema proposto

```sql
CREATE TABLE ast_nodes (
    id          TEXT PRIMARY KEY,           -- "orchestrator/app/user_config.py:router"
    parent_id   TEXT,                       -- nó pai na hierarquia
    kind        TEXT NOT NULL,              -- FILE | CLASS | FUNCTION | ENDPOINT | CONVENTION | PITFALL | PATTERN | MIGRATION | CONFIG_KEY
    label       TEXT,                       -- nome curto: "user_agents_get"
    content     TEXT,                       -- corpo: código fonte, texto da convenção, schema SQL
    signature   TEXT,                       -- assinatura canônica: "GET /ui/agents → user_agents_get()"
    tags        TEXT[],                     -- ["agents", "crud", "endpoint", "user-config"]
    embedding   vector(1536),              -- embedding(label + content + tags)
    meta        JSONB,                      -- {lines: [236,258], lang: "python", risk_level: "P1", source_file: "..."}
    source_hash TEXT,                       -- hash para detecção de stale vs código real
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- Índices
CREATE INDEX idx_ast_embedding ON ast_nodes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_ast_parent ON ast_nodes (parent_id);
CREATE INDEX idx_ast_kind ON ast_nodes (kind);
CREATE INDEX idx_ast_tags ON ast_nodes USING gin (tags);
```

---

## 4. Tipos de nó (kinds)

| Kind | Origem | Exemplo |
|------|--------|---------|
| `PROJECT` | Parser | `CentralChat/` |
| `DIRECTORY` | Parser | `orchestrator/app/` |
| `FILE` | Parser | `user_config.py` (2493 linhas) |
| `CLASS` | Parser | `ContextAssembler` |
| `FUNCTION` | Parser | `build_prefix_sections()` |
| `ENDPOINT` | Parser | `GET /ui/agents` |
| `MIGRATION` | Parser | `007_user_scoped_config.sql` |
| `SCHEMA_TABLE` | Parser | `user_agents (id, name, prompt, icon...)` |
| `CONVENTION` | Manual | "Endpoints usam optimistic concurrency (version, 409)" |
| `PITFALL` | Manual | "Podman restart NÃO reexecuta entrypoint" |
| `PATTERN` | Manual | "BFF auth: httpOnly cookies > localStorage" |
| `CONTRACT` | Manual | "GET /ui/chat-sessions → {items: [...], ...}" |
| `RELATION` | Parser | `call_llm() → importa openrouter_client` |

---

## 5. Engine de query

### Endpoint

```
POST /ast/query
{
  "question": "Como criar endpoint com optimistic concurrency?",
  "focus": "backend",            // opcional: restringir domínio
  "max_nodes": 15,
  "include_children": true
}
```

### Algoritmo

```
1. EMBED pergunta → pgvector cos-similarity → top-20 hits
2. EXPAND cada hit:
   - parent_id (contexto acima)
   - children LIMIT 5 (visão geral do conteúdo)
   - Se kind=CONVENTION, inclui siblings (outras convenções do mesmo pai)
3. DEDUP por id
4. RANK: score × (1.0 / (depth + 1)) — favorece relevância com leve penalidade de profundidade
5. FORMAT como árvore JSON
6. RETORNAR subgrafo + sugestões de expansão
```

### Ferramenta exposta ao modelo

```json
{
  "name": "ask_project",
  "description": "Pergunta sobre estrutura, código, convenções e padrões do projeto CentralChat.",
  "parameters": {
    "question": "Pergunta em linguagem natural",
    "focus": "Domínio opcional: backend | frontend | infra | migrations"
  }
}
```

---

## 6. Integração com Agent Trees no chat

### Visualização

- Ícones de agentes/subagentes colapsáveis no chat
- Clique expande e mostra o trabalho sendo feito
- SSE events da execução de agent tree renderizados inline
- Cada nó da agent tree mostra o ícone do agent associado

### Relação com AST

- Agent Tree **não é** a AST de contexto — são conceitos diferentes
- Agent Tree = orquestração determinística de modelos
- AST = conhecimento estruturado do projeto que os modelos consultam
- Um nó da Agent Tree pode referenciar um `agent_name` (que agora tem `icon`)

---

## 7. Pipeline de parsing (automático)

```
1. WALK: os.walk() sobre o projeto
2. PARSE: ast.parse() para Python, regex para SQL, ts-morph para TypeScript
3. EXTRACT: classes, funções, endpoints, imports, tabelas SQL, contratos de API
4. EMBED: OpenAI text-embedding-3-small sobre label + content + tags
5. UPSERT: INSERT ON CONFLICT com source_hash — só atualiza nós modificados
6. HOOK: git post-merge hook dispara re-parse dos arquivos alterados
```

---

## 8. Migração de convenções

Origem: `centralchat/SKILL.md` (~30 convenções + 15 pitfalls)

### Exemplos de anotação

```
Nó: orchestrator/app/user_config.py
  ├── @convention: "Endpoints REST usam optimistic concurrency (version field, 409 on conflict)"
  ├── @convention: "Prefix /ui/ para user-facing endpoints"
  └── @pitfall: "createServerFn só suporta GET/POST"

Nó: infra/
  ├── @convention: ".env ZERO na raiz. Um .env por serviço."
  ├── @convention: "docker-compose: Zero environment: blocks. Só env_file:"
  └── @pitfall: "FROM docker.io/oven/bun:1 — NUNCA oven/bun:1 (Podman short-name)"

Nó: CentralChat_Web/src/lib/api/
  ├── @pattern: "BFF auth: server functions proxy → orchestratorJson(httpOnly cookie)"
  └── @contract: "Sessions: GET → {items}, POST → {session}, GET/:id → {session}"
```

---

## 9. Plano de implementação (proposto)

| Fase | O quê | Dependências |
|------|-------|-------------|
| **A. Parser** | Script que popula `ast_nodes` com estrutura do projeto | Postgres + pgvector |
| **B. Anotações** | Migrar convenções da SKILL.md para nós da AST | Fase A |
| **C. Engine** | Endpoint `POST /ast/query` com busca semântica + graph expansion | Fase A |
| **D. Tool** | Registrar `ask_project` no `tools.py` | Fase C |
| **E. Integração** | ContextEngine L6 usar AST em vez de markdown skills | Fase D |
| **F. Canvas** | LiveCanvas renderizar AST como árvore interativa | Fase C |
| **G. Agent Trees UI** | Orquestração visual com ícones colapsáveis no chat | Fase D |

---

## 10. Perguntas em aberto

1. **Profundidade de parsing**: Até que nível descer? Função? Bloco de código? Linha?
2. **Embedding model**: text-embedding-3-small (1536d) ou modelo local menor?
3. **Staleness**: Como detectar que um nó de código está desatualizado sem re-parse completo?
4. **Convenções vs código**: Quem mantém as anotações? O desenvolvedor? Um meta-agente?
5. **Fallback**: Se a busca não achar nada relevante, o que o modelo recebe?
6. **Custo**: Embeddings + pgvector queries a cada tool call — impacto em latência?
