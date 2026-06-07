#!/usr/bin/env bash
#
# startup-production.sh
# CentralChat — VPS startup (build + up + health checks)
#
# Sobe toda a stack de produção com docker compose.
# Assume que clone-pull.sh já foi executado.
#
# Uso:
#   cd infra && ./startup-production.sh           # build + up + health
#   ./startup-production.sh --no-build            # up sem rebuild
#   ./startup-production.sh --restart             # down + up (recria containers)
#   ./startup-production.sh --status              # só health check, sem restart
#
# Requisitos:
#   - Docker + docker compose instalados
#   - Rede infra_net criada (docker network create infra_net)
#   - PostgreSQL 16 + pgvector nativo no host (DB_HOST=host.docker.internal)
#   - vhosts/CentralChat_Backend/.env configurado
#   - vhosts/CentralChat_Frontend/.env configurado

set -uo pipefail

# ── Config ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CC_ROOT="${CC_ROOT:-$SCRIPT_DIR}"
COMPOSE_FILE="${CC_ROOT}/docker-compose.vps.yml"
COMPOSE_CMD="docker compose -f ${COMPOSE_FILE}"

DO_BUILD=true
DO_RESTART=false
STATUS_ONLY=false
NO_CACHE=false

for arg in "$@"; do
  case "$arg" in
    --no-build) DO_BUILD=false ;;
    --restart)  DO_RESTART=true ;;
    --status)   STATUS_ONLY=true ;;
    --no-cache) NO_CACHE=true ;;
    --help|-h)
      echo "Uso: $0 [--no-build] [--restart] [--status] [--no-cache]"
      echo ""
      echo "  --no-build  Sobe sem rebuild das imagens"
      echo "  --restart   docker compose down antes do up"
      echo "  --status    Apenas health check, não mexe nos containers"
      echo "  --no-cache  Build sem cache (docker build --no-cache)"
      exit 0
      ;;
  esac
done

# ── Cores ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

OK="${GREEN}✓${NC}"; WARN="${YELLOW}⚠${NC}"; ERR="${RED}✗${NC}"

# ── Helpers ─────────────────────────────────────────────────
banner() {
  echo ""
  echo -e "${BOLD}CentralChat — VPS Startup${NC}"
  echo -e "Root     : ${CYAN}${CC_ROOT}${NC}"
  echo -e "Compose  : ${CYAN}${COMPOSE_FILE}${NC}"
  echo "──────────────────────────────────────────"
  echo ""
}

die() { echo -e "${ERR} $1"; exit 1; }

# ── Pré-requisitos ──────────────────────────────────────────
check_prereqs() {
  echo -e "${BOLD}Pré-requisitos${NC}"

  # ── docker ──
  if command -v docker &>/dev/null; then
    echo -e "  ${OK} Docker: $(docker --version 2>/dev/null | head -1)"
  else
    die "Docker não encontrado."
  fi

  # ── docker compose ──
  if docker compose version &>/dev/null; then
    echo -e "  ${OK} Docker Compose: $(docker compose version 2>/dev/null | head -1)"
  else
    die "Docker Compose (plugin) não encontrado."
  fi

  # ── Rede infra_net ──
  if docker network inspect infra_net &>/dev/null; then
    echo -e "  ${OK} Rede infra_net"
  else
    echo -e "  ${WARN} Rede infra_net não existe. Criando..."
    docker network create infra_net || die "Falha ao criar infra_net."
    echo -e "  ${OK} Rede infra_net criada"
  fi

  # ── .env do Backend ──
  if [[ -f "${CC_ROOT}/vhosts/CentralChat_Backend/.env" ]]; then
    echo -e "  ${OK} vhosts/CentralChat_Backend/.env presente"
  else
    die "vhosts/CentralChat_Backend/.env não encontrado."
  fi

  # ── .env da Web UI ──
  if [[ -f "${CC_ROOT}/vhosts/CentralChat_Frontend/.env" ]]; then
    echo -e "  ${OK} vhosts/CentralChat_Frontend/.env presente"
  else
    die "vhosts/CentralChat_Frontend/.env não encontrado."
  fi

  # ── PostgreSQL (best-effort) ──
  if ss -tlnp 2>/dev/null | grep -q ':5432 '; then
    echo -e "  ${OK} PostgreSQL escutando na porta 5432"
  else
    echo -e "  ${WARN} PostgreSQL NÃO detectado na porta 5432 (pode estar em outro host)"
  fi

  # ── Nginx (best-effort) ──
  if systemctl is-active --quiet nginx 2>/dev/null; then
    echo -e "  ${OK} Nginx ativo"
  else
    echo -e "  ${WARN} Nginx não detectado via systemctl (pode ser outro proxy)"
  fi

  echo ""
}

# ── Health check individual ─────────────────────────────────
health_check() {
  local NAME="$1" PORT="$2" PATH="${3:-/}"
  local URL="http://127.0.0.1:${PORT}${PATH}"

  local CODE
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$URL" 2>/dev/null) || CODE="000"

  if [[ "$CODE" != "000" ]]; then
    echo -e "  ${OK} ${NAME} (${URL}) → ${CODE}"
    return 0
  else
    echo -e "  ${ERR} ${NAME} (${URL}) → sem resposta"
    return 1
  fi
}

# ── Health check com retry ──────────────────────────────────
health_with_retry() {
  local NAME="$1" PORT="$2" PATH="${3:-/}"
  local MAX=20 INTERVAL=5

  for ((i=1; i<=MAX; i++)); do
    if health_check "$NAME" "$PORT" "$PATH" 2>/dev/null; then
      return 0
    fi
    read -rt "$INTERVAL" <> <(:) 2>/dev/null || true
  done

  echo -e "  ${ERR} ${NAME} NÃO respondeu após $((MAX * INTERVAL / 60))min"
  return 1
}

# ── Migrations ──────────────────────────────────────────────
do_migrate() {
  echo -e "${BOLD}Rodando migrations...${NC}"

  # Executa run_migrations.py dentro do container orchestrator
  local MAX=10 INTERVAL=5
  for ((i=1; i<=MAX; i++)); do
    if docker exec central-orchestrator python scripts/run_migrations.py 2>&1; then
      echo -e "  ${OK} Migrations concluídas"
      return 0
    fi
    echo -e "  ${WARN} Tentativa ${i}/${MAX} — aguardando DB..."
    read -rt "$INTERVAL" <> <(:) 2>/dev/null || true
  done

  echo -e "  ${ERR} Migrations falharam após $((MAX * INTERVAL))s"
  return 1
}

# ── Seed auth user ──────────────────────────────────────────
do_seed() {
  echo -e "${BOLD}Verificando seed do utilizador...${NC}"

  local MAX=5 INTERVAL=3
  for ((i=1; i<=MAX; i++)); do
    if docker exec central-orchestrator python -c "
from app.auth import upsert_user
upsert_user(email='dev@local.test', password='changeme', client_id='default')
print('User seeded')
" 2>&1; then
      echo -e "  ${OK} Utilizador padrão verificado"
      return 0
    fi
    echo -e "  ${WARN} Tentativa ${i}/${MAX}..."
    read -rt "$INTERVAL" <> <(:) 2>/dev/null || true
  done

  echo -e "  ${WARN} Seed falhou (pode já ter sido executado)"
  return 0  # non-fatal
}

# ── Startup ─────────────────────────────────────────────────
do_startup() {
  cd "$CC_ROOT" || die "Não foi possível aceder a ${CC_ROOT}"

  if $DO_RESTART; then
    echo -e "${BOLD}Parando containers existentes...${NC}"
    $COMPOSE_CMD down --remove-orphans 2>&1 || true
    echo ""
  fi

  echo -e "${BOLD}Iniciando serviços...${NC}"
  local UP_FLAGS="-d"
  if $DO_BUILD; then
    UP_FLAGS="$UP_FLAGS --build"
    if $NO_CACHE; then
      echo -e "${YELLOW}Build sem cache ativado...${NC}"
      $COMPOSE_CMD build --no-cache 2>&1 || die "Build sem cache falhou."
    fi
  fi
  UP_FLAGS="$UP_FLAGS --force-recreate"
  $COMPOSE_CMD up $UP_FLAGS 2>&1 || {
    echo -e "${WARN} docker compose up reportou erro (pode ser falso positivo)"
  }
  echo ""

  # ── Aguardar estabilização ──
  echo -e "${BOLD}Aguardando containers estabilizarem...${NC}"
  read -rt 5 <> <(:) 2>/dev/null || true
}

# ── Health checks ───────────────────────────────────────────
do_health_checks() {
  echo -e "${BOLD}Health checks${NC}"
  local FAILS=0

  # orchestrator (FastAPI health endpoint)
  health_with_retry "Orchestrator" 8004 "/health" || ((FAILS++))

  # centralchat-web (SPA — aceitamos 2xx)
  health_check "Web UI" 5174 "/" || ((FAILS++))

  echo ""

  if [[ $FAILS -gt 0 ]]; then
    echo -e "${YELLOW}⚠ ${FAILS} health check(s) falharam.${NC}"
    echo -e "  Logs: ${CYAN}${COMPOSE_CMD} logs --tail 50 <serviço>${NC}"
    return 1
  else
    echo -e "${GREEN}Todos os serviços saudáveis.${NC}"
    return 0
  fi
}

# ── Status dos containers ───────────────────────────────────
show_status() {
  echo -e "${BOLD}Status dos containers${NC}"
  $COMPOSE_CMD ps 2>/dev/null || true
}

# ═════════════════════════════════════════════════════════════
banner

if $STATUS_ONLY; then
  echo -e "${YELLOW}Modo: apenas status + health${NC}"
  echo ""
  show_status
  echo ""
  do_health_checks
  exit $?
fi

check_prereqs
do_startup
do_migrate
do_seed
show_status
echo ""
do_health_checks
