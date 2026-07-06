# CentralChat Admin

Dashboard de **supervisão** do Central (audit, queue, custo, compliance, inferência).

Separado do chat web (`CentralChat_Frontend`) e do CLI (`CentralChat_CLI`).

## Dev local

```bash
cd vhosts/centralchat_admin
cp .env.example .env
bun install
bun run dev
```

Abre [http://127.0.0.1:5175](http://127.0.0.1:5175) — login igual ao orquestrador (`/auth/login`).

## Docker (stack dev)

```bash
cd CentralChat
docker compose -f docker-compose.dev.yml up -d centralchat-admin
```

| Serviço | Porta |
|---------|-------|
| `centralchat-web` (chat) | 5174 |
| `centralchat-admin` | 5175 |
| `orchestrator` | 8004 |

## Rotas

- `/dashboard` — início
- `/dashboard/audit`, `/queue`, `/usage`, `/compliance`, `/inference`, …

## Nota

O dashboard **não** vive em `Project_Sophia/orchestrator-ui` nem no vhost de chat. Este vhost é a única UI admin do CentralChat.
