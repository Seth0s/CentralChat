# GitHub App — Onda C2 (staging/prod)

> Recomendação **D-GIT-APP**: GitHub App em vez de PAT.

## Variáveis (orchestrator)

```bash
CENTRAL_GITHUB_REPO=org/repo
CENTRAL_GITHUB_APP_ID=123456
CENTRAL_GITHUB_APP_INSTALLATION_ID=78901234
# PEM numa linha com \n escapados ou multiline no secret manager:
CENTRAL_GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
```

Fallback dev: `CENTRAL_GITHUB_TOKEN` (PAT) — **não usar em produção**.

## Fluxo após approve (`pr_only`)

1. Branch `central/approval-{id8}`
2. Push `new_content` via Contents API (GitHub) ou commit API (GitLab)
3. PR/MR com trailer `Central-Approval: {uuid}` no body
4. Falha → work item + webhook (sem write local silencioso)

## Commit message

```
central(approval:{id8}): {filename}
```

## GitLab (paridade mínima)

```bash
CENTRAL_GITLAB_TOKEN=
CENTRAL_GITLAB_PROJECT_ID=
CENTRAL_GITLAB_BASE_URL=https://gitlab.com
```
