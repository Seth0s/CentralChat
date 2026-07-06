# Debugging Tips

## Common issues and fixes

### Podman restart + entrypoint

After `podman restart`, the entrypoint is not re-executed. Always run seed:
```
podman exec central-backend php artisan db:seed --class=MinimalStartSeeder --force
```

### Circular imports

Resolved with lazy imports inside function bodies:
```python
# ✅ Correct
def my_func():
    from app.tools import get_catalog
    get_catalog()
```

### Syntax check

```bash
python3 -c "import ast,os; [ast.parse(open(os.path.join(r,f)).read()) for r,d,fs in os.walk('app') for f in fs if f.endswith('.py')]"
```

### Database

- Migrations: `python scripts/run_migrations.py --db-url $MEMORY_DB_URL`
- Backup: `./scripts/pg_backup.sh`
- Retention: `python scripts/retention_worker.py --once`

### Rate limiting

Env vars control everything: `CENTRAL_RATE_LIMIT_ENABLED`, `CENTRAL_QUOTA_ENABLED`, `CENTRAL_CONCURRENT_STREAM_LIMIT_ENABLED`.

### Metrics

- `GET /admin/metrics` — aggregated JSON
- `GET /metrics` — Prometheus
- JSON logging: `import app.shared.observability; install_json_logging()`
