# CentralChat Helm chart

Helm chart for staging/production (D-DEPLOY-1). Docker Compose remains the canonical dev path.

## Prerequisites

- Kubernetes 1.28+ (k3s/kind OK for CI)
- `helm` 3.14+
- Secret `centralchat-secrets` with at least `MEMORY_DB_URL`, `CENTRAL_JWT_SECRET`, OIDC/GitHub keys as needed

## Install

```bash
kubectl create namespace centralchat-staging
kubectl -n centralchat-staging create secret generic centralchat-secrets \
  --from-literal=MEMORY_DB_URL='postgresql://user:pass@host:5432/central'

helm upgrade --install centralchat ./deploy/helm/centralchat \
  -n centralchat-staging \
  -f deploy/helm/centralchat/values.yaml
```

## Upgrade (D1.2)

```bash
helm upgrade centralchat ./deploy/helm/centralchat -n centralchat-staging \
  --set image.tag=v1.2.0 \
  --wait --timeout 5m
kubectl -n centralchat-staging rollout status deploy/centralchat-centralchat
```

Target: API downtime &lt; 5 min (rolling update + readiness on `/health/ready`).

## Rollback (D1.3)

```bash
helm history centralchat -n centralchat-staging
helm rollback centralchat <REVISION> -n centralchat-staging
```

## Backup CronJob

When `backup.enabled=true`, hourly `pg_dump` runs into PVC `*-backup`. Restore with `scripts/pg_restore.sh` — see `docs/RUNBOOK_BACKUP.md`.

## Observability

- Scrape `/metrics` (Prometheus annotations on pod)
- Import `deploy/grafana/centralchat-dashboard.json`
- Apply `deploy/prometheus/alerts.yml` in PrometheusRule or Alertmanager

## Secrets rotation (D1.4)

| Secret | Rotation | Notes |
|--------|----------|-------|
| `CENTRAL_JWT_SECRET` | Rolling restart after K8s secret update | Invalidates refresh tokens |
| `MEMORY_DB_URL` | DBA + restore if needed | Update secret, restart deployment |
| Webhooks (Slack/SIEM) | Update secret/env, no schema migration | |

## Air-gap (D1.5)

Set in values:

```yaml
env:
  CENTRAL_TELEMETRY_DISABLED: "1"
  CENTRAL_AIR_GAP_MODE: "1"
```

Verify: no outbound SIEM/webhook URLs configured; `/metrics` still local-only scrape.
