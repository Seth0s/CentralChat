# CentralChat CLI (Phase 1)

Go client for the CentralChat control plane.

## Build

```bash
cd vhosts/CentralChat_CLI
go mod tidy
go build -o central ./cmd/central
```

## Quick start

```bash
# Terminal 1 — API running (see README-MVP.md)
./central login --email dev@local.test --password changeme
./central workspace .
./central daemon

# Terminal 2
./central ask "lista ficheiros em src"
./central pending
./central diff <approval_id>
./central approve <approval_id>
```

## Commands

| Command | Description |
|---------|-------------|
| `central login` | Save JWT to `~/.config/central/credentials.json` |
| `central workspace [path]` | Bind repo + `POST /ui/workspace` |
| `central daemon` | Poll `GET /connector/jobs` — execute file ops locally |
| `central ask "..." --stream` | SSE chat with tools |
| `central pending` | Pending approvals |
| `central diff <id>` | Unified diff |
| `central approve/reject <id>` | HITL |
| `central sessions` | List sessions |

Send header `X-Central-Workspace` on every ask when workspace is bound.
