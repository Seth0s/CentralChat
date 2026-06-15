# CentralChat — Matriz RBAC (Onda A)

> **UPDATED:** 2026-06-14  
> **Fonte:** `app/shared/rbac.py`, `app/admin_routes.py`, `app/integrations_routes.py`  
> **JWT:** claim `role` (`developer` | `approver` | `viewer` | `auditor` | `admin`)

## Roles

| Role | Descrição |
|------|-----------|
| `developer` | Uso diário: chat, approvals, workspace |
| `approver` | Aprova ações HITL; visão operacional |
| `viewer` | Leitura supervisão (sem export sensível) |
| `auditor` | Audit export/report; compliance read |
| `admin` | Break-glass, compliance apply, config enterprise |

Utilizadores e2e/staging: `scripts/seed_e2e_users.py`.

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
