# Policy engine — precedência e fontes (Onda B)

## Precedência (B2.2)

```
deny (policy)  >  break-glass grant  >  allow (default)
```

1. **Deny** — regra de path/tool/model bloqueia a operação.
2. **Break-glass** — grant activo do utilizador cobre o path; gera `break_glass.used` + alerta.
3. **Allow** — sem regra aplicável ou regra permissiva.

## Fontes de política (D-POL-1)

| Prioridade | Fonte |
|------------|--------|
| 1 | Bundle `published` em PG (`tenant_active_policy` → `policy_bundles`) |
| 2 | `tenant_config.features_json.policies` (legado) |
| 3 | `CENTRAL_ROOT/config/team_policies.json` (bootstrap dev) |
| 4 | `DEFAULT_POLICIES` em código |

## Versionamento (B2.6)

- Nova versão = `INSERT policy_bundles` + regras + swap em `tenant_active_policy`.
- Audit: `policy.bundle_published` com `version` e `bundle_id`.

## Avaliação (B2.1)

Todas as tool calls passam por `classify_tool_call` → `evaluate_tool_policy`.
Falha do motor = **bloqueio** (fail-closed), não bypass.

## Violações (B2.7)

`record_policy_violation()` grava `policy.violation` com:
`tenant_id`, `tool`, `path`, `error_code`, `message_pt`, `bundle_id`, `bundle_version`.
