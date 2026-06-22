# SOLO-3 — Performance, Completude & Polish

> **Created:** 2026-06-22
> **Status:** Planejamento aprovado — implementação pendente
> **Depende de:** SOLO-2 (AgentRuntime nativo Go + SQLite + Policy)

---

## Phase 1 — Performance (3 dias)

### P1.1 — Ollama keep-alive
**Impacto:** -2 a 5s por turno (modelo não é descarregado da RAM)
**Esforço:** 15 min

Adicionar `keep_alive: "10m"` ao payload do Ollama (`ollamaRequest`). Após 10 min sem uso, o modelo é descarregado automaticamente.

```go
type ollamaRequest struct {
    Model     string    `json:"model"`
    Messages  []Message `json:"messages"`
    Stream    bool      `json:"stream"`
    KeepAlive string    `json:"keep_alive,omitempty"` // "10m"
}
```

### P1.2 — Token counting real
**Impacto:** Previne erros de context window em sessões longas (hoje o truncate por mensagens é impreciso — 40 mensagens podem ser 2000 ou 20000 tokens)
**Esforço:** 2h

Substituir `compactHistory` baseado em contagem de mensagens por estimativa de tokens. Usar `chars/4` como fallback com ajuste para código (mais denso).

```go
func estimateTokens(messages []Message) int {
    total := 0
    for _, m := range messages {
        // ~4 chars per token for natural language, ~2.5 for code
        chars := len(m.Content)
        if isCode(m.Content) {
            total += chars / 5 * 2  // code is denser
        } else {
            total += chars / 4
        }
    }
    return total
}
```

Budget: 8000 tokens para histórico, keep last 10 messages verbatim.

### P1.3 — Context cache entre turns
**Impacto:** -2ms por turno (evita reconstruir system prompt)
**Esforço:** 1h

`ContextLite` ganha cache das camadas L2+L3+ENV. Invalidado quando workspace ou agent mudam.

```go
type ContextLite struct {
    // ...existing fields...
    cachedSystem []Message
    cacheKey     string  // "{agent}:{workspace}:{skills_hash}"
}
```

### P1.4 — SQLite prepared statements
**Impacto:** -30% latência em AppendTurn (3 INSERT em transação)
**Esforço:** 1h

Pre-compilar statements no `DB()` e reusar:

```go
var stmtInsertMsg *sql.Stmt
var stmtUpdateSession *sql.Stmt
```

### P1.5 — Streaming buffer
**Impacto:** Evita bloqueio do provider quando TUI renderiza devagar
**Esforço:** 5 min

```go
ch := make(chan streamEventMsg, 256) // era 64
```

### P1.6 — Tool execution paralela (read-only)
**Impacto:** -50% latency quando múltiplas tools independentes
**Esforço:** 3h — requer análise de dependências entre tool calls

Tools read-only (`read_file`, `search_files`) executam em paralelo via goroutines. Tools write (`write_file`, `patch`, `terminal`) continuam sequenciais por segurança.

---

## Phase 2 — Comandos SOLO (3 dias)

### P2.1 — Desabilitar comandos TEAM-only em SOLO

Comandos que **não fazem sentido** em SOLO:
| Comando | Ação |
|---------|------|
| `/approve` | Bloquear com mensagem: "Approvals are TEAM-only. SOLO uses policy confirmation." |
| `central approve` | Idem |
| `central reject` | Idem |
| `central daemon` | Bloquear: "Connector daemon is TEAM-only. SOLO uses in-process executor." |
| `central login` | Permitir mas avisar: "Login is optional in SOLO mode." |
| `central pending` | Bloquear: "Work queue is TEAM-only." |

Implementação: `guardSolo(cmd)` que verifica `config.Runtime == ModeSolo` e bloqueia com mensagem PT.

### P2.2 — `/prefs` local
**Em SOLO:** Abre `config.toml` ou `policy.yaml` no `$EDITOR` (ou `cat` se não definido).
**Em TEAM:** Comportamento atual (VPS).

```go
case "/prefs":
    if m.runtime.Runtime == config.ModeSolo {
        path, _ := config.RuntimeConfigPath()
        return sessionTea(m), openEditorCmd(path)
    }
    // TEAM path...
```

### P2.3 — `/agent` local (gerido pelo próprio agente)
**Não implementar UI.** O agente usa a tool `write_file` para criar/editar arquivos em `~/.config/central/agents/*.txt` e `skills/*.txt`. O `ContextLite` já lê esses arquivos.

Adicionar tool `manage_agent`:
- `manage_agent action=create name=coder prompt="És um programador Python..."` → escreve `agents/coder.txt`
- `manage_agent action=delete name=coder` → remove `agents/coder.txt`
- `manage_agent action=list` → lista arquivos em `agents/`

Mesmo para `manage_skill`.

### P2.4 — Sidebar com dados locais
Em SOLO, o sidebar mostra:
- Workspace path + git branch (já lido localmente)
- Session count (via `solo.ListSessions()`)
- Model name + provider kind
- Policy status ("policy: enforced" ou "policy: none")

Sem chamadas VPS.

### P2.5 — Session search com FTS5
Adicionar tabela FTS5 no SQLite:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, content='messages', content_rowid='id'
);
```

Tool `session_search` em SOLO faz `SELECT ... FROM messages_fts WHERE content MATCH ?`.

---

## Phase 3 — Agents & Skills via Tools (2 dias)

### Design: Igual ao Hermes CLI

O agente **não tem UI** para agents/skills. Em vez disso, ele usa as mesmas tools que já tem (`write_file`, `read_file`, `search_files`, `patch`) para gerir arquivos em `~/.config/central/agents/` e `skills/`.

```
~/.config/central/
├── agents/
│   ├── default.txt      # "És um assistente prestativo."
│   └── coder.txt        # "És um programador Python experiente..."
├── skills/
│   ├── python.txt       # "Sempre usar type hints. Usar pytest."
│   └── git.txt          # "Commits em português. Branches: feature/*"
└── config.toml
```

### Fluxo

1. Usuário: "cria um agente chamado reviewer que revisa código"
2. Agente chama `write_file(path="~/.config/central/agents/reviewer.txt", content="És um revisor...")`
3. Usuário: "/agent reviewer"
4. `ContextLite.LoadAgentPrompt("reviewer")` lê o arquivo
5. Agente agora age como reviewer

### Tools adicionais

| Tool | Implementação |
|------|---------------|
| `manage_agent` | CRUD de `agents/*.txt` (action=create/delete/list/activate) |
| `manage_skill` | CRUD de `skills/*.txt` (action=create/delete/list) |

Ou, mais simples: **sem tools novas**. O agente já tem `write_file` e `read_file`. Basta documentar que agents/skills são arquivos em `~/.config/central/agents/` e o agente os lê automaticamente.

---

## Phase 4 — Bridge & Polish (2 dias)

### P4.1 — Session search FTS5 (completar P2.5)

### P4.2 — `/prefs` local abrir config.yaml + policy.yaml

### P4.3 — `central sync push/pull`
```bash
central sync push --tenant my-org    # sessions + memory → VPS
central sync pull --rules            # team rules → ~/.config/central/skills/
```

### P4.4 — Documentação `central --help` atualizada

---

## Ordem de execução

```
Dia 1-2:  Phase 1 (Performance)
          P1.1 → P1.2 → P1.5 → P1.4 → P1.3
          (P1.6 paralelo se houver bandwidth)

Dia 3-4:  Phase 2 (Comandos SOLO)
          P2.1 → P2.4 → P2.2 → P2.3

Dia 5-6:  Phase 3 (Agents/Skills via tools)
          Design + implementação do manage_agent / manage_skill
          OU documentação de que agents são ficheiros

Dia 7-8:  Phase 4 (Bridge & Polish)
          P2.5 → P4.3 → P4.4
```

---

## Métricas de sucesso

| Métrica | Baseline | Meta |
|---------|----------|------|
| Latência turno (Ollama, sem tools) | 3-7s (com unload/reload) | <2s (keep-alive) |
| Latência 2x read_file paralelo | 2x sequencial | <1.2x sequencial |
| Sessão 100+ mensagens sem erro de contexto | Frágil (>40 msg perde) | Robusto (token budget) |
| Comandos TEAM-only em SOLO | Erro genérico | Mensagem PT clara |
| `/prefs` em SOLO | Erro VPS | Abre config.toml |
| `/agent` em SOLO | Erro VPS | Lê agents/ locais ou tool manage_agent |
