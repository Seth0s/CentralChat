# CentralChat SOLO — Tool Implementation Plan (Go-native)

> 2026-06-22 · Zero Python dependencies · Single binary

## Catálogo revisto

| Tool | Implementada | Ação |
|------|-------------|------|
| `read_file` | ✅ | — |
| `write_file` | ✅ | — |
| `search_files` | ✅ | — |
| `patch` | ✅ | — |
| `terminal` | ✅ | — |
| `memory` | ✅ | — |
| `session_search` | ✅ | — |
| `manage_work_item` | ✅ | — |
| `clarify` | ❌ → ✅ | Trivial (30min) |
| `web_search` | ❌ → 🔨 | DuckDuckGo + Brave Search (3h) |
| `vision_analyze` | ❌ → 🔨 | Provider multimodal (2h) |
| `execute_code` | ❌ → 🗑️ | Remover — `terminal` cobre |
| `delegate_task` | ❌ → 🔨 | Go subprocessos (8h, fase futura) |

---

## 1. `clarify` — 30min

Tool que faz o agente pedir input ao utilizador. Nenhuma dependência externa.

```go
// executor/agent.go
case "clarify":
    question := strArg(args, "question")
    choices := strListArg(args, "choices")
    if len(choices) > 0 {
        return fmt.Sprintf("[QUESTION] %s\nOptions: %s\nReply with your choice.", 
            question, strings.Join(choices, ", ")), nil
    }
    return fmt.Sprintf("[QUESTION] %s", question), nil
```

O agente vê a resposta e age. O TUI mostra como mensagem do sistema.

---

## 2. `web_search` — 3h

### Backend primário: DuckDuckGo (zero deps, sem API key)

```go
// internal/websearch/ddg.go
package websearch

import (
    "encoding/json"
    "net/http"
    "net/url"
)

type SearchResult struct {
    Title   string
    URL     string
    Snippet string
}

func DuckDuckGo(query string, limit int) ([]SearchResult, error) {
    // DuckDuckGo Instant Answer API
    u := "https://api.duckduckgo.com/?q=" + url.QueryEscape(query) + "&format=json&no_html=1"
    resp, err := http.Get(u)
    // Parse Abstract, AbstractURL, RelatedTopics, Results
    // Return up to `limit` results
}
```

### Backend premium opcional: Brave Search API

```go
func BraveSearch(query, apiKey string, limit int) ([]SearchResult, error) {
    // GET https://api.search.brave.com/res/v1/web/search?q=<query>
    // Header: X-Subscription-Token: <apiKey>
}
```

Config: `BRAVE_SEARCH_API_KEY` env var. Se existir, usa Brave; senão, DDG.

### Executor bridge
```go
case "web_search":
    query := strArg(args, "query")
    limit := intArg(args, "limit", 5)
    results, err := websearch.Search(query, limit)
    // Format as text block with title + URL + snippet
```

---

## 3. `vision_analyze` — 2h

Passa a imagem como base64 no request do provider (OpenAI/Anthropic compatível).

```go
// internal/inference/provider.go — adicionar suporte a imagem
type ContentPart struct {
    Type     string `json:"type"`
    Text     string `json:"text,omitempty"`
    ImageURL *struct {
        URL string `json:"url"`
    } `json:"image_url,omitempty"`
}

// No executor:
case "vision_analyze":
    imagePath := strArg(args, "image_url")
    question := strArg(args, "question", "Describe this image")
    // Read file, encode base64
    // Send to provider with vision model
    // Return description
```

Se o provider atual não suportar visão, retorna erro claro.

---

## 4. `execute_code` — REMOVER

O `terminal` já cobre:
- `terminal("python3 script.py")` 
- `terminal("go run main.go")`
- `terminal("bash -c 'for f in *.go; do ...'")`

Não precisamos de uma tool separada para execução de código. O agente usa `terminal` para qualquer runtime (Python, Go, Bash, Node).

### Ação
- Remover `execute_code` de `allToolNames()` e `toolSchemas`
- Remover `toolTriggers["execute_code"]`

---

## 5. `delegate_task` — fase futura (8h)

Go subprocesso:

```go
case "delegate_task":
    goal := strArg(args, "goal")
    // Spawn: os.exec("central", "agent", "--task", goal, "--workspace", workspace)
    // Capture stdout, enforce timeout
```

Complexo — deixar para depois.

---

## Plano de implementação (revisto)

| Fase | Entregável | Esforço |
|------|-----------|---------|
| **Fase 1** | `clarify` + remover `execute_code` do catálogo | 30min |
| **Fase 2** | `web_search` (DDG + Brave opcional) | 3h |
| **Fase 3** | `vision_analyze` (provider multimodal) | 2h |
| **Fase 4** | `delegate_task` | 8h (futuro) |

### Remoção de referências "hermes"

Ficheiros a limpar:
- `internal/runtime/context_lite.go`: comentários mencionando "Hermes"
- `docs/SIDEBAR_FIELDS.md`: referências a hermes
- `internal/ui/app.go`: comentários hermes
- Qualquer `hermes_tools` ou `hermes-agent` no código
