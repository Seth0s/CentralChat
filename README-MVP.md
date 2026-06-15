# CentralChat MVP — Quickstart

**Control plane self-hosted** para agentes de código — **CLI-first**, equipa/empresa, aprovação obrigatória, audit e fila de chamados.

Documentação completa: [`docs/MVP_REPOSITIONING.md`](docs/MVP_REPOSITIONING.md)

---

## Requisitos

- Docker (ou Podman com `docker` alias)
- Chave [OpenRouter](https://openrouter.ai/) (para o LLM)

---

## 5 minutos até ao chat

```bash
cd CentralChat

# Primeira vez: clonar vhosts (Backend + Frontend)
./clone-pull.sh

# Subir stack dev (Postgres + API + UI)
./startup-testing.sh
```

Abrir: **http://127.0.0.1:5174**

| Campo | Valor |
|-------|-------|
| Email | `dev@local.test` |
| Password | `changeme` |

API health: http://127.0.0.1:8004/health

### API para o CLI (Fase 0+)

| Item | Valor |
|------|-------|
| Base URL | `http://127.0.0.1:8004` |
| Login | `POST /auth/login` |
| Stream | `POST /assistant/text/stream` (SSE) |
| Sessões | `GET/POST /ui/chat-sessions/*` |
| Approvals | `GET /approvals`, `POST /approvals/{id}/approve` |
| OpenAPI (product mode) | http://127.0.0.1:8004/docs — com `CENTRAL_PRODUCT_MODE=1` no `.env` |
| Workspace header | `X-Central-Workspace: /abs/path` (Fase 1 CLI) |

```bash
# Smoke: login + health
curl -s http://127.0.0.1:8004/health
curl -s -X POST http://127.0.0.1:8004/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"dev@local.test","password":"changeme"}'
```

---

## Configurar LLM

Editar `vhosts/CentralChat_Backend/.env`:

```bash
OPENROUTER_API_KEY=sk-or-v1-...
```

Reiniciar o orquestrador:

```bash
docker restart central-orchestrator
```

> Perfil MVP recomendado: copiar `.env.mvp` → `.env` (ver secção abaixo).

---

## CLI (Fase 1–2)

```bash
cd vhosts/CentralChat_CLI
go build -o central ./cmd/central

central login --email dev@local.test --password changeme
central workspace .
central              # TUI Surface (defeito)
central tui          # igual
central ask "..." --stream
central daemon       # executor local (outro terminal)
```

### `~/.config/central/tui.toml` (opcional)

```toml
[reasoning]
panel = "collapsed"   # open | collapsed | hidden
width_cols = 24
```

---

## Comandos úteis (Docker)

```bash      # só health check
./startup-testing.sh --no-build    # up sem rebuild
./startup-testing.sh --clean       # apaga BD + sobe fresco (re-seed)
docker logs central-orchestrator --tail 50
docker logs central-centralchat-web --tail 50
```

---

## Perfil MVP (tools + flags)

```bash
cp vhosts/CentralChat_Backend/.env.mvp vhosts/CentralChat_Backend/.env
# Editar OPENROUTER_API_KEY
./startup-testing.sh --restart
```

---

## Posicionamento (vs Hermes / Cursor)

| | Hermes | Cursor | CentralChat |
|---|--------|--------|-------------|
| Foco | Agente pessoal no terminal | IDE | **Equipa/empresa + política no servidor** |
| Interface | CLI local | Editor | **CLI** (+ web dashboard) |
| Skills/agents | Locais / auto-criados | — | **Catálogo partilhado governado** |
| Histórico | `/undo` local | — | **Audit log** + Git corporativo (PR) |
| Chamados | — | Jira | **Work Queue** ligada a sessão IA + diff |

## O que o MVP entrega (roadmap)

| Fase | Entrega |
|------|---------|
| **0** (actual) | Backend sólido, API pronta para CLI |
| **1** | CLI `central` + workspace + diff com aprovação no terminal |
| **2** | Status/diff polido no CLI + web dashboard (secundário) |
| **3** | Agents/skills/regras de equipa partilhados entre máquinas |
| **H1** | Audit log, RBAC, **Work Queue** (`central queue`), políticas |
| **H2** | SSO, PR-only GitHub/GitLab, quotas, SIEM, sync Jira opcional |
| **H3** | Compliance packs, break-glass, relatórios auditoria |

---

## Estrutura activa

```
CentralChat/
├── vhosts/CentralChat_Backend/   # Control plane (orquestrador + Postgres)
├── vhosts/CentralChat_CLI/       # Interface principal (a implementar — Fase 1)
├── vhosts/CentralChat_Frontend/  # Dashboard review/audit (secundário)
├── docker-compose.dev.yml
├── startup-testing.sh
└── docs/MVP_REPOSITIONING.md     # plano completo
```

`CentralChat_Desktop` é **stub** — fora do MVP.

---

## Problemas comuns

| Sintoma | Solução |
|---------|---------|
| Login 401 | BD vazia — correr `./startup-testing.sh` (faz seed) |
| Login 429 | Muitas tentativas — `docker restart central-orchestrator` |
| Chat sem resposta | Verificar `OPENROUTER_API_KEY` no `.env` |
| Porta 5174 ocupada | Parar outro serviço ou alterar porta no compose |

---

## Próximo passo de desenvolvimento

Seguir checklist em [`docs/MVP_REPOSITIONING.md`](docs/MVP_REPOSITIONING.md) — **Fase 1 CLI:**

```bash
cd vhosts/CentralChat_CLI
go mod tidy && go build -o central ./cmd/central

# Terminal 1
./central login --email dev@local.test --password changeme
./central workspace .
./central daemon

# Terminal 2
./central ask "..." --stream
./central pending && ./central diff <id> && ./central approve <id>
```

Ver `vhosts/CentralChat_CLI/README.md`.
