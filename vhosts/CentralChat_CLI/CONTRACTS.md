# CentralChat CLI ↔ Backend — Mapa de Contratos

> Backend é a fonte da verdade. CLI adapta-se aos contratos do backend.

## 1. Auth

| Método | Endpoint | Request | Response | Usado por |
|--------|----------|---------|----------|-----------|
| POST | `/auth/login` | `{email, password}` | `{access_token, refresh_token, expires_in}` | `submitLogin()` |
| POST | `/auth/refresh` | `{refresh_token}` | `{access_token, refresh_token, expires_in}` | `Refresh()` |
| POST | `/auth/logout` | — | — | `Logout()` |
| GET | `/auth/public-config` | — | `map` | `PublicConfig()` |
| POST | `/auth/device` | `{client_label}` | `map` | `StartDeviceAuth()` |
| POST | `/auth/device/poll` | `{device_code}` | `{access_token, ...}` | `PollDeviceToken()` |
| POST | `/auth/exchange-api-key` | `{api_key}` | `{access_token, ...}` | `ExchangeApiKey()` |

## 2. Workspace

| Método | Endpoint | Request | Response | Usado por |
|--------|----------|---------|----------|-----------|
| POST | `/ui/workspace` | `{path?, connector_id?}` | `{bound, id, path?, connector_id?, git}` | `activateCurrentWorkspace()`, `selectCurrentWorkspace()` |
| GET | `/ui/workspace` | — | `{bound, id, path?, connector_id?, git}` | `refreshSidebarCmd()` |
| GET | `/ui/workspaces` | — | `{items: [{id, path?, label, connector_id?}], active_workspace_id}` | `GetWorkspaces()` |
| PUT | `/ui/workspaces` | `{workspaces: [{id, path?, label, connector_id?}], active_id}` | `map` | `SyncWorkspacesToServer()` |

> **Phase 2+**: `path` é opcional quando `connector_id` está presente. Workspace connector-only não tem filesystem local.

## 3. Sessões (Chat Sessions)

| Método | Endpoint | Request | Response | Usado por |
|--------|----------|---------|----------|-----------|
| GET | `/ui/chat-sessions` | — | `{items: [{id, title, message_count, pinned, updated_at}], chat_sessions_enabled}` | `loadSessionsCmd()` → hub |
| POST | `/ui/chat-sessions` | `{title?}` | `{session: {id, title, ...}}` | `ensureSessionCmd()` |
| GET | `/ui/chat-sessions/{id}` | — | `map` | — (não usado pelo CLI) |
| PATCH | `/ui/chat-sessions/{id}` | `{title?, pinned?}` | `map` | `PatchSession()` |
| DELETE | `/ui/chat-sessions/{id}` | — | — | `deleteSessionCmd()` |
| GET | `/ui/sessions/{id}/surface` | — | `{title, session_phase, messages: [{role, content}]}` | `sessionOpenCmd()`, `openSessionByID()` |

## 4. Chat (Streaming)

| Método | Endpoint | Request | Response | Usado por |
|--------|----------|---------|----------|-----------|
| POST | `/ui/ask` | `{prompt, ...}` + headers | SSE stream | `AskStream()` |
| POST | `/ui/sessions/{id}/interrupt/respond` | `{choice?, custom?}` | `map` | `RespondInterrupt()` |

## 5. Work Items

| Método | Endpoint | Request | Response | Usado por |
|--------|----------|---------|----------|-----------|
| GET | `/ui/work-items` | ?status | `map` com items | `loadWorkItemsCmd()` → hub Work Queue |
| GET | `/ui/work-items/{id}` | — | `map` | `GetWorkItem()` |
| POST | `/ui/work-items` | `{title, description?, priority?, session_id?, workspace?}` | `map` | `CreateWorkItem()` |
| PATCH | `/ui/work-items/{id}` | `map` | `map` | `PatchWorkItem()` |
| POST | `/ui/work-items/{id}/work` | — | `map` | `WorkWorkItem()` |
| POST | `/ui/work-items/{id}/link` | `{external_url?, external_id?}` | `map` | `LinkWorkItem()` |

## 6. Usage / Sidebar

| Método | Endpoint | Request | Response | Usado por |
|--------|----------|---------|----------|-----------|
| GET | `/ui/sidebar` 🆕 | — | `{workspace: {path, branch, dirty_count, connector_id}, preferences: {model, inference_dest, auto_tier, temperature, effort, max_tokens}, usage: {total_cost}, pending_approvals, work_queue_count, connector: {online, count}}` | `refreshSidebarCmd()` — 1 chamada substitui 5 |
| GET | `/ui/usage` | — | `{total_cost, ...}` | fallback |

## 7. Team Agents / Skills / Rules

| Método | Endpoint | Usado por |
|--------|----------|-----------|
| GET | `/ui/team-agents?status=published` | `loadAgentsCmd()` |
| POST | `/ui/team-agents` | `CreateTeamAgent()` |
| POST | `/ui/team-agents/{id}/review` | `SubmitTeamAgentReview()` |
| POST | `/ui/team-agents/{id}/publish` | `PublishTeamAgent()` |
| GET | `/ui/team-skills?status=published` | `ListTeamSkills()` |
| GET | `/ui/team-rules?status=published` | `ListTeamRules()` |
| POST | `/ui/team-rules/{id}/approve` | `ApproveTeamRule()` |

## 8. Preferences

| Método | Endpoint | Usado por |
|--------|----------|-----------|
| GET | `/ui/preferences` | `memoryStatusCmd()`, `GetPreferences()` |
| POST | `/ui/preferences` | `SetPreferences()` |

## 9. Approvals

| Método | Endpoint | Usado por |
|--------|----------|-----------|
| GET | `/ui/approvals?status=pending` | `approveListCmd()` |
| GET | `/ui/approvals/{id}/diff` | `ApprovalDiff()` |
| POST | `/ui/approvals/{id}/approve` | `Approve()` |
| POST | `/ui/approvals/{id}/deny` | `Deny()` |

## 10. Config / Catálogo / Audit / Policies / Connector

| Método | Endpoint | Usado por |
|--------|----------|-----------|
| GET | `/ui/config` | `GetConfig()` |
| GET | `/ui/cloud-models` | `doctorCmd()` |
| GET | `/ui/inference-catalog` | `GetInferenceCatalog()` |
| POST | `/ui/profile/{letter}` | `SetProfile()` |
| GET | `/ui/audit` | `ListAuditEvents()` |
| GET | `/ui/audit/export` | `ExportAudit()` |
| GET | `/ui/policies` | `ShowPolicies()` |

### 10a. Connector (ADR-017)

| Método | Endpoint | Request | Response | Usado por |
|--------|----------|---------|----------|-----------|
| POST | `/connector/register` | `{connector_id, capabilities, protocol_version, device_label?}` | `map` | `ConnectorRegister()` |
| POST | `/connector/heartbeat` | `{connector_id}` | `map` | `ConnectorHeartbeat()` |
| GET | `/connector/jobs?connector_id=…` | — | `{items, transport}` | `PollJobs()` |
| POST | `/connector/jobs/{job_id}/result` | `{status, result?, error_code?}` | `map` | `submit_job_result` |
| POST | `/connector/inference-complete` | `{request_id, reply, model, usage}` | `map` | inference audit |

### 10b. Connector Context (Phase 3 🆕)

| Método | Endpoint | Request | Response | Usado por |
|--------|----------|---------|----------|-----------|
| PUT | `/connector/{id}/context` | `{connector_id, workspace_id?, repo_structure, active_file?, git_branch?, git_dirty, recent_changes?, open_files?}` | `{ok, stored}` | Connector push de snapshot → `ContextPipeline` L2 |
| GET | `/connector/{id}/context` | — | `{found, context?}` | Debug |

> **Phase 3**: Quando `connector_id` está definido no workspace binding, a L2 do `ContextPipeline` usa o contexto enviado pelo connector em vez de ler o filesystem local.

## 11. Health

| Método | Endpoint | Usado por |
|--------|----------|-----------|
| GET | `/health` | `Health()` |
| GET | `/health/ready` | `HealthReady()` |

---

## Problemas Encontrados

### P1 ✅ `createSessionFromHubCmd` removido (código morto)
- Função e tipo `hubSessionCreatedMsg` removidos. O handler em `root.go` também.
- A criação de sessão no hub agora só acontece via Enter no botão "Nova sessão" → `enterSessionMsg` → `ensureSessionCmd`.

### P2 ✅ `refreshSidebarCmd` já chama `GetUsage()` — sem ação necessária
- `GetUsage()` é chamado nas linhas 357-361 de `app.go`.
- `UsageTotalCost` e `WorkQueueCount` são corretamente populados.

### P3 ℹ️ `BindWorkspace` com `_` é intencional (fire-and-forget)
- Se o bind falhar, a sessão abre na mesma — soft failure aceitável.
- Bloquear o utilizador por falha de bind seria pior UX.

### P4 ℹ️ `GET /ui/sessions/{id}/surface` — OK no CLI
- Backend não inclui `session_id` na resposta, mas o CLI define a partir do parâmetro.

### P5 ℹ️ `ensureSessionCmd` — comportamento correto
- Sessão nova vem sem mensagens (`Phase: phaseIdle`).

---

## Fases — Migração Workspace → Connector

| Fase | Estado | Descrição |
|------|--------|-----------|
| 1 | ✅ | CLI: `WorkspaceTab.ConnectorID`, UI mostra `@connector` no hub |
| 2 | ✅ | Backend: `POST/GET /ui/workspace` aceitam `connector_id`, `path` opcional |
| 3 | ✅ | Backend: `PUT /connector/{id}/context`, ContextPipeline L2 usa connector context |
| 4 | ✅ | Backend: `GET /ui/sidebar` — endpoint consolidado (1 chamada substitui 5). CLI: fallback automático se indisponível |
