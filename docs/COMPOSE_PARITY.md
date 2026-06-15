# Compose ↔ staging parity (D1.9)

| Aspecto | Dev (`docker-compose.dev.yml`) | Staging (+ overrides) |
|---------|-------------------------------|---------------------|
| JWT | `optional` ou `off` local | `required` (`e2e` + `staging`) |
| Write mode | `direct_write` | `pr_only` |
| Quotas / DLP | opcional | activos |
| Audit retention | default | 365d |
| JSON logs | off | `CENTRAL_JSON_LOGGING=1` |
| OIDC | override opcional | Keycloak override |
| Deploy | Compose only | Compose **ou** Helm (K8s) |

## Arranque staging local

```bash
docker compose -f docker-compose.dev.yml \
  -f docker-compose.e2e.override.yml \
  -f docker-compose.staging.override.yml up -d
```

## Multi-tenant limits (D1.10)

| Limite | Env / config | Default |
|--------|--------------|---------|
| Streams simultâneos | `CENTRAL_CONCURRENT_STREAM_LIMIT_*` + `tenant_config.max_concurrent_streams` | por tenant |
| Quota horária | `CENTRAL_QUOTA_PER_TENANT_PER_HOUR` | PG rollup |
| Quota mensal | `CENTRAL_QUOTA_MONTHLY_TOKENS` | alerta 80%/90% |
| Rate limit | `CENTRAL_RATE_LIMIT_PATH_PREFIXES` | `/assistant/text*` |

Noisy neighbour: quotas + stream limiter + rate limit por tenant (JWT `client_id`).
