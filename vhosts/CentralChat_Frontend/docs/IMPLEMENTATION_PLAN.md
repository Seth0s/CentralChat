# CentralChat_Web — Implementation Plan

`CREATED:` 2026-06-06  `UPDATED:` 2026-06-06 (BFF auth, remove dashboard)
`STACK:` TanStack Start · React 19 · Tailwind v4 · shadcn/ui · Bun
`API:` [UI_BACKEND_CONTRACT.md](../docs/UI_BACKEND_CONTRACT.md) · [API_UI_INVENTORY.md](../docs/API_UI_INVENTORY.md)

---

## Princípios para IA

1. **1 ficheiro = 1 domínio** — cada ficheiro contém imports, types, logic, e JSX do seu domínio
2. **Contratos antes de código** — cada fase referencia o endpoint exacto
3. **Zero regressão** — cada fase compila e corre sem quebrar as anteriores
4. **Fase isolada** — começar e terminar uma fase antes de passar à próxima

## Segurança — BFF Pattern (httpOnly Cookies)

**Problema:** localStorage é vulnerável a XSS — qualquer script no domínio pode ler o JWT.

**Solução:** TanStack Start tem camada de servidor (Nitro). Usamos o padrão **BFF (Backend-for-Frontend)**:

```
Browser                    TanStack Server (Nitro)         Orchestrator
  │                              │                            │
  │  POST /api/auth/login        │                            │
  │  { email, password }         │                            │
  │ ─────────────────────────→  │                            │
  │                              │  POST /auth/login          │
  │                              │ ─────────────────────────→ │
  │                              │  ← JWT access + refresh    │
  │                              │                            │
  │  ← Set-Cookie:              │                            │
  │    token=JWT;               │                            │
  │    HttpOnly; Secure;        │                            │
  │    SameSite=Strict          │                            │
  │                              │                            │
  │  GET /api/chat-sessions     │                            │
  │  (cookie enviado auto)      │                            │
  │ ─────────────────────────→  │                            │
  │                              │  GET /ui/chat-sessions     │
  │                              │  Authorization: Bearer JWT │
  │                              │ ─────────────────────────→ │
  │                              │  ← dados                   │
  │  ← JSON                     │                            │
```

- **JWT nunca toca o browser** — cookie `HttpOnly; Secure; SameSite=Strict`
- **Zero exposição a XSS** — JS não consegue ler o cookie
- **Refresh automático** — server detecta 401, faz refresh, re-envia request original
- **Server functions** do TanStack (`createServerFn`) fazem o proxy para o orchestrator

---

## Estado actual (Fase 0)

Mockup visual completo com dados hardcoded. Zero integração.

| Componente | Estado |
|-----------|--------|
| `routes/index.tsx` | Chat com seed data + setTimeout mock |
| `Sidebar.tsx` | Grupos hardcoded |
| `MessageBlock.tsx` | Markdown simples |
| `TerminalInput.tsx` | 3 modelos hardcoded |
| `SettingsModal.tsx` | 5 tabs fake |
| `LiveCanvas.tsx` | Preview/Code estático |
| API | Só exemplo `getGreeting` |

---

## Fase 1: Auth — BFF + Login (Admin Design)

**Objectivo:** Login via server function, JWT em httpOnly cookie, AuthGate.

**Design:** igual ao Admin CentralChurch — card centrado, dark theme, shadcn/ui.

### Tarefas

| ID | Tarefa | Contrato |
|----|--------|----------|
| 1.1 | Criar `src/lib/api/orchestrator.ts` — fetch para orchestrator (server-side, com JWT inject) | §2.4 |
| 1.2 | Criar `src/lib/auth/server/login.ts` — server function: recebe credenciais, chama `POST /auth/login`, seta cookie httpOnly | §6 |
| 1.3 | Criar `src/lib/auth/server/refresh.ts` — server function: `POST /auth/refresh`, actualiza cookie | §7 |
| 1.4 | Criar `src/lib/auth/server/session.ts` — ler JWT do cookie (server-side), validar expiry, extrair claims | §2.4 |
| 1.5 | Criar `src/lib/auth/client.ts` — client-side helpers: `useAuth()` hook, `logout()`, redirect | — |
| 1.6 | Criar `src/components/auth/LoginPage.tsx` — Card + Input + Button (shadcn), zod, toast erros | §6 |
| 1.7 | Criar `src/routes/login.tsx` — rota pública `/login` | — |
| 1.8 | Actualizar `__root.tsx` — `beforeLoad` check da sessão, redirect `/login` se inválida | — |

### Design

```
┌──────────────────────────────────┐
│         🔷 Central               │  ← logo + nome
│                                  │
│  Escolha o método de login.      │
│                                  │
│  ┌──────────────────────────┐   │
│  │ Email                     │   │  ← Input shadcn
│  └──────────────────────────┘   │
│  ┌──────────────────────────┐   │
│  │ Palavra-passe             │   │  ← Input password
│  └──────────────────────────┘   │
│                                  │
│  ┌──────────────────────────┐   │
│  │         Entrar            │   │  ← Button primary
│  └──────────────────────────┘   │
│                                  │
│  ⚠ Email ou senha inválidos     │  ← toast sonner
└──────────────────────────────────┘
```

### DoD
- [ ] Login `dev@local.test` / `changeme` → cookie httpOnly setado
- [ ] JWT invisível ao JS (HttpOnly; Secure; SameSite=Strict)
- [ ] Refresh automático server-side antes de expirar
- [ ] Sem sessão → redirect `/login`
- [ ] Design idêntico ao Admin (Card + shadcn + dark theme)
- [ ] Erros via toast (sonner)

### Estrutura

```
src/lib/api/orchestrator.ts       ← fetch p/ orchestrator (server-side)
src/lib/auth/server/login.ts      ← server fn: login + set cookie
src/lib/auth/server/refresh.ts    ← server fn: refresh token
src/lib/auth/server/session.ts    ← ler/validar JWT do cookie
src/lib/auth/client.ts            ← useAuth(), logout()
src/components/auth/LoginPage.tsx
src/routes/login.tsx
```

---

## Fase 2: Chat Real — Streaming SSE + Sessões

**Objectivo:** Substituir mock por streaming real, CRUD de conversas, markdown.

### Tarefas

| ID | Tarefa | Contrato |
|----|--------|----------|
| 2.1 | Criar `src/lib/api/server/chat.ts` — server functions: `sendMessage`, `streamAssistantText` (SSE parser) | §19 |
| 2.2 | Criar `src/lib/api/server/sessions.ts` — CRUD sessões via server proxy | §10 |
| 2.3 | Actualizar `routes/index.tsx` — remover SEED, usar TanStack Query + server functions | — |
| 2.4 | Actualizar `Sidebar.tsx` — dados reais, agrupar por data, criar/renomear/apagar | §10 |
| 2.5 | Actualizar `MessageBlock.tsx` — markdown real (react-markdown + remark-gfm) | — |
| 2.6 | Streaming token-a-token com indicador de digitação | §19 |
| 2.7 | Métricas reais (tokens, tempo) do stream | — |

### DoD
- [ ] Chat envia → stream SSE → renderiza token a token
- [ ] Sidebar mostra conversas reais do servidor
- [ ] CRUD sessões funcional
- [ ] Markdown rico (código, tabelas, bold, listas)

---

## Fase 3: Configuração & Modelos Reais

**Objectivo:** Settings modal + seletor de modelos com dados do orchestrator.

### Tarefas

| ID | Tarefa | Contrato |
|----|--------|----------|
| 3.1 | Criar `src/lib/api/server/config.ts` — `GET /config`, `GET /ui/inference_catalog` | §5, §11 |
| 3.2 | Criar `src/lib/api/server/preferences.ts` — `POST /ui/preferences` | §9 |
| 3.3 | Actualizar `TerminalInput.tsx` — modelos reais do `inference_catalog` | §11 |
| 3.4 | Actualizar `SettingsModal.tsx` "Model Hub" — lista real, toggle enable/disable | §11 |
| 3.5 | Actualizar `SettingsModal.tsx` "Advanced" — temp/top_p persiste no server | §9 |
| 3.6 | Actualizar `SettingsModal.tsx` "API Keys" — status real dos providers | §5 |

### DoD
- [ ] Seletor mostra modelos reais do orchestrator
- [ ] Model Hub com toggle funcional
- [ ] Preferências persistem

---

## Fase 4: Live Canvas v2 — Navegador Interno

**Objectivo:** 3 tabs: Preview, Code, **Browser**. O Browser renderiza HTML/CSS/JS em sandbox.

### Funcionamento

- AI gera código → resposta inclui `canvas_artifact` no stream SSE
- Canvas detecta → renderiza na tab Browser em tempo real
- Browser usa `<iframe sandbox>` com `srcdoc`
- Preview e Code mantêm-se para preview estático e source

### Tarefas

| ID | Tarefa |
|----|--------|
| 4.1 | Adicionar tipo `CanvasArtifact` ao Message |
| 4.2 | Criar `CanvasBrowser.tsx` — iframe sandbox + srcdoc |
| 4.3 | Actualizar `LiveCanvas.tsx` — 3 tabs: Preview / Code / Browser |
| 4.4 | Integrar com stream — detectar `canvas_artifact`, popular Browser |
| 4.5 | Botão "Abrir em nova janela" (blob URL) |
| 4.6 | Refresh/reload do iframe |
| 4.7 | Tratamento de erros JS no iframe → toast amigável |

### DoD
- [ ] 3 tabs: Preview | Code | Browser
- [ ] HTML gerado → renderizado em sandbox
- [ ] Iframe isolado (sem acesso ao DOM da app)
- [ ] Code tab com syntax highlighting
- [ ] Erros capturados e exibidos

### Segurança do iframe

```html
<iframe
  sandbox="allow-scripts allow-same-origin"
  srcdoc={htmlContent}
  title="Canvas Preview"
/>
```

- `allow-scripts` — JS inline (React/Preact gerado)
- `allow-same-origin` — recursos locais
- **NÃO** incluir `allow-top-navigation`, `allow-popups`, `allow-forms`
- Erros capturados via `window.onerror` → toast

---

## Fase 5: Ferramentas & Aprovações HITL

**Objectivo:** Fila de aprovações, tool calls inline, status do connector.

### Tarefas

| ID | Tarefa | Contrato |
|----|--------|----------|
| 5.1 | `src/lib/api/server/approvals.ts` — GET/POST approvals | §16 |
| 5.2 | `ApprovalsPanel.tsx` — painel lateral com lista de pendentes | — |
| 5.3 | `ConnectorBadge.tsx` — status online/offline do agente local | — |
| 5.4 | Ícone de aprovações com badge de contagem na top bar | — |
| 5.5 | Tool calls inline nas mensagens (tool → resultado) | — |

---

## Fase 6: Avançado — Agent Trees, RAG, Multi-slot, OIDC

| ID | Tarefa |
|----|--------|
| 6.1 | Agent Trees — visualização e edição |
| 6.2 | Multi-slot graph widget |
| 6.3 | Document RAG — upload e busca |
| 6.4 | Memory context viewer |
| 6.5 | OIDC/SSO login (Keycloak) |

---

## Dependências

```
F1 (auth BFF) ──→ F2 (chat real) ──→ F3 (config) ──→ F4 (canvas v2)
                        │
                        └──→ F5 (tools/approvals) ──→ F6 (avançado)
```

## Estimativa

| Fase | Esforço |
|------|---------|
| F1 — Auth BFF + Login | 5-7h |
| F2 — Chat + SSE | 6-8h |
| F3 — Config & Modelos | 2-3h |
| F4 — Canvas v2 (Browser) | 4-6h |
| F5 — Tools & Approvals | 3-5h |
| F6 — Avançado | 8-12h |
| **Total** | **~28-41h** |

---

## Arquitectura de segurança (BFF)

```
┌─────────────────────────────────────────────────────────┐
│ Browser                                                 │
│  ┌─────────┐   fetch /api/*    ┌──────────────────┐    │
│  │ React   │ ────────────────→ │ TanStack Server   │    │
│  │ (client)│ ← JSON ───────── │ (Nitro)           │    │
│  └─────────┘                   │                    │    │
│                                │ JWT em httpOnly    │    │
│  Nunca vê o JWT                │ cookie             │    │
│                                │                    │    │
│                                │ fetch /orch/*      │    │
│                                │ Authorization:     │    │
│                                │ Bearer <JWT>       │    │
│                                │ ──────────────────→│    │
│                                │                    │    │
│                                │ Orchestrator       │    │
│                                │ :8004              │    │
│                                └──────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

## Estrutura final de ficheiros

```
CentralChat_Web/
├── src/
│   ├── lib/
│   │   ├── api/
│   │   │   ├── orchestrator.ts       ← F1: fetch p/ orchestrator (server)
│   │   │   └── server/
│   │   │       ├── chat.ts           ← F2: SSE streaming
│   │   │       ├── sessions.ts       ← F2: CRUD sessões
│   │   │       ├── config.ts         ← F3: /config + catalog
│   │   │       ├── preferences.ts    ← F3: preferences
│   │   │       └── approvals.ts      ← F5: HITL approvals
│   │   ├── auth/
│   │   │   ├── server/
│   │   │   │   ├── login.ts          ← F1: login + set cookie
│   │   │   │   ├── refresh.ts        ← F1: refresh token
│   │   │   │   └── session.ts        ← F1: ler/validar cookie
│   │   │   └── client.ts             ← F1: useAuth(), logout()
│   │   └── utils.ts
│   ├── components/
│   │   ├── auth/
│   │   │   └── LoginPage.tsx         ← F1
│   │   └── chat/
│   │       ├── Sidebar.tsx           ← F2 (real)
│   │       ├── MessageBlock.tsx      ← F2 (markdown)
│   │       ├── TerminalInput.tsx     ← F3 (modelos reais)
│   │       ├── SettingsModal.tsx     ← F3 (dados reais)
│   │       ├── LiveCanvas.tsx        ← F4 (3 tabs)
│   │       ├── CanvasBrowser.tsx     ← F4 (iframe)
│   │       ├── ApprovalsPanel.tsx    ← F5
│   │       └── ConnectorBadge.tsx    ← F5
│   ├── routes/
│   │   ├── __root.tsx                ← F1 (beforeLoad check)
│   │   ├── login.tsx                 ← F1 (pública)
│   │   └── index.tsx                 ← F2 (chat real)
│   └── styles.css
```
