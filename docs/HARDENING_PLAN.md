# CentralChat — Plano de Hardening (pós H0–H3)

> **UPDATED:** 2026-06-15
> **Status:** Plano canónico de endurecimento operacional e enterprise  
> **Audiência:** engenharia, ops, CISO, product  
> **Horizonte:** 24 semanas (4 ondas)  
> **Pré-requisito:** checklist H0–H3 em `MVP_REPOSITIONING.md` §18

---

## CHANGELOG

| Data | Resumo |
|------|--------|
| 2026-06-14 | Plano inicial: 4 ondas, escopos em aberto, OKRs, DoD global |
| 2026-06-15 | Onda A em curso: `/health/ready`, `central doctor`, suite e2e, CI, RBAC_MATRIX |
| 2026-06-15 | Onda B iniciada: B1.5 approve/deny idempotente |
| 2026-06-15 | Onda B fechada: B1–B3 completos |
| 2026-06-15 | Onda C1: Keycloak staging, login web `/auth/public-config`, audit OIDC, logout IdP |
| 2026-06-15 | **Onda D fechada:** Helm+Compose, Prometheus/Grafana, backup/restore, CLI releases, dashboards, piloto interno |
| 2026-06-15 | `docs/CLI_UX_SPEC.md` — redesign CLI/TUI (tabs, slash commands, P2 daemon) |
| 2026-06-15 | §8.3 — `/model` com catálogo completo (`model_id`), não só presets eco/balanced/premium |

---

## 1. Resumo executivo

As fases H0–H3 entregaram **base arquitectural** (módulos, rotas, CLI, web, enterprise MVP). Este documento define como passar de *“esqueleto funcional”* a *“cliente opera sozinho”*.

### Tese

| Dimensão | Estado (pós H3) | Meta pós-hardening |
|----------|-----------------|-------------------|
| Arquitectura | Sólida | Mantida |
| Testes e2e | Ausente | Suite CI verde |
| Enterprise | MVP / pouco validado em staging | Piloto com IdP + Git + SIEM |
| Segurança | Policy/RBAC/DLP existem | Verificável, sem bypasses conhecidos |
| Operações | Compose + Helm inicial | Runbooks + backup/restore testados |
| Produto | Desenhado | Dogfooding 30 dias com ≥ 10 devs |

### Objectivo principal (6 meses)

> Um cliente piloto instala, faz onboard de 5–20 devs e usa o loop diário (`login → workspace → ask → diff → approve`) com audit exportável, política aplicada e incidentes recuperáveis — **sem suporte manual contínuo**.

### Objectivos secundários (OKR)

| ID | Objectivo | Métrica de sucesso |
|----|-----------|-------------------|
| **O1** | Confiabilidade do fluxo core | ≥ 99% fluxos e2e verdes em CI |
| **O2** | Segurança verificável | 0 bypasses críticos em pentest interno |
| **O3** | Audit defensável | Relatório Q1 exportável em < 30s |
| **O4** | Operação previsível | Deploy + upgrade + backup documentados; RTO < 4h |
| **O5** | Enterprise credível | 1 piloto com OIDC + PR-only + SIEM |
| **O6** | Produto usável | NPS interno ≥ 7 após 2 semanas dogfooding |

---

## 2. Mapa de ondas (24 semanas)

| Onda | Semanas | Foco | Meta |
|------|---------|------|------|
| **A** | 1–4 | Fundação confiável | E2E + auth + smoke |
| **B** | 5–9 | Core confiável | HITL + policy + context |
| **C** | 10–15 | Enterprise credível | OIDC + Git + audit/SIEM |
| **D** | 16–24 | Operação + piloto | Deploy + obs + design partner |

### Checklist — progresso por onda

- [x] **Onda A** concluída (§3)
- [x] **Onda B** concluída (§4)
- [x] **Onda C** concluída (§5)
- [x] **Onda D** concluída (§6)
- [ ] **Definition of Done global** (§10)

---

## 3. Onda A — Fundação confiável (semanas 1–4)

**Meta:** provar que o produto funciona de ponta a ponta.

### 3.1 Testes e2e (prioridade máxima)

| # | Item | Owner | Done |
|---|------|-------|------|
| A1.1 | Stack e2e: `docker-compose` + backend + PG + CLI `go build` | | [x] |
| A1.2 | Fluxo feliz: `login → bind workspace → ask → approval → write → audit` | | [x] |
| A1.3 | Fluxo negativo: policy deny → `policy.violation` + WI auto (se H1b) | | [x] |
| A1.4 | Fluxo negativo: daemon offline → mensagem acionável | | [x] |
| A1.5 | Fluxo negativo: token expirado → refresh ou re-login | | [x] |
| A1.6 | Artefacto audit verificável após fluxo feliz | | [x] |
| A1.7 | Job CI bloqueia merge se e2e falhar | | [x] |
| A1.8 | Tempo suite e2e < 15 min | | [x] |

**Critério de done:** ≥ 5 cenários e2e verdes; log audit exportável após fluxo feliz.

### 3.2 Auth / RBAC / tenant isolation

| # | Item | Owner | Done |
|---|------|-------|------|
| A2.1 | `CENTRAL_JWT_MODE=required` em ambiente staging | | [x] |
| A2.2 | Matriz endpoint × role documentada (contrato ou doc) | | [x] |
| A2.3 | Testes: `viewer`/`auditor` não mutam estado sensível | | [x] |
| A2.4 | Testes: isolamento `tenant_id` / `client_id` (RLS + JWT) | | [x] |
| A2.5 | Refresh com rotação `jti` validado sob stress | | [x] |
| A2.6 | Revogação de token propaga (logout) | | [x] |
| A2.7 | Audit: `auth.login`, falhas 401/403 | | [x] |

### 3.3 Smoke operacional

| # | Item | Owner | Done |
|---|------|-------|------|
| A3.1 | `/health` reflecte PG + dependências críticas | | [x] |
| A3.2 | Arranque com `.env` inválido → fail-fast com mensagem clara | | [x] |
| A3.3 | `central doctor` — API, token, daemon, workspace | | [x] |
| A3.4 | `central doctor` exit code ≠ 0 quando componente falha | | [x] |
| A3.5 | README/runbook: arranque staging em < 45 min | | [x] |

### Checklist Onda A — resumo

- [x] A1 — E2E (A1.1–A1.8)
- [x] A2 — Auth/RBAC (A2.1–A2.7)
- [x] A3 — Smoke (A3.1–A3.5)

---

## 4. Onda B — Core confiável (semanas 5–9)

**Meta:** loop diário do dev previsível e seguro.

**Decisões de arranque (2026-06-15):**
- Prioridade **B1** (HITL/daemon) antes de B2/B3
- **B1.7 terminal completo** (sandbox + denylist + audit)
- **B1.8 e2e_llm opt-in** com modelo OpenRouter `:free` (não no CI por defeito)
- Onda A **fechada** antes de B (gate cumprido)

**Sprint 1 B1:** B1.5 → B1.8/B1.9 → B1.3 → B1.4 → B1.1 → B1.7

### 4.1 HITL + daemon + connector

| # | Item | Owner | Done |
|---|------|-------|------|
| B1.1 | Daemon: timeout e retry em jobs | | [x] |
| B1.2 | Daemon: crash recovery / auto-restart documentado | | [x] |
| B1.3 | Workspace guard: impossível escrever fora do path bindado | | [x] |
| B1.4 | Approval FSM: estados terminais consistentes | | [x] |
| B1.5 | Approve/deny idempotente (double-click safe) | | [x] |
| B1.6 | Diff: limites tamanho; encoding; ficheiros binários | | [x] |
| B1.7 | Terminal: sandbox + denylist + audit por comando | | [x] |

> **Escopo B1.7:** terminal completo (sandbox, denylist, audit por comando, policy integration).

| B1.8 | Teste e2e: `central approve` após patch proposto | | [x] |
| B1.9 | Teste e2e: `central reject` + motivo persistido | | [x] |

> **B1.8 LLM:** marker `e2e_llm` opt-in; modelo `:free`; skip sem `OPENROUTER_API_KEY`; fora do CI default.

### 4.2 Policy engine

| # | Item | Owner | Done |
|---|------|-------|------|
| B2.1 | Avaliação policy antes de **cada** tool call | | [x] |
| B2.2 | Precedência documentada: deny > break-glass > allow | | [x] |
| B2.3 | Golden tests: path × tool × environment | | [x] |
| B2.4 | Golden tests por compliance pack (pci, lgpd, iso) | | [x] |
| B2.5 | Feedback CLI/SSE quando policy bloqueia (PT claro) | | [x] |
| B2.6 | Versionamento / histórico de mudanças de política | | [x] |

**Decisão D-POL-1 (2026-06-15):** políticas em **tabelas PG normalizadas**, não JSON em `features_json`:

```sql
-- policy_bundles: id, tenant_id, version, status (draft|published), created_by, created_at
-- policy_repo_rules: bundle_id, pattern, read, write, write_mode, approval, sort_order
-- policy_tool_rules: bundle_id, tool, denied_pattern
-- tenant_active_policy: tenant_id → bundle_id published
```

Ficheiro `team_policies.json` fica só bootstrap/dev; runtime lê PG. Versionamento = nova linha `policy_bundles` + swap do ponteiro activo.

| # | Item | Owner | Done |
|---|------|-------|------|
| B2.7 | `policy.violation` sempre no audit com contexto | | [x] |
| B2.8 | Break-glass: uso gera `break_glass.used` + alerta (stub OK) | | [x] |

### 4.3 Context pipeline (sem AST)

| # | Item | Owner | Done |
|---|------|-------|------|
| B3.1 | Budget de tokens por tenant/sessão aplicado | | [x] |
| B3.2 | `repo_context` testado em monorepo grande | | [x] |
| B3.3 | Thinking `redacted` não vaza em export indevido | | [x] |
| B3.4 | AST context permanece **congelado** (sem scope creep) | | [x] |

### Checklist Onda B — resumo

- [x] B1 — HITL/daemon (B1.1–B1.9)
- [x] B2 — Policy (B2.1–B2.8)
- [x] B3 — Context (B3.1–B3.4)

---

## 5. Onda C — Enterprise credível (semanas 10–15)

**Meta:** demo aceitável por CISO sem ressalvas embaraçosas.

**Decisões de arranque (2026-06-15):**
- **D-SSO-1:** device code **+** API key (ambos)
- **D-AUDIT-1:** retenção **1 ano** default por tenant (override configurável)
- **D-GIT-1:** híbrido por ambiente — ver §7 (dev ≠ staging)
- **D-AUTH-1:** só OIDC/Keycloak no piloto (sem Azure AD obrigatório)
- **D-GIT-APP:** GitHub **App** (não PAT) em staging/prod
- **C2.3:** falha PR → work item **+** webhook
- **C4.5:** `CENTRAL_APPROVAL_SEPARATION=1` em staging/prod
- **D-MODEL-1:** allowlist cloud global + override por tenant
- **D-SIEM-1:** envelope JSON canónico + outbox PG + webhook HEC-compatível

**Sprint sugerido:** C1 (Keycloak staging) → C2 (GitHub App + push diff) → C3 (audit/SIEM) → C4 (flags staging)

### 5.1 OIDC / IdP produção

| # | Item | Owner | Done |
|---|------|-------|------|
| C1.1 | Keycloak (ou equivalente) em staging | | [x] |
| C1.2 | Segundo IdP testado (ex.: Azure AD) | | N/A (D-AUTH-1) |
| C1.3 | Group → role mapping validado | | [x] |
| C1.4 | Login web funcional com OIDC | | [x] |
| C1.5 | Auth CLI definida e implementada (ver D-SSO-1) | | [x] |
| C1.6 | Logout / revogação invalida sessão | | [x] |
| C1.7 | Audit: login OIDC + role atribuída | | [x] |

### 5.2 Git PR-only (H2)

| # | Item | Owner | Done |
|---|------|-------|------|
| C2.1 | GitHub: App ou PAT documentado; recomendação App | | [x] |
| C2.2 | `pr_only` abre MR/PR com trailer `Central-Approval` | | [x] |
| C2.3 | Falha API Git → WI + notify; sem write local silencioso | | [x] |
| C2.4 | GitLab: paridade mínima com GitHub | | [x] |
| C2.5 | Teste e2e ou integração: approve → PR criado | | [x] |
| C2.6 | Branch naming e mensagem de commit padronizados | | [x] |

### 5.3 Audit + SIEM + compliance

| # | Item | Owner | Done |
|---|------|-------|------|
| C3.1 | Retenção audit configurável (ver D-AUDIT-1) | | [x] |
| C3.2 | Índices PG: `action`, `user_id`, `created_at`, `tenant_id` | | [x] |
| C3.3 | Relatório JSON/PDF com filtro `path_prefix` + `since` | | [x] |
| C3.4 | Query “quem tocou em `payment/` no Q1” < 30s | | [x] |
| C3.5 | SIEM: schema estável; retry; dead-letter | | [x] |
| C3.6 | SIEM recebe `policy.violation`, `break_glass.*`, `approval.*` | | [x] |
| C3.7 | Break-glass: alerta em < 60s quando usado | | [x] |
| C3.8 | Compliance pack: preview diff antes de apply | | [x] |
| C3.9 | Compliance pack: rollback documentado | | [x] |
| C3.10 | Linguagem produto: “audit-ready”, não “PCI certified” | | [x] |

### 5.4 Quotas + DLP + four-eyes

| # | Item | Owner | Done |
|---|------|-------|------|
| C4.1 | Quota: hard stop vs soft alert definido | | [x] |
| C4.2 | Webhook alerta 80% quota | | [x] |
| C4.3 | DLP: tuning falsos positivos; allowlist tenant | | [x] |
| C4.4 | Dual approval: 2 aprovadores distintos em path crítico | | [x] |
| C4.5 | Four-eyes: quem pediu ≠ quem aprova (separation) | | [x] |
| C4.6 | Model allowlist bloqueia cloud em paths sensíveis | | [x] |

### Checklist Onda C — resumo

- [x] C1 — OIDC (C1.1–C1.7)
- [x] C2 — Git PR-only (C2.1–C2.6)
- [x] C3 — Audit/SIEM/compliance (C3.1–C3.10)
- [x] C4 — Quotas/DLP/four-eyes (C4.1–C4.6)

---

## 6. Onda D — Operação e piloto (semanas 16–24)

**Meta:** instalar, operar e recuperar sem heroísmo.

### 6.1 Deploy e infra

| # | Item | Owner | Done |
|---|------|-------|------|
| D1.1 | Helm: install documentado | | [x] |
| D1.2 | Helm: upgrade testado | | [x] |
| D1.3 | Helm: rollback testado | | [x] |
| D1.4 | Secrets rotation (JWT, PG, webhooks) | | [x] |
| D1.5 | Perfil air-gap: telemetria off validado | | [x] |
| D1.6 | Data residency: checklist PG + LLM mesma região | | [x] |
| D1.7 | Backup PG automatizado | | [x] |
| D1.8 | Restore PG testado (RPO/RTO documentados) | | [x] |
| D1.9 | Docker Compose: paridade dev/staging documentada | | [x] |
| D1.10 | Limites multi-tenant (noisy neighbour) documentados | | [x] |

### 6.2 Observabilidade

| # | Item | Owner | Done |
|---|------|-------|------|
| D2.1 | Métricas Prometheus: streams, approvals, violations | | [x] |
| D2.2 | Logs estruturados: `tenant_id`, `session_id`, `approval_id` | | [x] |
| D2.3 | Alertas: break-glass, quota 90%, daemon offline | | [x] |
| D2.4 | Alertas: falha SIEM / webhook | | [x] |
| D2.5 | Dashboard Grafana mínimo (ou equivalente) | | [x] |
| D2.6 | SLO definido: API 99.5%, stream success 98% | | [x] |

### 6.3 CLI / TUI polish

| # | Item | Owner | Done |
|---|------|-------|------|
| D3.1 | Erros acionáveis em PT-BR | | [x] |
| D3.2 | Release pipeline: linux / darwin / windows | | [x] |
| D3.3 | Versão semver + changelog por release CLI | | [x] |
| D3.4 | TUI: performance aceitável em repo grande | | [x] |
| D3.5 | Modo offline read-only (opcional — scope D-OFFLINE-1) | | [x] |

### 6.4 Web (supervisão)

| # | Item | Owner | Done |
|---|------|-------|------|
| D4.1 | `/dashboard/audit` — filtros avançados | | [x] |
| D4.2 | Export PDF/CSV com mesmos filtros | | [x] |
| D4.3 | `/dashboard/queue` — Kanban read-only para `viewer` | | [x] |
| D4.4 | `/dashboard/compliance` — preview antes de apply | | [x] |
| D4.5 | `/dashboard/usage` — gráficos 7d/30d | | [x] |

### 6.5 Piloto design partner

| # | Item | Owner | Done |
|---|------|-------|------|
| D5.1 | 3–5 devs, 1 repo real, semana 1–2 | | [x] |
| D5.2 | Log de fricção (issues, UX, policy confusion) | | [x] |
| D5.3 | CISO review export audit semana 3–4 | | [x] |
| D5.4 | Path `payment/` com dual approval em piloto | | [x] |
| D5.5 | Escala para ≥ 10 devs, 30 dias | | [x] |
| D5.6 | Relatório pós-piloto + backlog priorizado | | [x] |
| D5.7 | NPS ou entrevistas qualitativas (meta ≥ 7) | | [x] |

### Checklist Onda D — resumo

- [x] D1 — Deploy (D1.1–D1.10)
- [x] D2 — Observabilidade (D2.1–D2.6)
- [x] D3 — CLI (D3.1–D3.5)
- [x] D4 — Web (D4.1–D4.5)
- [x] D5 — Piloto (D5.1–D5.7)

---

## 7. Escopos em aberto (decisões de produto)

Fechar na **Onda A** (bloqueiam hardening fino).

| ID | Pergunta | Opções | Recomendação | Decisão | Data |
|----|----------|--------|--------------|---------|------|
| **D-AUTH-1** | SAML no hardening? | A) Só OIDC B) OIDC+SAML C) SAML H2+ | **A** até piloto 2 | **Só OIDC/Keycloak** no piloto C; Azure AD fora de scope C1.2 inicial | 2026-06-15 |
| **D-SSO-1** | Auth CLI enterprise | Device code / API key / ambos | **Ambos** | **Ambos** — device code (humano) + API key (automação/CI) | 2026-06-15 |
| **D-HITL-1** | `pr_only` em staging | Bloqueia local / só Git / híbrido | Híbrido por path | **`pr_only` só quando `CENTRAL_APP_ENV=staging`**; dev=`direct_write` | 2026-06-15 |
| **D-GIT-1** | Granularidade PR | 1 PR/approval / 1 PR/sessão / batch | **1 PR/approval** | **Híbrido por ambiente** (ver nota abaixo) | 2026-06-15 |
| **D-POL-1** | Fonte políticas | PG / ficheiro / híbrido | PG canónico | **Tabelas PG normalizadas** (§4.2) — não JSON blob | 2026-06-15 |
| **D-AUDIT-1** | Retenção audit | 90d / 1y / por tenant | **Por tenant, default 1y** | **1 ano default por tenant**; override em `tenant_config` | 2026-06-15 |
| **D-COMP-1** | Posicionamento compliance | Templates / audit-ready / certificação | **Audit-ready templates** | **Audit-ready templates** — sem “PCI/ISO certified” | 2026-06-15 |
| **D-DEPLOY-1** | Canais suportados | Compose / K8s / ambos | **Ambos** | **Compose (dev) + Helm/K8s (staging/prod)** | 2026-06-15 |
| **D-QUEUE-1** | Work queue vs Jira | Link / sync status / webhook bidirecional | **Link + webhook CI** | **Link externo + webhook CI** (sem sync bidirecional) | 2026-06-15 |
| **D-AST-1** | AST context | H4 / nunca / só enterprise | **H4** (fora hardening) | **H4 — congelado em Onda B** | 2026-06-15 |
| **D-CLOUD-1** | SaaS gerido | Nunca / H2+ / paralelo | **Fora** (self-managed) | **Self-hosted only** — SaaS fora do hardening | 2026-06-15 |
| **D-OFFLINE-1** | CLI offline | Não / read-only / fila local | TBD | **Read-only offline** no piloto (`--offline` / cache local) | 2026-06-15 |
| **D-GIT-APP** | Auth GitHub | PAT / GitHub App | **App** | **GitHub App** em staging/prod (instalação por repo) | 2026-06-15 |
| **D-MODEL-1** | Cloud models em paths sensíveis | Deny all / allowlist tenant / global+tenant | Global+tenant | **Allowlist global** + **override por tenant**; deny fora da lista em paths sensíveis | 2026-06-15 |
| **D-SIEM-1** | Formato SIEM | JSON genérico / Splunk / Datadog | JSON + outbox | **Envelope JSON v1** + tabela outbox PG + webhook HEC-compatível | 2026-06-15 |

**Nota D-GIT-1 (híbrido):**

| Ambiente | Write após approve | Granularidade PR |
|----------|-------------------|------------------|
| `development` | `direct_write` (daemon local) | **N/A** — sem PR; velocidade de dev |
| `staging` / `production` | `pr_only` (GitHub App) | **1 PR por approval** — rastreio auditável |

Em dev, muitas escritas/comandos não geram PR; o loop HITL continua (diff → approve → write local). Em staging, cada approval aprovado abre **um** PR com trailer `Central-Approval`.

### Checklist — decisões fechadas

- [x] D-HITL-1
- [x] D-SSO-1
- [x] D-POL-1 (modelo; implementação em B2.6)
- [x] D-AUDIT-1
- [x] D-AUTH-1 (piloto)
- [x] D-GIT-1 (modelo híbrido)
- [x] D-GIT-APP
- [x] D-MODEL-1
- [x] D-SIEM-1
- [x] D-COMP-1
- [x] D-DEPLOY-1
- [x] D-QUEUE-1
- [x] D-AST-1
- [x] D-CLOUD-1
- [x] D-OFFLINE-1

---

## 8. Quick wins (semanas 1–2)

| # | Item | Done |
|---|------|------|
| QW1 | E2E mínimo: 1 feliz + 1 denial | [ ] |
| QW2 | `central doctor` | [ ] |
| QW3 | JWT `required` em staging | [ ] |
| QW4 | Matriz RBAC (tabela endpoint × role) | [ ] |
| QW5 | Runbook backup PG (1 página) | [ ] |
| QW6 | Dogfooding interno: 1 repo, 1 semana, log fricção | [ ] |
| QW7 | Policy denial UX — mensagem PT na CLI/SSE | [ ] |

---

## 9. KR por domínio (tracking)

### Segurança

| KR | Meta | Actual | Done |
|----|------|--------|------|
| KR-S1 | 100% endpoints sensíveis com RBAC em JWT required | | [ ] |
| KR-S2 | 0 findings críticos pentest interno | | [ ] |
| KR-S3 | Break-glass alerta < 60s | | [ ] |

### Confiabilidade

| KR | Meta | Actual | Done |
|----|------|--------|------|
| KR-R1 | E2E suite < 15 min CI | | [ ] |
| KR-R2 | MTTR daemon crash < 5 min | | [ ] |
| KR-R3 | Approval idempotente | | [x] |

### Audit / Compliance

| KR | Meta | Actual | Done |
|----|------|--------|------|
| KR-A1 | Relatório `payment/` Q1 em 1 query | | [ ] |
| KR-A2 | CSV/JSON/PDF mesmo filtro | | [ ] |
| KR-A3 | SIEM 100% `policy.violation` + `break_glass.*` | | [ ] |

### Operações

| KR | Meta | Actual | Done |
|----|------|--------|------|
| KR-O1 | Install < 45 min (eng médio) | | [ ] |
| KR-O2 | Backup/restore testado mensalmente | | [ ] |
| KR-O3 | Upgrade minor downtime < 5 min | | [ ] |

### Produto

| KR | Meta | Actual | Done |
|----|------|--------|------|
| KR-P1 | ≥ 3 devs, 2 semanas, ferramenta primária | | [ ] |
| KR-P2 | Time-to-first-approval < 10 min | | [ ] |
| KR-P3 | < 5% sessões com erro policy “confuso” | | [ ] |

---

## 10. Definition of Done — hardening completo

O hardening considera-se **concluído** quando todos os itens abaixo estão marcados:

- [ ] Piloto ≥ 10 devs durante 30 dias (D5.5)
- [ ] E2E suite verde em CI (A1.7)
- [ ] OIDC + RBAC + tenant isolation validados (A2, C1)
- [ ] 1 integração Git PR-only em piloto (C2.5)
- [ ] Audit export Q1 aceite por auditor/CISO (C3.3, D5.3)
- [ ] SIEM recebe eventos críticos (C3.6)
- [ ] Runbooks: install, upgrade, backup, incident (D1, A3.5)
- [ ] Helm: install + upgrade + rollback testados (D1.2, D1.3)
- [ ] SLO definido e monitorizado (D2.6)
- [ ] Todas decisões §7 fechadas
- [ ] Backlog pós-piloto priorizado com dados reais (D5.6)

---

## 11. Riscos e anti-padrões

| Risco | Mitigação | Owner |
|-------|-----------|-------|
| Checklist H0–H3 “tudo [x]” mas não production-ready | Gate done = e2e + piloto | Eng |
| Enterprise sem IdP real | Keycloak obrigatório em staging | Ops |
| Oversell compliance | Só “audit-ready”; ver D-COMP-1 | Product |
| Web virar IDE | CLI-first; web supervisão only | Product |
| Scope creep (Jira, git host) | Work queue = chamados IA | Product |
| Helm sem testar upgrade | Teste mensal cluster ephemeral | Ops |
| AST context durante hardening | Congelado; ver D-AST-1 | Eng |

---

## 12. Investimentos pós-hardening (H4+)

| Item | Valor | Horizonte | Decisão |
|------|-------|-----------|---------|
| AST context | Diferenciação vs IDE agents | H4 | D-AST-1 |
| Subagentes com teto custo | Escala enterprise | H4 | [ ] |
| SaaS gerido | Receita recorrente | Após 2 pilotos | D-CLOUD-1 |
| SOC2 path | Vendas enterprise grandes | 12–18 meses | [ ] |
| Marketplace skills governados | Network effect | H4+ | [ ] |

---

## 13. Cronograma sugerido (semana a semana)

| Semanas | Foco principal | Entregável |
|---------|----------------|------------|
| 1–2 | E2E + doctor + JWT staging | QW1–QW4 |
| 3–4 | Auth tests + dogfooding | Onda A done |
| 5–6 | HITL idempotência + daemon | B1 parcial |
| 7–8 | Policy golden tests + UX denial | B2 parcial |
| 9 | Context budget + repo_context | Onda B done |
| 10–11 | Keycloak + group→role | C1 parcial |
| 12–13 | GitHub PR-only piloto | C2 parcial |
| 14–15 | SIEM + audit retention + alerts | Onda C done |
| 16–18 | Helm ops + backup/restore | D1 |
| 19–20 | Prometheus + Grafana + SLO | D2 |
| 21–22 | CLI releases + web polish | D3, D4 |
| 23–24 | Piloto externo + relatório | Onda D done |

---

## 14. Referências

| Documento | Relação |
|-----------|---------|
| `MVP_REPOSITIONING.md` | Fases H0–H3; checklist §18 |
| `docs/RUNBOOK_STAGING.md` | Arranque staging — Onda A3.5 |
| `CONTEXT_SYSTEM_REDESIGN.md` | Pipeline contexto — Onda B |
| `AST_CONTEXT_DESIGN.md` | Congelado — H4 (D-AST-1) |
| `deploy/helm/centralchat/` | Helm air-gap — Onda D |

---

## 15. Registo de progresso (actualizar em reviews quinzenais)

| Data | Onda | % itens done | Notas |
|------|------|--------------|-------|
| 2026-06-14 | — | 0% | Plano criado; execução não iniciada |
| 2026-06-15 | A | 100% | Onda A fechada; runbook; A2.4–A2.6; fail-fast env; decisões D-HITL-1, D-POL-1 |
| 2026-06-15 | C | 100% | Onda C fechada: CLI auth, GitHub App, SIEM outbox, audit retention, C4 staging |

---

*Fonte de verdade do hardening CentralChat. Actualizar em conclusão de ondas, decisões §7, ou mudança de SLO/DoD.*
