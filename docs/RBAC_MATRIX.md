# CentralChat — Matriz RBAC (Onda A)

> **UPDATED:** 2026-06-16  
> **Fonte:** `app/auth.py`, `app/shared/rbac.py`, `app/admin_routes.py`, `app/org_memberships.py`, `app/shared/secrets_admin.py`, `app/session_acl.py`, `app/team_requests.py`, `app/work_queue.py`  
> **JWT:** claim `role` (`viewer` | `developer` | `reviewer` | `lead` | `approver` | `auditor` | `admin`)

## Roles

| Role | Descrição |
|------|-----------|
| `developer` | Uso diário: chat, approvals, workspace |
| `reviewer` | Revisão operacional de work items e sessões compartilhadas |
| `lead` | Liderança de equipe; coordena fila, revisão e governança operacional |
| `approver` | Aprova ações HITL; visão operacional |
| `viewer` | Leitura supervisão (sem export sensível) |
| `auditor` | Audit export/report; compliance read |
| `admin` | Break-glass, compliance apply, config enterprise |

Utilizadores e2e/staging: `scripts/seed_e2e_users.py`.

> **Transição org-scope:** novos acessos operacionais devem migrar para `memberships`
> (`scope_type = organization | group | project`) conforme `ADMIN_PROFESSIONALIZATION_PLAN.md`.
> O JWT role continua existindo para compatibilidade e bootstrap administrativo.

## Endpoints admin (JWT required)

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/admin/audit/events` | GET | viewer, auditor, admin, developer, approver |
| `/admin/audit/export` | GET | auditor, admin |
| `/admin/audit/report` | GET | auditor, admin |
| `/admin/policies` | GET | developer, approver, admin, auditor, viewer |
| `/admin/usage/summary` | GET | admin, auditor, approver |
| `/admin/compliance/packs` | GET | admin, auditor, approver |
| `/admin/compliance/packs/{id}` | GET | admin, auditor, approver |
| `/admin/compliance/apply` | POST | admin |
| `/admin/break-glass/active` | GET | admin, auditor |
| `/admin/break-glass/grant` | POST | admin |
| `/admin/break-glass/revoke` | POST | admin |
| `/admin/deployment` | GET | admin, auditor |

## Organização e memberships

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/admin/users` | GET | admin, lead, auditor |
| `/admin/users` | POST | admin |
| `/admin/users/{id}` | PATCH | admin; alteração do próprio `role` retorna 403 |
| `/admin/users/{id}/reset-password` | POST | admin |
| `/admin/users/{id}/revoke-sessions` | POST | admin |
| `/admin/users/{id}/memberships` | GET | admin, lead, auditor + filtro por escopo |
| `/admin/org/tree` | GET | developer, lead, auditor, admin + escopo via memberships |
| `/admin/org/health` | GET | lead, auditor, admin + escopo via memberships |
| `/admin/groups` | POST | admin |
| `/admin/groups/{id}` | PATCH | admin |
| `/admin/projects` | POST | admin |
| `/admin/projects/{id}` | PATCH | admin ou lead do project/group |
| `/admin/projects/{id}/members` | GET | admin ou lead do project/group |
| `/admin/projects/{id}/members/{user_id}` | PUT | admin ou lead do project/group |
| `/admin/projects/{id}/members/{user_id}` | DELETE | admin ou lead do project/group |

## Segredos e inferência

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/admin/secrets` | GET | admin, auditor |
| `/admin/secrets/{key}` | PUT | admin |
| `/admin/secrets/{key}` | DELETE | admin |
| `/admin/secrets/{key}/test` | POST | admin |
| `/admin/inference/status` | GET | admin, auditor |
| `/admin/inference/providers` | GET | admin, auditor |
| `/admin/inference/providers/{id}` | PUT | admin |
| `/admin/inference/providers/{id}/test` | POST | admin |
| `/admin/inference/models/global` | GET/PUT | auditor+admin / admin |

## Work queue

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/ui/work-items` | GET | viewer, developer, reviewer, lead, approver, auditor, admin |
| `/ui/work-items` | POST | developer, reviewer, lead, approver, admin |
| `/ui/work-items/{id}` | GET | viewer, developer, reviewer, lead, approver, auditor, admin |
| `/ui/work-items/{id}` | PATCH | developer, reviewer, lead, approver, admin |
| `/ui/work-items/{id}/events` | GET | viewer, developer, reviewer, lead, approver, auditor, admin |
| `/ui/work-items/{id}/comments` | GET/POST | GET: viewer+; POST: developer, reviewer, lead, approver, admin |
| `/ui/work-items/{id}/link` | POST | developer, reviewer, lead, approver, admin |
| `/ui/work-items/{id}/work` | POST | developer, reviewer, lead, approver, admin |

## Sessões compartilháveis

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/admin/sessions/{id}` | GET | developer, lead, auditor, admin, reviewer, viewer (ACL) |
| `/admin/sessions/{id}/acl` | GET/PUT | lead, admin |
| `/admin/sessions/{id}/acl/{type}/{id}` | DELETE | lead, admin |

## Solicitações contextuais

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/admin/requests` | GET | developer, lead, auditor, admin, reviewer |
| `/admin/requests` | POST | developer, lead, admin |
| `/admin/requests/{id}` | GET | developer, lead, auditor, admin, reviewer |
| `/admin/requests/{id}/comments` | GET/POST | developer, lead, auditor, admin, reviewer |
| `/admin/requests/{id}/resolve` | POST | lead, admin, auditor |

## Catálogo de agentes e skills

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/ui/team/agents` | GET | viewer, developer, reviewer, lead, approver, auditor, admin |
| `/ui/team/agents` | POST | developer, lead, admin |
| `/ui/team/agents/{id}` | PATCH | developer, lead, admin (draft) |
| `/ui/team/agents/{id}/submit-review` | POST | developer, lead, admin |
| `/ui/team/agents/{id}/publish` | POST | lead, admin |
| `/ui/team/skills` | GET | viewer, developer, reviewer, lead, approver, auditor, admin |
| `/ui/team/skills` | POST/PATCH/submit/publish | igual agentes |

## Regras de equipa

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/ui/team/rules` | GET | viewer, developer, reviewer, lead, approver, auditor, admin |
| `/ui/team/rules` | POST | developer, lead, admin |
| `/ui/team/rules/{id}` | PATCH | lead, admin |
| `/ui/team/rules/{id}/approve` | POST | lead, admin |
| `/ui/team/rules/{id}/reject` | POST | lead, admin |

## Policy bundles

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/admin/policies` | GET | developer, lead, auditor, admin, reviewer, viewer (snapshot legado) |
| `/admin/policies/active` | GET | developer, lead, auditor, admin, reviewer, viewer |
| `/admin/policies/history` | GET | lead, auditor, admin |
| `/admin/policies/drafts` | POST | lead, admin |
| `/admin/policies/drafts/{id}/publish` | POST | lead, admin |
| `/admin/policies/rollback` | POST | admin |

## Operação enterprise (P5)

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/admin/deploy/status` | GET | admin, auditor |
| `/admin/deploy/residency` | GET | admin, auditor |
| `/admin/siem/outbox` | GET | admin, auditor |
| `/admin/siem/outbox/process` | POST | admin |
| `/admin/break-glass/active` | GET | admin, auditor |
| `/admin/break-glass/grant` | POST | admin |
| `/admin/break-glass/{id}` | DELETE | admin |
| `/admin/audit/exports` | GET/POST | auditor, admin |
| `/admin/audit/exports/{id}` | GET | auditor, admin |
| `/admin/audit/exports/{id}/download` | GET | auditor, admin |

## Integrações

| Endpoint | Método | Roles permitidas |
|----------|--------|------------------|
| `/integrations/github/*` (mutações) | * | approver, admin, developer |

## Rotas públicas (sem Bearer)

`/health`, `/health/ready`, `/metrics`, `/auth/login`, `/auth/refresh`, `/auth/public-config`, `/docs*`.

## Ambiente

| Ambiente | `CENTRAL_JWT_MODE` |
|----------|-------------------|
| Dev local | `optional` (default) |
| Staging / CI e2e | `required` (`docker-compose.e2e.override.yml`) |

## Testes

- Unit: `tests/test_rbac_roles.py`
- E2E: stack com override e2e + `scripts/seed_e2e_users.py`
