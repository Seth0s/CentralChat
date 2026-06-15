# Piloto interno — kickoff

**Início:** 2026-06-15  
**Fase:** semana 1–2 (3–5 devs)  
**Log activo:** [`pilot/FRICITION_LOG.md`](pilot/FRICITION_LOG.md)

## Participantes (preencher)

| Dev | Repo / área | Papel JWT |
|-----|-------------|-----------|
| | | developer |
| | | approver |

## Checklist semana 1

- [ ] Stack staging: `./scripts/staging_up.sh`
- [ ] `central doctor` verde
- [ ] Primeiro loop: ask → diff → approve → audit
- [ ] Entrada no log de fricção se algo falhar

## Comandos úteis

```bash
# Staging local (Compose — não Helm)
./scripts/staging_up.sh

# Validar alertas
./scripts/ops_smoke.sh

# Helm (render / kind opcional)
./scripts/helm_smoke.sh
```

## Métricas piloto

| Métrica | Meta | Actual |
|---------|------|--------|
| Time-to-first-approval | &lt; 10 min | |
| NPS semana 2 | ≥ 7 | |
