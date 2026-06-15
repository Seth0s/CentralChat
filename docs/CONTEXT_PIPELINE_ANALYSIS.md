# CentralChat — Pipeline de Contexto Atual

> Análise completa para discussão de otimização. 2026-06-08.

---

## 1. Visão geral do fluxo

```
POST /assistant/text ou /assistant/text/stream
│
├─ 1. _resolved_assistant_payload()
│     Aplica defaults salvos (assistant_preferences.json) se use_saved_defaults=true
│     Focus mode: força overrides (disable tools, etc.)
│
├─ 2. _apply_chat_session_history()
│     Se CHAT_SESSIONS_ENABLED=1: carrega histórico do event log, ignora history do cliente
│     Senão: usa history enviado pelo cliente no payload
│
├─ 3. _prepare_assistant_text_llm_inputs() → ContextAssembler.build()
│     │
│     ├─ 3a. normalize_raw_history()
│     │      Normaliza roles, strip thinking tags de assistant
│     │
│     ├─ 3b. compact_conversation_history()
│     │      Se include_long_session_memory=true:
│     │        Gera eco-summary das mensagens antigas via aux_llm (modelo pequeno)
│     │        Remove mensagens antigas, insere summary como system message
│     │      Senão:
│     │        Trunca para SESSION_MAX_MESSAGES_NO_LONG_MEMORY (default: ?)
│     │      Mantém últimas COMPACT_KEEP_LAST_MESSAGES (default: ?)
│     │
│     ├─ 3c. apply_multislot_context() [se WIDGET_MULTI_SLOT_ENABLED=1]
│     │      Particiona histórico por slot, aplica contexto de slots vizinhos
│     │
│     ├─ 3d. build_prefix_sections()
│     │      │
│     │      ├── System Prompt Injection (L6 anchor + product pack + bundled + overlay)
│     │      ├── Pre-injection ([SYSTEM] com ID, User, Privilege, OS)
│     │      ├── Multi-slot system message
│     │      ├── Capability Digest (se include_capability_digest=true)
│     │      ├── User Preferences (L2)
│     │      ├── Host Context (se host_trigger detectado)
│     │      ├── Memory Recall (pgvector: project + prefs namespaces)
│     │      ├── Document RAG (por doc_id)
│     │      ├── Session RAG (por chat_session_id)
│     │      ├── Product RAG (sempre ativo — docs do Central)
│     │      └── Playbook (token-matching local)
│     │
│     ├─ 3e. slim_injected_history_for_router()
│     │      Trim final: aplica caps do router_history_max_messages e max_chars
│     │
│     └─ 3f. TokenBudgetAllocator.build_accounting()
│            Estima tokens (chars/4), valida contra context window cap
│
├─ 4. T15 ContextEngine [se agent_name definido]
│     Pipeline paralelo: 7+1 camadas com cache LRU
│     Retorna InferenceReady (messages, tools, model, profile)
│     Usado por agent trees + quando agent_name é especificado
│
├─ 5. LLM Call
│     Se use_agent_tools=true: run_agent_tool_flow() com PROTOCOLO_AGENT_TOOLS
│     Senão: call_llm() direto
│
└─ 6. Pós-processamento
      Se streaming: NDJSON → SSE (token, provider, usage, done, error)
      Se chat_sessions: append_completed_turn()
      Async summarization: maybe_summarize() se tokens > 80% context limit
```

---

## 2. Sistema de Compaction (conversas longas)

### 2.1 Compactação por truncagem (padrão)

```
SESSION_MAX_MESSAGES_NO_LONG_MEMORY: N
COMPACT_KEEP_LAST_MESSAGES: K

Se histórico > N mensagens:
  Remove as (N - K) mensagens mais antigas
  Mantém as K mais recentes intactas
```

**Problema**: Perda de contexto antigo. Se o usuário menciona algo do início da conversa, o modelo não tem acesso.

### 2.2 Eco-summary (include_long_session_memory=true)

```
1. Pega as primeiras 60% das mensagens
2. Chama aux_llm (modelo pequeno, profile="aux_cloud") 
   com prompt: "Resume esta conversa em português (máx 300 palavras)"
3. Insere summary como system message no início
4. Remove as mensagens sumarizadas do histórico
5. Salva summary em arquivo (COMPACT_SUMMARY_STORE_PATH)
```

**Problema**: 
- Summary é síncrono — bloqueia a request até o aux_llm responder
- Summary é genérico ("máx 300 palavras") — não adapta ao domínio
- Se aux_llm falhar, middle-out é o safety net (perda de dados)

### 2.3 Async Summarization (monitor de tokens)

```
_async_summarize (background thread):
  Dispara quando token_pct > 80% do context limit
  Resume as primeiras 60% das mensagens
  Cache in-memory (_summary_cache[session_id])
  
Na próxima request: get_summary(session_id) → injeta no system prompt
```

**Problema**:
- Cache in-memory — se o processo reinicia, perde todos os summaries
- Thread detached — se falhar, ninguém sabe
- Só dispara UMA vez por sessão (_summarized_sessions set)
- Se a conversa continua crescendo depois do summary, não re-summariza

---

## 3. Dois sistemas de contexto paralelos

### 3.1 ContextAssembler (legacy — context.py, 2493 linhas)

Usado pelo chat normal (`/assistant/text`, `/assistant/text/stream`).
- Histórico vem do payload ou session event log
- Prefix sections: system prompt + pre-injection + RAG + playbook + preferences
- Compact + slim + token budget

### 3.2 ContextEngine (T15 — context_engine.py, 759 linhas)

Usado quando `agent_name` é especificado OU por agent trees.
- 7+1 camadas com cache LRU por hash
- Busca agent config (prompt, model, tools) do `user_agents`
- Carrega skills do diretório `config/default_skills/`
- RAG async em paralelo (memory + user_profile)
- Tool digest filtrado por agent.allowed_tools

**Duplicação**: Dois sistemas fazem coisas similares (RAG, system prompt, tool digest) com implementações diferentes. ContextEngine é mais moderno mas não cobre todos os casos que ContextAssembler cobre.

---

## 4. Token Budget (estimativa)

```
TokenBudgetAllocator:
  estimate_tokens(text) = len(text) / 4  (heurística chars/4)
  
  build_accounting():
    prefix_tokens = sum(estimate_tokens(p) for p in prefix_messages)
    history_tokens = sum(estimate_tokens(h) for h in compacted_history)
    injected = prefix_messages + history
    injected_total = sum(estimate_tokens(i) for i in injected)
    
    Valida contra context_window_cap (do modelo)
```

**Problema**: chars/4 é impreciso. Código vs linguagem natural têm densidades diferentes. Pode subestimar ou superestimar em até 30%.

---

## 5. RAG (Retrieval-Augmented Generation)

4 namespaces de busca, executados SEQUENCIALMENTE (não paralelo):

| Namespace | Trigger | Index | Conteúdo |
|-----------|---------|-------|----------|
| Memory Recall | `include_memory_recall=true` | pgvector | Memórias do usuário (project + prefs) |
| Document RAG | `include_document_rag=true` + doc_id | pgvector | Documentos ingeridos |
| Session RAG | `include_session_rag=true` + session_id | pgvector | Fact index da sessão |
| Product RAG | **Sempre ativo** | pgvector | Documentação do Central |
| Playbook | `include_playbook=true` | Token-matching local | Playbook entries (JSON) |

**Problema**: Product RAG é sempre executado — mesmo em conversas curtas onde não é necessário. Adiciona latência e tokens sem benefício.

---

## 6. Canvas (LiveCanvas / CanvasBrowser)

### Estado atual

```
LiveCanvas.tsx:
  useState("") ← htmlContent NUNCA é populado
  3 abas: Preview (placeholder), Code (hardcoded), Browser (iframe sandbox)

CanvasBrowser.tsx:
  iframe com sandbox="allow-scripts"
  srcDoc={htmlContent} ← sempre vazio
  Botões: Refresh, Open in new window
  
SSE stream:
  Eventos: token, provider, usage, done, error
  NÃO existe evento canvas / html / artifact
```

**Conclusão**: Canvas é um shell visual. Sem backend, sem SSE, sem conteúdo.

### O que precisaria para funcionar

```
1. Modelo gera HTML/CSS/JS via tool call (manage_workspace_artifact)
2. Backend captura output, valida, armazena
3. SSE emite evento canvas com htmlContent ou artifact_id
4. Frontend recebe evento, chama setHtmlContent()
5. CanvasBrowser renderiza no iframe
```

---

## 7. Agent Trees — execução

### Fluxo atual

```
POST /agent-trees/{tree_id}/execute
│
├─ Carrega árvore do banco (agent_trees + agent_nodes)
├─ Monta árvore nested (parent_id → children)
├─ AgentTreeRunner.run_tree():
│   │
│   ├─ Leaf nodes: chama ContextEngine.assemble(agent_name) → call_llm()
│   ├─ Parent nodes: spawn filhos em ThreadPoolExecutor (max 8 workers)
│   │   Aguarda todos, agrega resultados (concat ou first)
│   │
│   └─ SSE events: tree_start, node_start, node_child_done, node_done, tree_done
│
└─ POST /agent-trees/{tree_id}/cancel → threading.Event
```

### Integração com chat principal

**Não existe.** Agent trees são executadas via endpoint separado, página separada (`/agent-trees`). O chat principal não dispara agent trees, não recebe SSE de agent trees, e não renderiza árvore de agentes visualmente.

---

## 8. Pontos de otimização identificados

### 8.1 Conversas curtas (pouca história)

**Problema**: Product RAG, capability digest, e pre-injection são executados mesmo quando desnecessários.

**Otimização**: 
- Product RAG: só executar se a pergunta contém keywords indicando necessidade de documentação
- Capability digest: desabilitar por padrão em conversas curtas (já está condicionado a `include_capability_digest=true`)
- Pre-injection: útil, mas poderia ser cacheado (não muda entre requests)

### 8.2 Conversas longas (muita história)

**Problemas**:
1. Compaction por truncagem perde contexto antigo
2. Eco-summary é síncrono e bloqueia a request
3. Async summarization só dispara UMA vez e cache é volátil
4. Token budget usa chars/4 (impreciso)
5. Não há summarization progressiva (resumo do resumo)

**Otimizações**:
1. **Summarization progressiva**: Manter cadeia de summaries (summary_n cobre mensagens 0-50, summary_n+1 cobre 0-100 incorporando summary_n)
2. **Cache persistente**: Salvar summaries no event log da sessão (já existe `session_summaries` table)
3. **Token budget real**: Usar tiktoken ou tokenizer do modelo em vez de chars/4
4. **Async summarization reentrante**: Permitir re-summarização quando conversa cresce além do último summary

### 8.3 Agent trees no chat

**Problema**: Execução isolada em página separada.

**Otimização**:
1. Integrar SSE de agent tree no stream principal do chat
2. Renderizar árvore de agentes como UI colapsável inline
3. Usar ícones dos agents (já implementado no Ponto 3) para identificar nós
4. Conectar agent tree ao chat session (executar árvore DENTRO de uma conversa)

### 8.4 Canvas

**Problema**: Shell vazio.

**Otimização**:
1. Wire up `manage_workspace_artifact` tool → SSE canvas event
2. Canvas renderiza HTML/componentes em tempo real
3. Preview tab mostra último artefato gerado
4. Code tab mostra fonte do artefato
5. Browser tab mantém iframe sandbox

### 8.5 ContextEngine vs ContextAssembler

**Problema**: Dois sistemas duplicados.

**Otimização**: Migrar progressivamente ContextAssembler → ContextEngine (já planejado como T15/T16). ContextEngine tem cache LRU, paralelismo, e injeção em camadas — superior em todos os aspectos.

### 8.6 Product RAG sempre ativo

**Problema**: Custo fixo de latência + tokens em toda request.

**Otimização**: Só executar se a pergunta contiver termos do domínio do Central (ex: "orchestrator", "endpoint", "migration", "context"). Usar o playbook como fallback leve (token-matching é mais barato que pgvector).
