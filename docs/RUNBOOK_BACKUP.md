# Runbook — Backup & restore PG (D1.7 / D1.8)

**RPO:** 1 h (hourly CronJob in Helm staging)  
**RTO:** 4 h (documented restore procedure)

## Backup manual

```bash
cd vhosts/CentralChat_Backend
export MEMORY_DB_URL='postgresql://...'
./scripts/pg_backup.sh
# → backups/central_memory_YYYYMMDD_HHMMSS.sql.gz
```

## Restore

```bash
./scripts/pg_restore.sh backups/central_memory_YYYYMMDD_HHMMSS.sql.gz
# Confirmação interactiva: digite RESTORE
```

## Validação pós-restore

1. `curl -s localhost:8004/health/ready | jq`
2. Login UI + listar sessões
3. `central doctor` com token válido

## Helm CronJob

Ver `deploy/helm/centralchat/README.md` — PVC `*-backup` retém últimos N dias (`backup.retentionDays`).

## Teste mensal (KR-O2)

- [ ] Backup automático ou manual
- [ ] Restore em DB ephemeral
- [ ] Smoke e2e mínimo
