# CentralChat

Plataforma open-source de orquestração de agentes de IA para equipas de desenvolvimento. O agente atua no contexto real do projeto — lê e edita ficheiros, executa comandos, pesquisa — com aprovação obrigatória antes de qualquer ação com efeitos colaterais.

Diferente de um chat de IA no navegador, o CentralChat oferece sessões partilháveis entre desenvolvedores, contexto herdado via Work Items, file leasing para impedir conflitos e auditoria completa de cada ação.

---

## Arquitetura

| Componente | Tecnologia | Função |
|---|---|---|
| **Backend** | Python / FastAPI + PostgreSQL | Control plane: pipeline de contexto, RBAC, catálogo de ferramentas, vault de secrets |
| **CLI** | Go / Bubble Tea TUI | Interface principal: terminal com tabs, streaming token a token, execução local de ferramentas |
| **Frontend** | TypeScript / React 19 + TanStack Start | Interface web para chat e revisão de sessões |
| **Admin** | TypeScript / React 18 + shadcn/ui | Painel administrativo: utilizadores, agentes, políticas, auditoria |

### Modos de operação

- **SOLO** — offline, tudo local. SQLite para sessões, inferência direta contra OpenRouter ou Ollama. Zero dependência de servidor.
- **TEAM** — conectado ao control plane da organização. Sessões partilhadas, políticas server-side, aprovações multi-utilizador, auditoria.

O mesmo binário Go suporta ambos os modos. A transição é transparente: `central` para SOLO, `central login` para TEAM.

---

## Quickstart (dev)

```bash
# Subir tudo com Docker
docker compose -f docker-compose.dev.yml up -d --build
```

Abrir http://127.0.0.1:5174

| Campo | Valor |
|---|---|
| Email | `dev@local.test` |
| Password | `changeme` |

### CLI (modo SOLO)

```bash
cd vhosts/CentralChat_CLI
export OPENROUTER_API_KEY=sk-or-v1-...
go run ./cmd/central
```

---

## Docker Compose

Duas bases (dev e produção) + dois overrides + um profile no dev:

| Ficheiro/Profile | Tipo | Propósito |
|---|---|---|
| `docker-compose.dev.yml` | **Base** | Desenvolvimento com hot-reload, Postgres em container |
| `docker-compose.vps.yml` | **Base** | Produção minimalista — 2 containers, PostgreSQL nativo no host |
| `docker-compose.oidc.yml` | Override | Adiciona container Keycloak + variáveis OIDC |
| `docker-compose.monitoring.yml` | Override | Adiciona Prometheus + webhook sink de alertas |
| `--profile browser` | Profile | Sidecar browser-use para `web_search` |

### Como compor

```bash
# Desenvolvimento base
docker compose -f docker-compose.dev.yml up -d --build

# Dev com browser-use (web_search)
docker compose -f docker-compose.dev.yml --profile browser up -d --build

# Dev com Keycloak OIDC
docker compose -f docker-compose.dev.yml -f docker-compose.oidc.yml up -d --build

# Dev com monitoring (Prometheus + alertas)
docker compose -f docker-compose.dev.yml -f docker-compose.monitoring.yml up -d --build

# Produção VPS
docker compose -f docker-compose.vps.yml up -d --build
```

---

## Estrutura do repositório

```
CentralChat/
├── vhosts/
│   ├── CentralChat_Backend/   # FastAPI + PostgreSQL (200+ módulos)
│   ├── CentralChat_CLI/       # Go TUI — Bubble Tea + Cobra (80+ ficheiros)
│   ├── CentralChat_Frontend/  # React 19 + TanStack Start
│   ├── centralchat_admin/     # Painel admin React 18 + shadcn/ui
│   └── CentralChat_Desktop/   # Desktop app (placeholder)
├── docker-compose.dev.yml       # Dev base (hot-reload)
├── docker-compose.vps.yml       # Produção VPS
├── docker-compose.oidc.yml      # Override Keycloak OIDC
├── docker-compose.monitoring.yml # Override Prometheus + alertas
├── deploy/
│   ├── helm/centralchat/        # Helm chart para Kubernetes
│   └── prometheus/              # Configs de monitorização
```

---

## CLI — comandos principais

```bash
central                    # TUI interativa
central ask "pergunta"     # One-shot sem TUI
central login              # Conectar ao control plane TEAM
central doctor             # Diagnóstico de conectividade
central workspace <dir>    # Vincular diretório de trabalho
central sync push|pull     # Sincronizar SOLO ↔ TEAM
central approve|reject     # Gerir aprovações pendentes
```

### TUI — atalhos

| Tecla | Ação |
|---|---|
| `Enter` | Enviar mensagem |
| `/` | Slash commands: `/model`, `/agent`, `/tools`, `/help` |
| `Tab` | Alternar modos (Plan / Build / Debug / Multitask / Ask) |
| `Ctrl+H` | Alternar sidebar |
| `Ctrl+B` | Alternar painel de ferramentas |
| `Ctrl+P` | Paleta de comandos |
| `Ctrl+C` | Sair |

---

## Conceitos principais

**Work Item** — unidade de contexto persistente. Um desenvolvedor inicia uma tarefa; o agente herda o histórico, ficheiros e decisões. Outro dev pode retomar exatamente do mesmo ponto.

**Aprovação obrigatória** — antes de escrever no disco ou executar comandos, o agente pede aprovação. Em TEAM, qualquer membro autorizado pode aprovar ou rejeitar.

**File leasing** — o backend impede que dois agentes modifiquem o mesmo ficheiro simultaneamente. Cada Work Item adquire leases; conflitos são detetados antes da execução.

**RBAC** — developer, reviewer, auditor. Cada papel tem permissões e visibilidade diferentes sobre sessões, ferramentas e políticas.

---

## Roadmap resumido

| Fase | Estado | Descrição |
|---|---|---|
| Backend + API | ✅ | FastAPI, PostgreSQL, ContextEngine, RBAC, ferramentas |
| CLI Go | ✅ | TUI, dual runtime SOLO/TEAM, streaming, aprovações |
| Frontend web | ✅ | Chat + revisão de sessões |
| Admin panel | ✅ | Gestão de utilizadores, agentes, políticas, segredos |
| Work Queue | ✅ | Fila de tarefas com handoff entre devs |
| Helm + K8s | ✅ | Deploy Kubernetes com monitorização Prometheus |
| SSO / OIDC | 🚧 | Keycloak integrado, em estabilização |
| Desktop app | ⏳ | Placeholder |

---

## Licença

MIT — ver ficheiro `LICENSE`.
