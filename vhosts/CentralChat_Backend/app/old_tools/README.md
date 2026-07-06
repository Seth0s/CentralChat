# old_tools (ADR-017 phase 8)

Código e metadados das tools que correm no **host Central (VPS)** — system-agent, shell-gateway, desktop helpers — retiradas do catálogo LLM por defeito (`CENTRAL_LEGACY_PLATFORM_TOOLS=0`).

## Ficheiros

| Ficheiro | Função |
|----------|--------|
| `platform_specs.py` | `PLATFORM_TOOL_NAMES`, `strip_platform_specs()`, `merge_legacy_platform_specs()` |
| `platform_dispatch.py` | `dispatch_legacy_platform_tool()` — handlers VPS chamados antes de client/cloud |

## Catálogo activo

`app/tool_registry.py` mantém `_CORE_TOOL_SPECS` completo; `_build_active_tool_specs()` aplica strip/merge conforme env.

- **Tenant (defeito):** cloud + client (`client_read_file`, `client_grep`, `request_shell`, …).
- **Homelab / ops:** `CENTRAL_LEGACY_PLATFORM_TOOLS=1` reexpõe tools platform ao modelo.

## Host context no prompt

Bloco `[FACTUAL_HOST_CONTEXT]` (system-agent) descreve o **servidor Central**, não o PC do utilizador.

- `CENTRAL_INCLUDE_PLATFORM_CONTEXT=1` — injecta host block quando `include_host_context` ou trigger de texto.
- Legacy platform tools (`CENTRAL_LEGACY_PLATFORM_TOOLS=1`) — comportamento anterior (host context ligado).

Ver `app/platform_context.py`.

## Não fazer

- Importar `old_tools` em novos fluxos tenant sem revisão de segurança.
- Assumir que specs nesta pasta estão no JSON enviado ao LLM em produção widget.
