# CentralChat Admin — Plano de Profissionalização

> **UPDATED:** 2026-06-16  
> **Status:** Plano canónico para transformar `centralchat_admin` em painel administrativo enterprise  
> **Audiência:** produto, engenharia frontend/backend, segurança, operações  
> **Escopo:** `vhosts/centralchat_admin`, orquestrador FastAPI, RBAC, configurações sensíveis, work queue, sessões, usuários e governança  
> **Relacionado:** `docs/RBAC_MATRIX.md`, `docs/HARDENING_PLAN.md`, `docs/POLICY_ENGINE.md`, `docs/CLI_UX_SPEC.md`

---

## CHANGELOG

| Data | Resumo |
|------|--------|
| 2026-06-16 | Documento inicial: diagnóstico crítico, arquitetura alvo, páginas necessárias, APIs, RBAC, segurança, escalabilidade, UX e roadmap de implementação |
| 2026-06-16 | Revisão de produto: simplificar cargos base, substituir approval universal por solicitações contextuais e introduzir hierarquia Empresa → Times/Grupos/Projetos → Leads → Developers/Auditoria |
| 2026-06-16 | Decisão de identidade: usuários nascem sem acesso operacional; permissões são memberships com `scope_type` (`organization`, `group`, `project`) |
| 2026-06-16 | Implementação P1 inicial: `/admin/users`, criação local sem membership automática e seleção de usuários na tela de Organização |
| 2026-06-16 | Implementação P1 usuários: `/dashboard/users`, edição de role/status/nome e reset de senha local |
| 2026-06-16 | Hardening P1 usuários: proteção do último admin ativo, auditoria de mutações e revogação de sessões em reset/status/role |
| 2026-06-16 | Implementação P1 UI permissions: matriz frontend de paths, sidebar filtrada por role e gate visual no layout |
| 2026-06-16 | Implementação P1 memberships UI: Organização diferencia admin, lead e leitura; lead gerencia memberships apenas em projects sob seu escopo |
| 2026-06-16 | Implementação P1 project members UI: listagem, troca de role e remoção de memberships diretas por project |
| 2026-06-16 | Hardening P1 memberships: auditoria de add/update/remove e proteção contra remover/demover o último lead direto do project |
| 2026-06-16 | Implementação P1 user memberships UI: `/admin/users/{id}/memberships` e painel usuário → acessos em `/dashboard/users` |
| 2026-06-16 | Implementação P1 org editing UI: edição inline de groups e projects na árvore organizacional, respeitando admin/lead de escopo |
| 2026-06-16 | Implementação P1 org health: `/admin/org/health` e alertas de projects sem lead direto / groups sem projects |
| 2026-06-16 | Correção P0 auth guard: `/oidc-callback` liberado, refresh sozinho não valida sessão e role ausente não vira `developer` |
| 2026-06-16 | Correção P0 UX guard: `Toaster` global, 403 dedicado e revisão de mensagens PT-BR nas telas de users/org/queue |
| 2026-06-16 | Correção P0 origem admin: `VITE_ADMIN_ORIGIN` usado em fallback OIDC e logout, sem depender de `VITE_APP_ORIGIN` |
| 2026-06-16 | Roadmap P0 marcado como concluído, incluindo critérios de done |
| 2026-06-16 | Roadmap P1 marcado como concluído: users/org/memberships, auditoria, último admin e bloqueio de autoalteração de role |
| 2026-06-16 | Início P2 configurações sensíveis: `/admin/secrets`, teste de provider, auditoria de rotação e UI `/dashboard/settings/*` |
| 2026-06-16 | Roadmap P2 marcado como concluído (MVP): metadados de segredos, rotação/teste de provider e páginas de settings |
| 2026-06-16 | Roadmap P3 marcado como concluído (MVP): work item detail/timeline/comentários, session ACL, solicitações contextuais e UI `/dashboard/queue/$id`, `/dashboard/sessions/$id`, `/dashboard/requests` |
| 2026-06-16 | Roadmap P4 marcado como concluído (MVP): agentes/skills draft-review-publish, regras com rejeição motivada, policy bundles draft/publish/rollback e UI `/dashboard/agents`, `/skills`, `/rules`, `/policies` |
| 2026-06-16 | Roadmap P5 marcado como concluído (MVP): break-glass grant/revoke UI, export audit assíncrono, `/admin/deploy/status`, monitor SIEM e `/dashboard/settings/ops` |

---

## 1. Resumo Executivo

O `centralchat_admin` atual é um **dashboard operacional MVP**: ele permite observar solicitações/approvals legados, sessões, regras, work queue, audit, uso, compliance e inferência. Isso é útil para supervisão, mas ainda não é uma **central administrativa profissional**.

A proposta do produto exige que o admin seja o lugar onde uma organização consegue operar o Central com segurança:

- Gerir usuários, cargos simples e capacidades contextuais.
- Modelar hierarquia organizacional: empresa, grupos, projetos, leads, developers e auditoria.
- Controlar agentes, regras, policies e work items por equipe.
- Administrar configurações gerais e sensíveis.
- Governar provedores de inferência, API keys, LLM local e model-router.
- Auditar tudo com trilha defensável.
- Expor cada página conforme o cargo do usuário.
- Evitar vazamento cross-tenant.
- Ter UX clara para operadores não técnicos.

### Tese

O admin deve deixar de ser “uma coleção de telas de diagnóstico” e virar um **console de governança multi-tenant**.

### Estado atual

| Dimensão | Estado atual | Avaliação |
|----------|--------------|-----------|
| Auth | Cookies httpOnly + BFF + JWT | Boa base |
| RBAC backend | Existe, mas mistura cargo com capacidade operacional (`reviewer`/`approver`) | Parcial |
| RBAC UI | Quase inexistente; sidebar expõe páginas sensíveis para todos | Fraco |
| Usuários/cargos | Sem página, sem API REST completa | Crítico |
| Config admin | Fragmentada em páginas operacionais | Parcial |
| Config sensível | Inference cobre parte; sem vault/rotação/status claro | Crítico |
| Sessões | Listagem simples | Insuficiente |
| Work queue | Kanban básico | Parcial |
| Solicitações/approvals legados | Aprovar/rejeitar básico; conceito precisa virar comunicação contextual, não bloqueio universal | Parcial |
| Audit | Boa fundação | Precisa de UX e filtros |
| Multi-tenant | Backend caminha para tenant; UI ainda usa `default` em pontos | Parcial |
| Escalabilidade UX | Sem paginação/virtualização consistente | Fraco |

---

## 2. Princípios do Admin Profissional

### 2.1 Segurança primeiro

Toda tela sensível deve obedecer ao princípio:

> Se o usuário não pode executar a ação, ele também não deve ser induzido a acreditar que pode.

Isso significa:

- Sidebar e rotas filtradas por role.
- Botões sensíveis escondidos ou desabilitados com motivo claro.
- Backend continua sendo a fonte de verdade.
- Nenhuma tela sensível depende apenas de regra no frontend.
- Toda mutação sensível gera audit event.
- Configurações secretas nunca retornam valor puro.

### 2.2 Backend como fonte de verdade

A UI melhora experiência, mas não substitui:

- RBAC no backend.
- RLS no banco.
- Validações de payload.
- Audit log.
- Policy engine.
- Proteção de segredo.

### 2.3 Multi-tenant nativo

Todas as telas administrativas devem operar com `tenant_id` explícito ou derivado do JWT.

Regras:

- Usuário comum não escolhe tenant manualmente.
- Admin global pode trocar tenant com selector explícito.
- Auditor vê apenas tenants permitidos.
- Todas as queries do backend usam tenant resolvido no servidor.
- Nunca confiar em `tenantId` vindo do frontend sem autorização.

### 2.4 Cargos simples, capacidades contextuais

O produto não deve transformar lead/admin/auditor em “mãe do developer”. O developer deve ser responsável pelo próprio repo local e pelo próprio workspace. O Central deve ajudar com guardrails, auditoria e comunicação, não bloquear o fluxo diário de engenharia.

Cargos base recomendados:

- `developer`: trabalha nos projetos, usa agentes, sessões e work queue; tem autonomia no repo local vinculado.
- `lead`: responsável por um projeto/grupo/time; coordena prioridades, sessões compartilhadas, decisões técnicas e governança do projeto.
- `admin`: administra empresa, usuários, grupos, projects, secrets, providers, políticas globais e configurações sensíveis.
- `auditor`: papel transversal read-only para evidências, compliance, trilhas de auditoria e relatórios.

Não devem ser cargos base:

- `approver`: deve virar uma **capacidade contextual** ou estado de uma solicitação, não identidade principal do usuário.
- `reviewer`: deve virar função em um fluxo de review ou permissão de projeto, não cargo global obrigatório.
- `viewer`: deve virar nível de acesso/read-only ou permission set, não cargo central do produto.

Capacidades contextuais úteis:

- `can_request_decision`
- `can_review_project_work`
- `can_publish_agent`
- `can_publish_policy`
- `can_manage_project_members`
- `can_manage_secrets`
- `can_view_audit`
- `can_export_audit`
- `can_break_glass`

### 2.5 Hierarquia organizacional alvo

Hierarquia conceitual padrão:

```text
Organization / Company
  └── Groups
      └── Projects
          ├── Lead(s)
          ├── Developers
          └── Auditors (acesso transversal/read-only conforme escopo)
```

Definições:

- **Organization / Company:** boundary maior de billing, compliance, tenant e configuração global.
- **Group:** agrupamento lógico de projetos, squads ou domínios.
- **Project:** unidade operacional ligada a repos, sessões, agentes, work items e policies.
- **Lead:** responsável por governança do projeto/grupo, não aprovador de cada ação local do dev.
- **Developer:** dono operacional do próprio workspace/repo local.
- **Auditor:** observa evidências e conformidade; não participa da cadeia de comando diária.

`Department` ou `Business Unit` pode existir no futuro acima de `Group`, mas não deve entrar no MVP se não houver necessidade real. O modelo inicial deve ser simples: empresa, grupos e projetos.

### 2.5.1 Memberships e `scope_type`

Usuário não deve nascer com role operacional nem com projeto/grupo. Ao criar um usuário, ele existe na organização, mas sem acesso operacional até receber uma membership.

`scope_type` responde à pergunta:

> Essa permissão vale onde?

Modelo conceitual:

```text
membership
  user_id
  scope_type = organization | group | project
  scope_id
  role = admin | lead | developer | auditor
```

Exemplos práticos:

```text
Lucas  | organization | acme-company      | admin
Maria  | group        | frontend-platform | lead
Maria  | project      | admin-ui          | developer
Joao   | project      | backend-api       | developer
Ana    | organization | acme-company      | auditor
```

Como isso funciona:

- `organization`: a permissão vale para a empresa inteira.
- `group`: a permissão vale para o grupo e, conforme política, pode herdar para os projetos do grupo.
- `project`: a permissão vale apenas para aquele projeto.

Regra de herança inicial:

```text
organization role -> vale para tudo abaixo
group role        -> vale para projects daquele group
project role      -> vale só para aquele project
```

Exemplos:

- Lucas é `admin` na organization `acme-company`; pode gerir usuários, groups, projects e configurações sensíveis da empresa.
- Maria é `lead` no group `frontend-platform`; pode coordenar projects desse group, mas não projects de outro group.
- João é `developer` no project `backend-api`; pode trabalhar nesse project, abrir sessões e criar work items nele, mas não recebe acesso a outros projects.
- Ana é `auditor` na organization; lê audit/compliance conforme política, sem participar do fluxo diário.

Regra de criação de usuário:

1. Admin cria usuário.
2. Usuário fica sem role operacional efetiva.
3. Admin/lead adiciona o usuário a um `group` ou `project`.
4. A membership define role e capacidades naquele escopo.

Essa abordagem evita `user.role = developer` como verdade global. O mesmo usuário pode ser `lead` em um group, `developer` em um project específico e não ter acesso a outros projetos.

### 2.6 Solicitações, não approval universal

O conceito antigo de “approval” deve ser reposicionado.

O Central deve separar:

- **Confirmação local:** o próprio developer confirma ação destrutiva no repo/workspace dele.
- **Solicitação ao lead/admin:** pedido de decisão, revisão, exceção ou alinhamento quando a ação cruza uma fronteira compartilhada.
- **Bloqueio por policy:** negação automática quando uma regra corporativa ou de segurança proíbe a ação.

Repo local do developer:

- Editar arquivo dentro do workspace vinculado: sem approval externo.
- Aplicar patch local: sem approval externo; pode exigir confirmação do próprio dev se destrutivo.
- Rodar teste/build/comando seguro: sem approval externo.
- Comando destrutivo local: confirmação forte do próprio dev e audit, não lead por padrão.
- Escrever fora do workspace permitido: bloqueio/policy, não “pedir para lead ser mãe”.

Approval/solicitação externa só faz sentido quando envolve:

- Repo central/compartilhado gerenciado pelo Central.
- Branch protegida, merge, release ou deploy.
- Staging/prod/infra compartilhada.
- Secrets, providers, API keys, políticas globais.
- Publicação de agente/regra para equipe/tenant.
- Acesso a sessão privada ou dado sensível de outro usuário.
- Exceção de policy ou break-glass.

### 2.7 Operação auditável

Toda ação relevante deve responder:

- Quem fez?
- Em qual tenant?
- Em qual recurso?
- Quando?
- Qual era o estado anterior?
- Qual é o estado novo?
- Qual motivo foi informado?
- Qual policy ou role permitiu?
- Houve break-glass?

---

## 3. Diagnóstico Crítico do Admin Atual

### 3.1 Auth e sessão

Problemas identificados:

- `/oidc-callback` pode ser bloqueado pelo guard global antes de trocar o código OIDC.
- Toasts são usados, mas o `Toaster` global pode não estar montado.
- Logout/OIDC pode apontar para origem errada se `VITE_APP_ORIGIN` estiver herdando a porta do frontend principal.
- Em alguns fluxos, a UI assume `role: developer` como fallback, o que pode mostrar ações indevidas até o backend negar.

Estado implementado em 2026-06-16:

- `/oidc-callback` está liberado no guard global.
- `Toaster` global está montado no root da aplicação.
- `VITE_ADMIN_ORIGIN` é usado para fallback de callback OIDC e `post_logout_redirect_uri`.
- Refresh token sozinho não valida sessão.
- Role ausente/desconhecida não vira `developer`.

Correções necessárias:

- Liberar `/oidc-callback` no guard.
- Montar `Toaster` no root.
- Separar origem do admin: `VITE_ADMIN_ORIGIN`.
- Não assumir role mutável quando a sessão está em refresh.
- Exibir tela “validando sessão” em vez de liberar UI com fallback permissivo.

### 3.2 RBAC visual

Problemas identificados:

- Sidebar igual para todos.
- Páginas sensíveis aparecem para cargos sem permissão.
- `403` aparece como erro genérico.
- Poucas páginas têm lógica client-side de read-only.

Estado implementado em 2026-06-16:

- Sidebar filtrada por `role` de sessão.
- Acesso direto a rota sensível renderiza 403 dedicado em PT-BR no layout do dashboard.
- Páginas de Organização/Usuários aplicam leitura/mutação conforme role e escopo.

Correções necessárias:

- Criar matriz central no frontend: rota → roles → nível de acesso.
- Criar `useCurrentUser()` com `role`, `tenant_id`, `email`, `display_name`.
- Criar componente `RequireRole`.
- Criar página `403` em PT-BR com orientação.
- Marcar páginas read-only para `auditor` e para usuários sem capability de mutação naquele escopo.

### 3.3 Ausência de identidade administrativa

Problemas:

- Sem página de usuários.
- Sem CRUD de usuários.
- Sem ativar/desativar usuário.
- Sem troca de cargo.
- Sem reset de senha.
- Sem convite.
- Sem visão de origem do usuário: local, OIDC, API key.

Impacto:

- O admin não consegue operar o produto sem scripts.
- Não há autonomia para equipe de operação.
- A hierarquia empresa/grupo/projeto não existe como modelo operacional.
- `lead` ainda não é relacionado a projetos/grupos.
- Capacidades como review/publicação/aprovação ainda estão misturadas com cargos.

### 3.4 Configurações sensíveis incompletas

Problemas:

- API keys de providers são parcialmente configuráveis.
- Não há rotação formal.
- Não há histórico de alteração.
- Não há health check por provider.
- Não há visualização segura de segredo: prefixo, último uso, criado por, expira em.
- Não há gestão clara de LLM local/model-router.

Impacto:

- Operação manual via `.env`.
- Risco de segredo exposto.
- Difícil auditar quem alterou provider/model.

### 3.5 Work queue operacional, mas não colaborativa

Problemas:

- CRUD visual incompleto.
- Pouca gestão de assignee.
- Sem histórico de transições visível.
- Sem SLA, prioridade avançada ou filtros salvos.
- Sem relação rica com sessão, solicitação contextual e audit.

Correções:

- Página de detalhe do work item.
- Timeline de eventos.
- Campos editáveis conforme role.
- Criar/editar/cancelar item.
- Assign/reassign.
- Comentários e motivo de mudança.

### 3.6 Sessões sem governança

Problemas:

- Listagem simples.
- Sem detalhe completo.
- Sem compartilhamento por usuário/cargo.
- Sem visibilidade `private/group/tenant`.
- Sem trilha de acesso.
- Sem ação de arquivar/reter/exportar.

Correções:

- `session_acl`.
- Página de detalhe.
- Timeline/mensagens.
- Compartilhamento com role/user.
- Retenção e export auditável.

---

## 4. Arquitetura Alvo

### 4.1 Camadas

| Camada | Responsabilidade |
|--------|------------------|
| Admin UI | UX, navegação, formulários, feedback, guards visuais |
| BFF TanStack Start | Server functions, cookies httpOnly, refresh, chamadas autenticadas |
| Orquestrador FastAPI | RBAC, validação, tenant, audit, policies, secrets |
| Postgres | Dados relacionais, RLS, constraints, histórico |
| Vault/Secrets runtime | Armazenamento seguro de API keys |
| SIEM/Audit | Export, compliance, trilha externa |

### 4.2 Fluxo de autorização

1. Usuário acessa rota admin.
2. Root loader valida sessão.
3. UI recebe `role`, `tenant_id`, `sub`, `email`.
4. Sidebar filtra páginas.
5. Página aplica modo `read`, `write` ou `hidden`.
6. Mutação chama server function.
7. BFF injeta Bearer token.
8. Backend valida JWT, tenant e role.
9. Backend executa mutação em transação.
10. Backend grava audit event.
11. UI mostra toast e atualiza cache.

### 4.3 Regra de ouro

Frontend pode esconder, mas backend deve negar.

---

## 5. Mapa de Páginas Necessárias

### 5.1 Grupo: Identidade e Acesso

#### `/dashboard/users`

Objetivo: gerir usuários do tenant.

Features:

- Listar usuários.
- Buscar por email/nome.
- Filtrar por role, status, origem.
- Criar usuário local.
- Convidar usuário.
- Editar nome/email quando permitido.
- Ativar/desativar.
- Resetar senha.
- Forçar logout/revogar refresh tokens.
- Ver último login.
- Ver último uso de API key.
- Ver origem: `local`, `oidc`, `api_key`.

Campos mínimos:

- `id`
- `tenant_id`
- `email`
- `display_name`
- `role`
- `active`
- `auth_source`
- `created_at`
- `last_login_at`
- `last_seen_at`

Segurança:

- Apenas `admin` e talvez `lead` podem listar todos.
- Apenas `admin` altera cargo global.
- `lead` pode convidar/adicionar `developer` a projetos sob sua responsabilidade, se política permitir.
- Usuário não pode elevar o próprio cargo.
- Toda alteração gera audit.

#### `/dashboard/roles`

Objetivo: documentar cargos base e capacidades contextuais.

Features:

- Listar cargos base disponíveis: `admin`, `lead`, `developer`, `auditor`.
- Mostrar capacidades contextuais por projeto/grupo.
- Mostrar permissões por módulo.
- Mostrar se role vem de OIDC group mapping.
- Configurar mapeamento OIDC group → role.
- Visualizar usuários por cargo.

Decisão crítica:

- Para MVP, cargos base devem ser fixos.
- Para enterprise, permissões devem evoluir para capabilities por escopo: organization, group, project.

Modelo recomendado:

- `roles` fixos no código para MVP: `admin`, `lead`, `developer`, `auditor`.
- `memberships` com `scope_type` carregam capacidades contextuais.
- `tenant_role_overrides` deve ser evitado no início; preferir capabilities explícitas por escopo.
- Evitar criar RBAC totalmente dinâmico cedo demais.

#### `/dashboard/org`

Objetivo: gerir a hierarquia organizacional.

Features:

- Ver árvore Organization → Groups → Projects.
- Criar/editar groups.
- Criar/editar projects.
- Vincular repositórios a projects.
- Definir lead(s) por project/group.
- Adicionar/remover developers por project.
- Definir auditores com escopo: organization, group ou project.
- Ver quantidade de sessões, work items e agentes por project.

Regras:

- `admin` administra a hierarquia completa.
- `lead` administra projects/groups sob sua responsabilidade.
- `developer` vê os projects dos quais participa.
- `auditor` vê a árvore conforme escopo auditável.

Backend necessário:

- Tabelas para `groups`, `projects`, `memberships` e, se preferirmos normalizar depois, `project_memberships`/`group_memberships`.
- Relações de owner/lead por project.
- Associação de sessions, work items, agents e policies a `project_id` quando aplicável.

#### `/dashboard/api-keys`

Objetivo: gerir chaves de API para CLI/automação.

Features:

- Criar API key.
- Revogar API key.
- Listar prefixo, label, role, criado por, último uso.
- Definir expiração.
- Definir escopo: `cli`, `ci`, `integration`, `read_only`.
- Copiar segredo apenas no momento da criação.

Segurança:

- Nunca retornar hash ou segredo.
- Mostrar apenas prefixo.
- Revogação auditada.
- Rate limit por key.
- IP allowlist opcional para CI.

### 5.2 Grupo: Configurações

Configurações não devem ser uma página única gigante. O admin precisa de um **Settings Hub** com seções separadas por risco, frequência de uso e perfil autorizado.

Estrutura recomendada:

```text
/dashboard/settings
  /general
  /access
  /security
  /secrets
  /integrations
  /operations
```

`Inference` e `Policies` podem aparecer dentro de Configurações para descoberta, mas devem poder ser promovidas para tópicos próprios na sidebar quando virarem áreas de trabalho frequentes.

#### `/dashboard/settings`

Objetivo: hub de configurações.

Features:

- Cards por seção.
- Indicação de risco: baixo, médio, alto.
- Indicação de origem: editável na UI, configurado via deploy, herdado do tenant.
- Links para páginas específicas.
- Alertas de configuração incompleta: provider sem key, SIEM sem webhook, backup sem restore testado.
- Últimas alterações sensíveis.

Regras:

- Nunca misturar segredo editável com configuração comum.
- Mostrar modo read-only quando a config vem de `.env`, Helm ou compose.
- Exibir claramente o escopo: organization, group ou project.

#### `/dashboard/settings/general`

Objetivo: configurações gerais do tenant.

Features:

- Nome do tenant.
- Domínio/slug.
- Idioma padrão.
- Timezone.
- Limites de retenção.
- Flags de produto não sensíveis.
- Preferências de UI/admin.
- Nome público da organização.
- Branding leve: logo/wordmark, cor de destaque, se necessário.
- Configuração padrão de grupos/projetos.

Backend:

- Usar `tenant_config`.
- Validar por role.
- Audit em toda alteração.

#### `/dashboard/settings/access`

Objetivo: atalhos de acesso e governança organizacional.

Essa seção não substitui `/dashboard/users` nem `/dashboard/org`; ela serve como entrada rápida para administração de acesso.

Features:

- Usuários sem membership operacional.
- Convites pendentes.
- Groups sem lead.
- Projects sem lead.
- Auditores por escopo.
- Links para Users, Org Tree e Memberships.
- Resumo de cargos por escopo.

Segurança:

- `admin` vê tudo.
- `lead` vê apenas groups/projects sob sua responsabilidade.
- `auditor` lê conforme escopo.

#### `/dashboard/settings/security`

Objetivo: políticas de segurança.

Features:

- JWT mode/status.
- OIDC habilitado.
- Tenant claim.
- Session TTL.
- Refresh TTL.
- MFA status, se suportado pelo IdP.
- IP allowlist admin.
- Break-glass policy.
- Export policy.

Regras:

- Muitas opções podem ser read-only se vierem de env/Helm.
- UI deve explicar “configurado via deploy”.

#### `/dashboard/settings/secrets`

Objetivo: configurações sensíveis.

Features:

- Lista de segredos por categoria.
- Provider API keys.
- Webhooks SIEM.
- Tokens GitHub/Jira/Linear.
- OpenRouter keys.
- LLM local endpoint credentials.
- Rotação.
- Revogação.
- Testar conexão.
- Ver último uso.
- Ver último autor de rotação.
- Ver data de expiração quando houver.
- Ver consumers impactados antes de rotacionar.

UX segura:

- Campo secreto write-only.
- Mostrar `prefix`, `created_at`, `updated_by`, `last_used_at`.
- Nunca mostrar valor completo.
- Confirmação para sobrescrever.
- Explicar impacto antes de salvar.

#### `/dashboard/settings/inference`

Objetivo: governança de modelos/provedores.

Features:

- Providers globais e por tenant.
- Status por provider.
- API key status.
- Allowlist de modelos.
- Blocklist.
- Modelo padrão por perfil.
- Mapeamento `eco/balanced/premium`.
- LLM local/model-router endpoint.
- Test prompt de diagnóstico.
- Custos/limites por modelo.
- Allowlist por organization/group/project.
- Fallbacks por provider/model.
- Status do model-router.
- Status de LLM local.

Segurança:

- Só `admin` altera segredo/provider.
- `lead` pode propor allowlist, se houver workflow.
- `auditor` lê configuração sem segredo.

#### `/dashboard/settings/integrations`

Objetivo: conectar e monitorar ferramentas externas.

Features:

- GitHub/GitLab.
- Jira/Linear.
- Slack/Teams.
- SIEM.
- Sentry/Datadog, se aplicável.
- Webhooks customizados.
- Status de conexão.
- Último sync.
- Último erro.
- Testar integração.
- Rotacionar credencial via `settings/secrets`.

Segurança:

- Configuração de segredo fica em `settings/secrets`.
- Esta página mostra estado, metadados e ações de teste/sync.
- `admin` configura.
- `auditor` lê status e histórico sem segredo.

#### `/dashboard/settings/ops`

Objetivo: operação/deploy.

Features:

- Health geral.
- Versões dos serviços.
- Feature flags efetivas.
- Residency/deployment mode.
- Backup status.
- Último restore testado.
- Migrations aplicadas.
- Workers ativos.
- SIEM outbox status.

### 5.3 Grupo: Governança de Agentes

#### `/dashboard/agents`

Objetivo: CRUD e governança dos agentes de equipe.

Features:

- Listar agentes.
- Criar agente.
- Editar prompt/modelo/ícone.
- Draft/review/publish.
- Versionamento.
- Histórico de alterações.
- Owner.
- Visibilidade por role/equipe.
- Desativar agente.
- Testar agente.

Segurança:

- `developer` pode propor draft.
- `lead` revisa e publica dentro do project/group sob sua responsabilidade.
- `admin` pode intervir.
- Toda publicação gera audit.

#### `/dashboard/skills`

Objetivo: gerir skills compartilhadas.

Features:

- CRUD.
- Draft/review/publish.
- Dependências.
- Exemplos de uso.
- Avaliação de risco.

#### `/dashboard/rules`

Objetivo: governar regras de equipe.

Melhorias necessárias:

- Rejeitar com motivo.
- Editar regra antes de publicar.
- Mostrar origem: manual, sugestão, policy, playbook.
- Mostrar impacto estimado.
- Versionar.
- Buscar por texto/tags.

### 5.4 Grupo: Trabalho e Sessões

#### `/dashboard/queue`

Objetivo: work queue colaborativa.

Features necessárias:

- Criar work item.
- Editar título/descrição.
- Alterar prioridade.
- Atribuir responsável.
- Mover status.
- Status: `open`, `in_progress`, `review`, `done`, `cancelled`.
- Link com sessão.
- Link com solicitação contextual.
- Link externo.
- Labels.
- Filtros por assignee/status/prioridade.
- Timeline.
- Comentários.
- SLA.

Regras por cargo:

- `developer`: cria e trabalha itens dos projects dos quais participa.
- `lead`: reatribui, muda prioridade, fecha/cancela.
- `auditor`: leitura conforme escopo.
- `admin`: override.

#### `/dashboard/sessions`

Objetivo: supervisão e compartilhamento de sessões.

Features:

- Listar sessões.
- Ver detalhe.
- Ver mensagens.
- Ver agentes/modelos usados.
- Ver work item relacionado.
- Ver solicitações relacionadas.
- Compartilhar com usuário/cargo.
- Arquivar.
- Exportar.
- Aplicar retenção.

Segurança:

- Sessão pode ser `private`, `group`, `tenant`, `restricted`.
- Auditor pode ler sessões auditáveis, se política permitir.
- Conteúdo sensível pode exigir permissão extra.

#### `/dashboard/requests`

Objetivo: comunicação e decisão contextual entre developers, leads, admins e auditoria.

Features:

- Fila de solicitações pendentes.
- Solicitação de decisão ao lead do project.
- Solicitação de exceção/admin.
- Solicitação de revisão de auditoria.
- Diff inline/modal.
- Responder com decisão, comentário ou pedido de ajuste.
- Rejeitar/encerrar com motivo obrigatório.
- Marcar como resolvida ou converter em work item.
- Mostrar risco P0/P1/P2/P3 quando houver ação sensível.
- Mostrar policy relacionada quando a solicitação nasceu de bloqueio/guardrail.
- Mostrar solicitante.
- Mostrar project, repo e sessão relacionados.
- Mostrar daemon/connector alvo quando houver execução.
- Mostrar work item gerado.

Segurança:

- `developer` pode abrir solicitação para seu lead/project.
- `lead` responde solicitações dos projects sob sua responsabilidade.
- `admin` responde solicitações administrativas/sensíveis.
- `auditor` abre ou comenta solicitações de compliance, mas não comanda o fluxo diário.
- Ações locais do repo do developer não devem depender de aprovação externa.
- Ações P3/infra/secrets podem exigir confirmação, break-glass ou policy específica.

### 5.5 Grupo: Auditoria e Compliance

#### `/dashboard/audit`

Melhorias:

- Paginação real.
- Filtros avançados.
- Busca por usuário/email.
- Busca por work item/session/solicitação.
- Export CSV/JSON com confirmação.
- Redação de payload sensível.
- Drill-down de evento.

#### `/dashboard/compliance`

Features:

- Packs disponíveis.
- Preview de impacto.
- Aplicar pack com confirmação.
- Histórico de aplicação.
- Break-glass grant.
- Break-glass revoke.
- Grants ativos.
- Relatório de conformidade.

Segurança:

- `auditor` lê.
- `admin` aplica.
- Break-glass exige motivo, expiração e audit.

#### `/dashboard/policies`

Objetivo: governar policy bundles.

Features:

- Ver policy ativa.
- Criar draft.
- Editar regras.
- Validar golden cases.
- Publicar versão.
- Rollback.
- Ver violações.
- Ver precedência: deny > break-glass > allow.

---

## 6. APIs Necessárias no Backend

### 6.1 Usuários

Endpoints propostos:

| Método | Rota | Permissão | Descrição |
|--------|------|-----------|-----------|
| GET | `/admin/users` | admin, lead, auditor | Lista usuários do tenant |
| POST | `/admin/users` | admin | Cria usuário local ou convite |
| GET | `/admin/users/{id}` | admin, lead, auditor | Detalhe |
| GET | `/admin/users/{id}/memberships` | admin, lead, auditor | Lista memberships visíveis por usuário, filtradas por escopo |
| PATCH | `/admin/users/{id}` | admin | Edita role/status/dados permitidos |
| POST | `/admin/users/{id}/reset-password` | admin | Reset local |
| POST | `/admin/users/{id}/revoke-sessions` | admin | Revoga refresh tokens |
| GET | `/admin/roles` | developer, lead, auditor, admin | Lista roles e permissões |

Regras críticas:

- Criar usuário não cria membership operacional.
- Usuário recém-criado não deve enxergar projects/groups até ser adicionado a um escopo.
- Não permitir auto-elevação.
- Não permitir remover/desativar/demover o último admin ativo do tenant.
- Reset de senha, desativação, alteração de role e revogação manual invalidam refresh tokens existentes do usuário.
- Não permitir remover ou demover o último `lead` direto de um project quando ele já existe.
- Se OIDC gerencia role, mudança local deve ser bloqueada ou marcada como override explícito.
- Cargo global deve ser limitado a `admin`, `lead`, `developer`, `auditor`.
- Capacidades como revisar, publicar ou solicitar decisão devem vir de memberships/capabilities por project/group, não de cargo global como `approver`.
- Toda mutação auditada, incluindo add/update/remove de memberships.

### 6.2 Organização, grupos e projetos

| Método | Rota | Permissão | Descrição |
|--------|------|-----------|-----------|
| GET | `/admin/org/tree` | developer, lead, auditor, admin conforme escopo | Árvore Organization → Groups → Projects |
| POST | `/admin/groups` | admin, lead conforme escopo | Cria group |
| PATCH | `/admin/groups/{id}` | admin, lead conforme escopo | Edita group |
| POST | `/admin/projects` | admin, lead conforme escopo | Cria project |
| PATCH | `/admin/projects/{id}` | admin, lead conforme escopo | Edita project |
| GET | `/admin/projects/{id}/members` | lead, admin, auditor conforme escopo | Lista membros |
| PUT | `/admin/projects/{id}/members/{user_id}` | lead, admin | Adiciona/atualiza membro |
| DELETE | `/admin/projects/{id}/members/{user_id}` | lead, admin | Remove membro |

Regras críticas:

- `lead` só administra project/group sob sua responsabilidade.
- `developer` só vê projects em que participa ou que são explicitamente públicos no tenant.
- `auditor` lê conforme escopo concedido.
- Alterar lead de project gera audit.
- Remover o último lead de um project deve ser bloqueado, salvo override admin.

### 6.3 Configurações gerais

| Método | Rota | Permissão | Descrição |
|--------|------|-----------|-----------|
| GET | `/admin/settings/general` | developer, lead, auditor, admin | Snapshot geral |
| PATCH | `/admin/settings/general` | admin, lead | Atualiza config não sensível |
| GET | `/admin/settings/effective` | developer, lead, auditor, admin | Config efetiva com origem |

### 6.4 Segredos

| Método | Rota | Permissão | Descrição |
|--------|------|-----------|-----------|
| GET | `/admin/secrets` | admin, auditor | Lista metadados sem valor |
| PUT | `/admin/secrets/{key}` | admin | Cria/rotaciona segredo |
| DELETE | `/admin/secrets/{key}` | admin | Revoga/remove |
| POST | `/admin/secrets/{key}/test` | admin | Testa conexão |

Payload nunca deve retornar segredo puro.

### 6.5 Providers e inferência

| Método | Rota | Permissão | Descrição |
|--------|------|-----------|-----------|
| GET | `/admin/inference/providers` | auditor, admin | Lista providers |
| PUT | `/admin/inference/providers/{id}` | admin | Atualiza provider |
| POST | `/admin/inference/providers/{id}/test` | admin | Testa provider |
| GET | `/admin/inference/models` | developer, lead, auditor, admin | Catálogo efetivo |
| PUT | `/admin/inference/models/global` | admin | Allowlist global |
| PUT | `/admin/inference/models/tenant/{tenant_id}` | admin | Allowlist tenant |

### 6.6 Sessões compartilháveis

| Método | Rota | Permissão | Descrição |
|--------|------|-----------|-----------|
| GET | `/admin/sessions` | developer, lead, auditor, admin conforme escopo | Lista sessões visíveis |
| GET | `/admin/sessions/{id}` | ACL | Detalhe |
| PATCH | `/admin/sessions/{id}` | owner, lead, admin | Arquiva/renomeia |
| GET | `/admin/sessions/{id}/acl` | owner, lead, admin | Lista ACL |
| PUT | `/admin/sessions/{id}/acl` | owner, lead, admin | Compartilha |
| DELETE | `/admin/sessions/{id}/acl/{principal}` | owner, lead, admin | Remove acesso |

### 6.7 Work items

Além dos endpoints atuais:

| Método | Rota | Permissão | Descrição |
|--------|------|-----------|-----------|
| GET | `/ui/work-items/{id}/events` | developer, lead, auditor, admin conforme escopo | Timeline |
| POST | `/ui/work-items/{id}/comments` | developer, lead, admin conforme escopo | Comentário |
| PATCH | `/ui/work-items/{id}/priority` | lead, admin | Prioridade |
| PATCH | `/ui/work-items/{id}/assignee` | lead, admin | Responsável |

### 6.8 Solicitações contextuais

Substitui o conceito de approval universal como centro do produto.

| Método | Rota | Permissão | Descrição |
|--------|------|-----------|-----------|
| GET | `/admin/requests` | developer, lead, auditor, admin conforme escopo | Lista solicitações visíveis |
| POST | `/admin/requests` | developer, lead, admin conforme escopo | Cria solicitação para lead/admin/auditoria |
| GET | `/admin/requests/{id}` | ACL/escopo | Detalhe |
| POST | `/admin/requests/{id}/comments` | ACL/escopo | Comenta |
| POST | `/admin/requests/{id}/resolve` | lead, admin, auditor conforme tipo | Resolve com decisão/motivo |
| POST | `/admin/requests/{id}/to-work-item` | lead, admin | Converte em work item |

Tipos iniciais:

- `lead_decision`
- `admin_exception`
- `compliance_question`
- `policy_exception`
- `shared_resource_change`
- `central_repo_change`

Regras críticas:

- Não usar solicitação para bloquear edição normal no repo local do developer.
- Solicitação deve ter `project_id` quando vier de projeto.
- Backend resolve o lead alvo pelo membership do project.
- Solicitação sensível deve registrar recurso, risco, policy e motivo.
- Toda resposta/fechamento gera audit.

---

## 7. Modelo de Dados Recomendado

### 7.1 Identidade

Tabelas:

- `auth_users`
- `tenant_members`
- `groups`
- `projects`
- `memberships`
- `api_keys`
- `refresh_revocations`
- `user_sessions` ou `auth_sessions` no futuro

Necessário:

- `auth_users.role` deve ser limitado aos cargos base: `admin`, `lead`, `developer`, `auditor`.
- `tenant_members` representa vínculo básico do usuário à empresa/tenant, sem acesso operacional automático.
- `memberships` representa capacidades contextuais por `scope_type`: organization, group ou project.
- Capabilities como `can_publish_agent` e `can_manage_project_members` devem ser derivadas de membership/escopo.
- `api_keys` deve ter role, escopo, expiração, revogação e último uso.

Tabela `memberships` recomendada para o MVP:

```sql
memberships (
    id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id UUID NOT NULL,
    scope_type TEXT NOT NULL, -- organization | group | project
    scope_id UUID NOT NULL,
    role TEXT NOT NULL,       -- admin | lead | developer | auditor
    created_by UUID,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (tenant_id, user_id, scope_type, scope_id)
)
```

Constraints obrigatórias:

- `scope_type IN ('organization', 'group', 'project')`.
- `role IN ('admin', 'lead', 'developer', 'auditor')`.
- RLS por `tenant_id`.
- Índice `(tenant_id, user_id)`.
- Índice `(tenant_id, scope_type, scope_id, role)`.
- Índice `(tenant_id, scope_type, scope_id, user_id)`.

No futuro, se a tabela genérica ficar pesada ou regras por escopo divergirem muito, podemos materializar views ou tabelas específicas (`group_memberships`, `project_memberships`) sem mudar o conceito de produto.

### 7.1.1 Organização

Tabelas recomendadas:

- `groups`
- `projects`
- `project_repositories`
- `memberships`

Campos mínimos:

- `tenant_id`
- `id`
- `name`
- `slug`
- `parent_id` quando aplicável
- `lead_user_id` ou tabela de leads múltiplos
- `created_at`
- `updated_at`
- `archived_at`

Regras:

- Project pertence a group.
- Group pertence a empresa/tenant.
- Work items, sessões, agentes e policies devem aceitar `project_id` quando fizer sentido.
- Auditor pode ter escopo em tenant, group ou project.

### 7.2 Sessões

Tabelas:

- `chat_sessions`
- `chat_messages`
- `session_events`
- `chat_session_acl`
- `session_summaries`

Necessário:

- `tenant_id` em todas.
- RLS em todas.
- ACL por `user` e `role`.
- `visibility`.
- `owner_id`.
- `archived_at`.
- Índices por tenant, owner, updated_at.

### 7.3 Work queue

Tabelas:

- `work_items`
- `work_item_events`
- `work_item_comments`
- `work_item_watchers`

Necessário:

- Chave por `(tenant_id, id)`.
- Timeline append-only.
- Histórico de status.
- Comentários com audit.
- Filtros eficientes.

### 7.3.1 Solicitações contextuais

Tabelas:

- `decision_requests`
- `decision_request_events`
- `decision_request_comments`

Campos mínimos:

- `tenant_id`
- `project_id`
- `requester_id`
- `target_user_id` ou `target_role`
- `type`
- `status`
- `risk_level`
- `resource_type`
- `resource_id`
- `session_id`
- `work_item_id`
- `policy_ref`
- `title`
- `body`
- `resolution`
- `resolved_by`
- `resolved_at`

Status:

- `open`
- `in_discussion`
- `resolved`
- `cancelled`

Não usar essa tabela como bloqueio universal do repo local. Ela existe para comunicação, decisão e rastreabilidade quando a ação envolve recurso compartilhado, sensível ou governado.

### 7.4 Configurações sensíveis

Tabelas/metadados:

- `secret_refs`
- `provider_configs`
- `provider_key_versions`
- `inference_provider_status`

Não armazenar segredo puro no Postgres se houver vault. Se Postgres for usado temporariamente:

- Criptografia em repouso.
- Chave fora do banco.
- Metadados separados do valor.
- Audit obrigatório.

---

## 8. Segurança

### 8.1 Controles obrigatórios

- JWT required em staging/prod.
- CORS explícito.
- Cookies httpOnly, secure e sameSite apropriado.
- CSRF considerado para mutações BFF se cookies forem usados em browser.
- Rate limit para login e mutações sensíveis.
- RLS em tabelas multi-tenant.
- Audit em toda mutação.
- Problem Details para erros públicos.
- Secrets write-only.
- Reautenticação para ações críticas.

### 8.2 Ações críticas

Exigir confirmação explícita do próprio usuário para:

- Aplicar patch local destrutivo.
- Rodar comando local destrutivo.
- Apagar arquivos.
- Fazer reset/revert irreversível.
- Executar ação fora do workspace permitido.

Exigir solicitação/decisão externa somente para:

- Alterar role.
- Desativar usuário.
- Revogar sessões.
- Rotacionar API key.
- Alterar provider key.
- Aplicar compliance pack.
- Criar break-glass.
- Publicar policy bundle.
- Publicar agente global.
- Alterar recurso compartilhado de project/group/tenant.
- Executar deploy/staging/prod/infra compartilhada.

Regra crítica:

- Repo local do developer não deve depender de lead/admin por padrão.
- Se a ação local é perigosa, use confirmação local e audit.
- Se cruza boundary corporativo, use solicitação contextual, policy ou break-glass.

### 8.3 Break-glass

Requisitos:

- Motivo obrigatório.
- Expiração obrigatória.
- Scope limitado.
- Audit imediato.
- Alerta SIEM.
- Visualização em compliance.
- Revogação manual.

### 8.4 Segredos

Regras:

- Nunca exibir valor salvo.
- Mostrar apenas prefixo/fingerprint.
- Armazenar hash quando aplicável.
- Rotação cria nova versão.
- Permitir teste sem expor segredo.
- Log nunca contém valor secreto.
- Redação automática em audit.

---

## 9. Escalabilidade e Eficiência

### 9.1 Frontend

Necessário:

- Paginação server-side.
- Filtros server-side.
- React Query com cache por tenant/rota/filtro.
- Skeletons em tabelas grandes.
- Virtualização para audit pesado.
- Debounce em busca.
- Mutations com optimistic update apenas quando seguro.
- Error boundary por seção.

### 9.2 Backend

Necessário:

- Índices por `tenant_id` em todas as listagens.
- Limites máximos de `limit`.
- Cursor pagination para audit/eventos.
- Queries sem `SELECT *`.
- Timeouts de integração.
- Jobs async para export grande.
- Outbox para SIEM.

### 9.3 Banco

Necessário:

- RLS consistente.
- Constraints de status/role/source.
- Chaves compostas onde ID é por tenant.
- GIN apenas onde JSONB é consultado.
- Retenção/particionamento para audit no futuro.
- Migrations idempotentes.

### 9.4 Observabilidade

Métricas:

- Login success/failure.
- 401/403 por rota.
- Mutations por role.
- Latência por endpoint admin.
- Export audit duration.
- Provider test success/failure.
- SIEM outbox backlog.
- Work items por status.
- Solicitações por tipo/status/risco.

---

## 10. UX/UI Profissional

### 10.1 Navegação

Usar sidebar colapsável inspirada no GitLab: mostrar apenas **tópicos-mãe** no primeiro nível e expandir filhos ao clicar. Isso reduz ruído, melhora orientação e evita uma sidebar enorme conforme o admin cresce.

Princípios:

- Primeiro nível sempre curto.
- Filhos aparecem apenas quando o tópico está expandido.
- Estado de expandido/colapsado persiste por usuário.
- Se uma rota filha está ativa, o tópico-mãe fica expandido automaticamente.
- Itens sem permissão não aparecem.
- Itens read-only podem aparecer com badge “somente leitura” quando fizer sentido.
- Badges de pendência aparecem no tópico-mãe e no filho específico.

Estrutura sugerida:

```text
Visão geral
  Dashboard
  Saúde do sistema

Trabalho
  Fila
  Sessões
  Solicitações

Organização
  Usuários
  Árvore organizacional
  Grupos
  Projetos
  Memberships

Agentes
  Agentes
  Skills
  Regras

Governança
  Policies
  Compliance
  Break-glass
  Auditoria

Configurações
  Geral
  Acesso
  Segurança
  Segredos
  Inferência
  Integrações
  Operação
```

Aplicação por área:

- **Usuários:** tópico `Organização`; filhos para usuários, groups, projects e memberships.
- **Configurações:** tópico próprio; filhos separados por risco.
- **Governança:** policies, compliance e audit ficam juntos porque são leitura/controle institucional.
- **Trabalho:** work queue, sessões e solicitações ficam juntos porque são fluxo diário.
- **Agentes:** agentes, skills e regras ficam juntos porque representam a camada produtiva do Central.

Comportamento por role/escopo:

- `developer`: vê Trabalho, Agentes permitidos e Organização apenas com seus memberships.
- `lead`: vê Trabalho e Organização para groups/projects sob sua responsabilidade.
- `auditor`: vê Governança/Auditoria e leitura de escopos permitidos.
- `admin`: vê tudo.

Cada item deve ter:

- Label PT-BR.
- Descrição curta.
- Role mínima.
- Escopo aplicável: organization, group ou project.
- Badge quando há pendência.
- Estado de permissão: oculto, read-only ou write.

Requisitos de implementação:

- Criar uma configuração central de navegação no frontend, não hardcode espalhado nas páginas.
- Cada item deve declarar `id`, `label`, `path`, `parent`, `requiredCapabilities`, `scopeType` e `badgeQueryKey`.
- O filtro visual deve usar sessão + memberships carregados do BFF.
- Estado atual: filtro por `role` do JWT/session implementado no frontend; `/dashboard/org` já aplica memberships para limitar mutações, edição de role e remoção de project members.
- O backend continua sendo autoritativo: esconder item não substitui `403`.
- Em mobile/estreito, sidebar vira drawer com a mesma lógica colapsável.

### 10.2 Header

Mostrar:

- Tenant atual.
- Usuário.
- Role.
- Ambiente: dev/staging/prod.
- Status backend resumido.
- Logout.

### 10.3 Estados de tela

Toda página precisa:

- Loading state.
- Empty state útil.
- Error state em PT-BR.
- 403 state específico.
- Toast de sucesso/erro.
- Confirmação para ação sensível.

### 10.4 Componentes

Padronizar:

- `DataTable`
- `ConfirmDialog`
- `SensitiveField`
- `RoleBadge`
- `TenantBadge`
- `AuditEventDrawer`
- `UserSelect`
- `WorkItemStatusBadge`
- `ProviderHealthBadge`
- `PermissionGate`

### 10.5 Linguagem

Padronizar PT-BR:

- `Approvals` → `Solicitações`
- `Queue` → `Fila`
- `Audit` → `Auditoria`
- `Inference` → `Inferência`
- `Compliance` → `Conformidade`
- `Open` → `Aberto`
- `In Progress` → `Em andamento`
- `Review` → `Em revisão`
- `Done` → `Concluído`

---

## 11. Matriz de Permissões Alvo

Roles base:

| Área | developer | lead | auditor | admin |
|------|-----------|------|---------|-------|
| Dashboard | read own/projects | read managed scope | read audit scope | full |
| Org tree | read memberships | manage assigned groups/projects | read audit scope | full |
| Users | none ou project members | invite/manage project members | read audit scope | full |
| Roles | read | read | read | full |
| API keys | own limited | none por padrão | metadata | full |
| Sessions | own/project shared | managed project | audit scope | full |
| Work queue | create/work project items | manage project queue | read audit scope | full |
| Solicitações | create/comment own/project | respond managed project | create/comment compliance | full |
| Agents | propose project agent | publish project/group agent | read | full |
| Rules | propose project rule | publish project/group rule | read | full |
| Policies | read effective | propose scoped policy | read/export evidence | full |
| Inference | read catalog | read effective config | read config metadata | full |
| Secrets | none | none por padrão | metadata | full |
| Compliance | none | read limited | read/export | full |
| Audit | own/project limited | managed scope | full read/export scope | full |

Capabilities contextuais:

| Capability | Escopo típico | Observação |
|------------|---------------|------------|
| `can_manage_project_members` | project/group | Normalmente derivada de lead |
| `can_publish_agent` | project/group/tenant | Developer propõe; lead/admin publica |
| `can_publish_rule` | project/group/tenant | Exige audit |
| `can_request_decision` | project | Developer abre solicitação |
| `can_resolve_decision` | project/admin | Lead/admin resolve conforme tipo |
| `can_manage_secrets` | tenant | Admin apenas |
| `can_export_audit` | tenant/project | Auditor/admin |
| `can_break_glass` | tenant | Admin com audit/expiração |

Backend deve implementar a versão autoritativa. Frontend usa a matriz apenas para UX.

---

## 12. Roadmap de Implementação

### P0 — Correções imediatas — CONCLUÍDO

Status: concluído em 2026-06-16.

- [x] Corrigir guard de `/oidc-callback`.
- [x] Montar `Toaster`.
- [x] Corrigir origem do admin.
- [x] Criar gate visual por role e 403 amigável.
- [x] Filtrar sidebar por role.
- [x] Remover fallback permissivo de role.
- [x] Padronizar mensagens PT-BR mais visíveis.

Critério de done:

- [x] Usuário sem permissão não vê rota sensível.
- [x] Se acessar URL direto, recebe 403 amigável.
- [x] OIDC funciona ponta a ponta.

### P1 — Identidade mínima — CONCLUÍDO

Status: concluído em 2026-06-16.

- [x] Backend: `GET /admin/users`.
- [x] Backend: `POST /admin/users` para criação local sem membership automática.
- [x] Backend: `PATCH /admin/users/{id}/role`.
- [x] Backend: roles base `admin`, `lead`, `developer`, `auditor`.
- [x] Backend: ativar/desativar usuário.
- [x] Backend: tabelas mínimas de `groups`, `projects` e `memberships` com `scope_type`.
- [x] UI: `/dashboard/users` dedicada para criação, busca, role/status e reset de senha local.
- [x] UI: `/dashboard/org` mínimo para project members, com criação local de usuário e seleção por usuário em vez de UUID manual.
- [x] UI: filtros, tabela/lista e edição inline/painéis em vez de modal clássico.
- [x] Audit em toda alteração sensível de usuários e memberships.

Critério de done:

- [x] Admin consegue listar e alterar cargos sem script.
- [x] Admin consegue criar project e definir lead.
- [x] Lead consegue ver membros do project sob sua responsabilidade.
- [x] Não é possível remover último admin.
- [x] Não é possível auto-elevar.

### P2 — Configurações sensíveis — CONCLUÍDO

Status: concluído em 2026-06-16 (MVP).

- [x] Backend: secrets metadata.
- [x] Backend: rotate provider key.
- [x] UI: `/dashboard/settings/secrets`.
- [x] UI: `/dashboard/settings/inference`.
- [x] Provider test.
- [x] Audit e confirmação.

Critério de done:

- [x] API key nunca é retornada.
- [x] Admin consegue rotacionar provider.
- [x] Auditor vê metadados sem segredo.

### P3 — Work queue e sessões profissionais — CONCLUÍDO (MVP)

- [x] Work item detail.
- [x] Timeline de eventos.
- [x] Comentários.
- [x] Assign/reassign.
- [x] Session detail.
- [x] Session ACL.
- [x] Share by user/role.
- [x] Solicitações contextuais ligadas a project/session/work item.

Critério de done:

- [x] Lead coordena fluxo de trabalho sem sair do admin.
- [x] Developer consegue abrir solicitação ao lead sem bloquear o repo local.
- [x] Lead consegue responder/fechar solicitação do project.
- [x] Sessão compartilhada respeita ACL.

### P4 — Governança de agentes/regras/policies — CONCLUÍDO (MVP)

- [x] CRUD de agentes.
- [x] Draft/review/publish.
- [x] CRUD de skills.
- [x] Rules review com motivo.
- [x] Policy bundle editor.
- [x] Rollback.

Critério de done:

- [x] Publicação de agente/regra é versionada e auditada.
- [x] Policy ativa é visível e recuperável.

### P5 — Compliance e operação enterprise — CONCLUÍDO (MVP)

- [x] Break-glass completo.
- [x] Compliance pack apply com preview.
- [x] Audit export assíncrono para grandes volumes.
- [x] Deployment/ops settings.
- [x] SIEM outbox monitor.

Critério de done:

- [x] Auditor consegue gerar relatório defensável.
- [x] Admin consegue operar incidentes.

---

## 13. Testes Necessários

### 13.1 Frontend

- Guard libera `/login` e `/oidc-callback`.
- Sidebar por role.
- `developer` não vê mutações administrativas.
- `auditor` não altera estado.
- `admin` vê settings sensíveis.
- `lead` vê apenas projects sob sua responsabilidade.
- 403 amigável.
- Form de segredo nunca mostra valor salvo.
- Confirmações aparecem para ações críticas.

### 13.2 Backend

- Usuário não auto-eleva role.
- Último admin não pode ser desativado.
- Role inválida é rejeitada.
- Cargo global fora de `admin`, `lead`, `developer`, `auditor` é rejeitado.
- Lead não administra project fora do seu escopo.
- RLS impede cross-tenant.
- Secrets nunca retornam valor.
- Audit é criado em mutações.
- Work item event criado em transição.
- Session ACL impede acesso indevido.
- Solicitação contextual resolve o lead alvo pelo project.

### 13.3 E2E

Fluxos mínimos:

1. Admin cria usuário developer.
2. Admin cria project e define lead.
3. Lead adiciona developer ao project.
4. Auditor exporta audit.
5. Developer tenta abrir settings sensíveis e recebe 403.
6. Admin rotaciona provider key.
7. Lead compartilha sessão com developer do project.
8. Developer abre solicitação contextual ao lead.
9. Lead responde solicitação sem bloquear o repo local.
10. Ação P3 em infra/secrets exige policy/break-glass/decisão admin.

---

## 14. Riscos e Decisões Críticas

### 14.1 Risco: RBAC dinâmico cedo demais

Criar sistema de permissões totalmente customizável agora pode atrasar o produto e aumentar superfície de bug.

Recomendação:

- Roles base fixas no curto prazo: `admin`, `lead`, `developer`, `auditor`.
- Não criar `approver`/`reviewer` como cargos globais.
- Permissões granulares devem nascer de memberships/capabilities por project/group, não de uma matriz livre demais.
- Permission sets totalmente customizáveis só depois de demanda real de piloto.

### 14.2 Risco: Config sensível no banco sem vault

Guardar API keys diretamente no Postgres aumenta risco.

Recomendação:

- Preferir secret backend/vault.
- Se usar Postgres temporariamente, criptografar e tratar como solução transitória.

### 14.3 Risco: UI esconder sem backend negar

Frontend-only RBAC é inseguro.

Recomendação:

- Toda rota sensível no backend com `require_any_role`.
- Testes de 403.

### 14.4 Risco: Admin global cross-tenant

Selector de tenant para admin global pode causar vazamento/acidente.

Recomendação:

- Tenant selector explícito com banner forte.
- Audit em troca de tenant.
- Operações destrutivas exigem confirmação com tenant escrito.

### 14.5 Risco: Audit pesado

Audit cresce rápido.

Recomendação:

- Cursor pagination.
- Retenção.
- Export async.
- Particionamento futuro por tempo/tenant.

### 14.6 Risco: approval virar burocracia

Se todo fluxo sensível exigir aprovação externa, o Central vira gargalo e perde aderência ao dia a dia de engenharia.

Recomendação:

- Matar approval universal como centro do produto.
- Usar confirmação local para ações perigosas no repo/workspace do developer.
- Usar solicitações contextuais para comunicação com lead/admin/auditoria.
- Usar policy/break-glass para fronteiras corporativas reais.
- Nunca exigir lead/admin para edição normal no repo local vinculado.

---

## 15. Definition of Done Global

O admin só deve ser considerado profissional quando:

- [ ] OIDC/login/logout funcionam sem redirecionamentos errados.
- [ ] Sidebar colapsável estilo GitLab está organizada por tópicos-mãe e respeita role/membership.
- [ ] Backend nega toda ação sem permissão.
- [ ] Usuários podem ser geridos sem script.
- [ ] Roles base `admin`, `lead`, `developer`, `auditor` funcionam de ponta a ponta.
- [ ] Hierarquia Organization → Groups → Projects está modelada.
- [ ] Leads são vinculados a projects/groups.
- [ ] Solicitações contextuais substituem approval universal.
- [ ] Repo local do developer não depende de approval externo para fluxo normal.
- [ ] Configurações sensíveis são write-only e auditadas.
- [ ] Settings Hub separa geral, acesso, segurança, segredos, integrações e operação.
- [ ] Provider/model settings são operáveis via UI.
- [x] Work queue tem detalhe, timeline e assignee.
- [x] Sessões têm detalhe e compartilhamento seguro.
- [ ] Audit tem filtros úteis e export confiável.
- [x] Compliance tem break-glass completo.
- [ ] Todas as telas têm loading/empty/error/403 states.
- [ ] Testes e2e cobrem roles principais.
- [ ] RLS protege tabelas multi-tenant.
- [ ] Documentação `RBAC_MATRIX.md` está alinhada ao código.

---

## 16. Próximo Passo Recomendado

Implementar primeiro **P0 + P1**.

Motivo:

- P0 remove bugs de fluxo e UX que bloqueiam confiança.
- P1 cria a base de identidade, cargos simples e hierarquia organizacional.
- Sem users/groups/projects/memberships, páginas sensíveis e CRUDs futuros continuarão dependentes de scripts e suposições.

Sequência sugerida:

1. Corrigir auth/guard/toasts/origin.
2. Criar `PermissionGate` e matriz frontend.
3. Ajustar backend para roles base (`admin`, `lead`, `developer`, `auditor`).
4. Implementar APIs `/admin/users`, `/admin/roles`, `/admin/org/tree` e memberships por escopo.
5. Criar páginas `/dashboard/users` e `/dashboard/org`.
6. Criar testes de RBAC/escopo UI/backend.

Depois disso, seguir para configurações sensíveis, inference admin e solicitações contextuais.
