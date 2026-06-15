# Piloto interno — Onda D5

**Status:** kickoff 2026-06-15 — ver [`PILOT_KICKOFF.md`](PILOT_KICKOFF.md)  
**Escopo:** 3–5 devs semanas 1–2 → escala ≥ 10 devs / 30 dias (D5.5).  
**CISO review:** lead interno, semana 3–4 (D5.3).  
**Design partner externo:** fora desta fase.

## Semana 1–2 (D5.1)

- [ ] Repo real (não demo)
- [ ] Keycloak staging + `central login --device`
- [ ] Loop diário: ask → diff → approve → audit
- [ ] Path `payment/` com dual approval (D5.4)
- [x] Stack staging Compose + alertas locais (`scripts/staging_up.sh`)

## Log de fricção (D5.2)

Log activo: [`pilot/FRICITION_LOG.md`](pilot/FRICITION_LOG.md)  
Template: [`templates/PILOT_FRICTION_LOG.md`](templates/PILOT_FRICTION_LOG.md)

Categorias: UX CLI, policy confusion, daemon, IdP, Git PR, performance TUI.

## CISO review (D5.3)

1. Export PDF audit 30d (`/dashboard/audit`)
2. Verificar `policy.violation` + `break_glass.*` no SIEM
3. Checklist data residency (`GET /admin/ops/residency`)

## Escala 10 devs (D5.5)

- Métricas: time-to-first-approval, % policy errors confusos (KR-P2/P3)
- NPS ou entrevistas ≥ 7 (D5.7)

## Pós-piloto (D5.6)

Relatório com: top 5 fricções, bugs P0/P1, backlog H4 priorizado com dados.
