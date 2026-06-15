# CentralChat — Runbook staging (< 45 min)

> **UPDATED:** 2026-06-15  
> **Audiência:** engenharia / ops  
> **Stack:** `docker-compose.dev.yml` + `docker-compose.e2e.override.yml` (JWT required)

## Pré-requisitos (5 min)

- Docker/Podman + Compose
- Go 1.22+ (build CLI)
- Python 3.12+ (testes locais opcionais)
- Portas livres: `8004` (API), `5433` (Postgres), `5174` (web opcional)

## 1. Clone e env (10 min)

```bash
cd CentralChat
# Garantir vhosts e .env do backend (ver README-MVP.md)
cp -n vhosts/CentralChat_Backend/.env.example vhosts/CentralChat_Backend/.env
# Editar: CENTRAL_JWT_SECRET (≥32 chars), MEMORY_DB_URL se necessário
```

**Fail-fast:** arranque aborta com mensagem clara se:
- `AUTH_LOGIN_ENABLED=1` sem `MEMORY_DB_URL`
- `CENTRAL_APP_ENV=staging` com `CENTRAL_JWT_MODE=off`

## 2. Subir stack staging (15 min primeira vez)

**Atalho (recomendado — inclui alertas + Prometheus locais):**

```bash
./scripts/staging_up.sh
```

Equivalente manual:

```bash
docker compose -f docker-compose.dev.yml \
  -f docker-compose.e2e.override.yml \
  -f docker-compose.staging.override.yml \
  -f docker-compose.staging.ops.override.yml up -d --build
```

Aguardar healthy:

```bash
curl -sf http://127.0.0.1:8004/health
curl -sf http://127.0.0.1:8004/health/ready
```

Ou: `./startup-testing.sh --status`

## 3. Seed utilizadores (2 min)

```bash
docker exec central-orchestrator python scripts/seed_e2e_users.py
```

| Email | Password | Role |
|-------|----------|------|
| dev@local.test | changeme | developer |
| approver@local.test | changeme | approver |
| auditor@local.test | changeme | auditor |

## 4. Build CLI (3 min)

```bash
cd vhosts/CentralChat_CLI && go build -o central ./cmd/central
export PATH="$PWD:$PATH"
central login --email dev@local.test --password changeme --api http://127.0.0.1:8004
central workspace .
central doctor
```

## 5. Smoke manual (5 min)

```bash
central daemon &          # outro terminal
# criar approval de teste ou central ask (opcional)
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8004/config
```

## 6. Suite automatizada (5 min)

```bash
./scripts/run_e2e.sh
```

## 7. Daemon — crash recovery (B1.2)

O daemon CLI (`central daemon`) executa jobs locais. Em staging/produção, usar **restart automático**:

```ini
# ~/.config/systemd/user/central-daemon.service
[Unit]
Description=Central local executor
After=network.target

[Service]
ExecStart=%h/.local/bin/central daemon
Restart=on-failure
RestartSec=5
Environment=CENTRAL_CONFIG_HOME=%h/.config/central

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now central-daemon.service
```

**Jobs órfãos:** se o daemon morrer com job em `running`, o lease expira (`CENTRAL_CLIENT_JOB_LEASE_SECONDS`, default 120s) e o backend re-enfileira até `CENTRAL_CLIENT_JOB_MAX_RETRIES` (default 3). Verificar com `central doctor`.

## Política de ambientes (decisão D-HITL-1)

| Ambiente | `CENTRAL_APP_ENV` | Write após approve |
|----------|-------------------|-------------------|
| Dev local | `development` | `direct_write` (disco local) |
| Staging | `staging` | `pr_only` (PR/MR — Onda C) |
| Produção | `production` | `pr_only` |

Override e2e usa `development` para testes de write local; staging real usa `CENTRAL_APP_ENV=staging`.

## 8. OIDC / Keycloak (Onda C1)

Stack com IdP local (profile `oidc` + override de env no orchestrator):

```bash
docker compose \
  -f docker-compose.dev.yml \
  -f docker-compose.e2e.override.yml \
  -f docker-compose.oidc.override.yml \
  --profile oidc up -d --build
```

Smoke (Keycloak + `auth_oidc_enabled`):

```bash
chmod +x scripts/smoke_oidc.sh
./scripts/smoke_oidc.sh
```

| Recurso | URL |
|---------|-----|
| Keycloak admin | http://127.0.0.1:8180 (ver `.env` do backend) |
| Realm | `central` |
| Login web SSO | http://127.0.0.1:5174/login |
| Callback | `http://127.0.0.1:5174/oidc-callback` |

Utilizadores de teste no realm import (`deploy/keycloak/realm-central.json`):

| Email | Password | Grupo IdP | Role Central |
|-------|----------|-----------|--------------|
| dev@local.test | changeme | central-developers | developer |
| approver@local.test | changeme | central-approvers | approver |

`CENTRAL_OIDC_GROUP_ROLE_MAP` no override mapeia grupos → roles RBAC.  
`CENTRAL_APPROVAL_SEPARATION=1` em staging/prod (quem aprova ≠ quem pediu).

**Logout:** `POST /auth/logout` revoga refresh (`jti`); a UI chama o IdP `end_session_endpoint` quando OIDC está activo.

## 9. Staging enterprise (Onda C)

```bash
docker compose \
  -f docker-compose.dev.yml \
  -f docker-compose.e2e.override.yml \
  -f docker-compose.staging.override.yml \
  up -d --build
```

Activa: `pr_only`, `CENTRAL_APPROVAL_SEPARATION`, quota, DLP, retenção audit 365d.

GitHub App: ver `docs/GIT_INTEGRATION.md`. SIEM: `CENTRAL_SIEM_WEBHOOK_URLS` + worker `python scripts/siem_worker.py --once`.

CLI auth enterprise:

```bash
central login --device          # device code
central login --api-key ck_...  # API key
```

## Troubleshooting

| Sintoma | Acção |
|---------|--------|
| 429 login | Recriar orchestrator ou esperar janela rate-limit |
| Daemon não escreve | `central daemon` a correr + `central doctor` |
| `pr_only` em testes | Verificar `CENTRAL_APP_ENV` não é `staging` no override e2e |
| PG unhealthy | `docker compose logs postgres` |

## Referências

- `docs/RBAC_MATRIX.md`
- `docs/HARDENING_PLAN.md`
- `docs/RUNBOOK_BACKUP.md` — backup/restore PG (D1)
- `docs/COMPOSE_PARITY.md` — dev vs staging (D1.9)
- `docs/SLO.md` — SLO API/stream (D2.6)
- `docs/PILOT_INTERNAL.md` — piloto interno (D5)
- `deploy/helm/centralchat/README.md` — Helm install/upgrade/rollback
- `docs/CLI_UX_SPEC.md` — redesign TUI (onboarding, tabs, slash commands)
- `scripts/run_e2e.sh`
