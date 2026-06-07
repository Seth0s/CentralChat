#!/usr/bin/env bash
#
# startup-testing.sh
# CentralChat — ambiente dev (build + up + health checks)
#
# Sobe a stack de desenvolvimento com Docker Compose:
#   postgres (pgvector 16), orchestrator (FastAPI), centralchat-web (TanStack Start)
# O orchestrator faz migrate + seed automaticamente ao iniciar.
#
# Uso:
#   cd infra && ./startup-testing.sh               # build + up + health
#   ./startup-testing.sh --no-build                # up sem rebuild
#   ./startup-testing.sh --restart                 # down + up (recria containers)
#   ./startup-testing.sh --status                  # só health check, não mexe nos containers
#   ./startup-testing.sh --clean                   # down + apaga volume do banco + up
#
# Requisitos:
#   - Docker + docker compose
#   - vhosts/CentralChat_Backend/.env configurado
#   - vhosts/CentralChat_Frontend/.env configurado

set -uo pipefail

# ── Config ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CC_ROOT="${CC_ROOT:-$SCRIPT_DIR}"
COMPOSE_FILE="${CC_ROOT}/docker-compose.dev.yml"
COMPOSE_CMD="docker compose -f ${COMPOSE_FILE}"

DO_BUILD=true
DO_RESTART=false
DO_CLEAN=false
STATUS_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --no-build) DO_BUILD=false ;;
    --restart)  DO_RESTART=true ;;
    --clean)    DO_CLEAN=true ;;
    --status)   STATUS_ONLY=true ;;
    --help|-h)
      echo "Uso: $0 [--no-build] [--restart] [--clean] [--status]"
      echo ""
      echo "  --no-build  Sobe sem rebuild das imagens"
      echo "  --restart   docker compose down antes do up"
      echo "  --clean     docker compose down -v (apaga BD) + up fresco"
      echo "  --status    Apenas health check, não mexe nos containers"
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
  echo -e "${BOLD}CentralChat — Dev Startup${NC}"
  echo -e "Root    : ${CYAN}${CC_ROOT}${NC}"
  echo -e "Compose : ${CYAN}${COMPOSE_FILE}${NC}"
  echo "──────────────────────────────────────────"
  echo ""
}

die() { echo -e "${ERR} $1"; exit 1; }

# ── Bootstrap .env ──────────────────────────────────────────
bootstrap_env() {
  echo -e "${BOLD}Bootstrap .env files${NC}"

  # Backend .env
  local BE_ENV="${CC_ROOT}/vhosts/CentralChat_Backend/.env"
  local BE_EXAMPLE="${CC_ROOT}/vhosts/CentralChat_Backend/.env.example"
  if [[ ! -f "$BE_ENV" ]]; then
    if [[ -f "$BE_EXAMPLE" ]]; then
      cp "$BE_EXAMPLE" "$BE_ENV"
      echo -e "  ${OK} vhosts/CentralChat_Backend/.env criado a partir de .env.example"
    else
      echo -e "  ${WARN} vhosts/CentralChat_Backend/.env.example não encontrado"
    fi
  else
    echo -e "  ${OK} vhosts/CentralChat_Backend/.env já existe"
  fi

  # CentralChat_Frontend .env
  local WEB_ENV="${CC_ROOT}/vhosts/CentralChat_Frontend/.env"
  local WEB_EXAMPLE="${CC_ROOT}/vhosts/CentralChat_Frontend/.env.example"
  if [[ ! -f "$WEB_ENV" ]]; then
    if [[ -f "$WEB_EXAMPLE" ]]; then
      cp "$WEB_EXAMPLE" "$WEB_ENV"
      echo -e "  ${OK} vhosts/CentralChat_Frontend/.env criado a partir de .env.example"
    else
      echo -e "  ${WARN} vhosts/CentralChat_Frontend/.env.example não encontrado"
    fi
  else
    echo -e "  ${OK} vhosts/CentralChat_Frontend/.env já existe"
  fi

  echo ""
}

# ── Pré-requisitos ──────────────────────────────────────────
check_prereqs() {
  echo -e "${BOLD}Pré-requisitos${NC}"

  command -v docker &>/dev/null || die "Docker não encontrado."
  echo -e "  ${OK} Docker: $(docker --version 2>/dev/null | head -1)"

  docker compose version &>/dev/null || die "Docker Compose não encontrado."
  echo -e "  ${OK} Docker Compose: $(docker compose version 2>/dev/null | head -1)"

  if [[ -f "${CC_ROOT}/vhosts/CentralChat_Backend/.env" ]]; then
    echo -e "  ${OK} vhosts/CentralChat_Backend/.env presente"
  else
    die "vhosts/CentralChat_Backend/.env não encontrado. Rode ./clone-pull.sh primeiro."
  fi

  if [[ -f "${CC_ROOT}/vhosts/CentralChat_Frontend/.env" ]]; then
    echo -e "  ${OK} vhosts/CentralChat_Frontend/.env presente"
  else
    die "vhosts/CentralChat_Frontend/.env não encontrado. Rode ./clone-pull.sh primeiro."
  fi

  echo ""
}

# ── Health checks ───────────────────────────────────────────
health_check() {
  local NAME="$1" URL="$2"
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

health_with_retry() {
  local NAME="$1" URL="$2"
  local MAX=20 INTERVAL=3

  for ((i=1; i<=MAX; i++)); do
    if health_check "$NAME" "$URL" 2>/dev/null; then
      return 0
    fi
    read -rt "$INTERVAL" <> <(:) 2>/dev/null || true
  done

  echo -e "  ${ERR} ${NAME} NÃO respondeu após $((MAX * INTERVAL))s"
  return 1
}

docker_health() {
  local CONTAINER="$1" LABEL="$2"
  local STATE
  STATE=$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null) || STATE="not_found"

  case "$STATE" in
    healthy)
      echo -e "  ${OK} ${LABEL} (${CONTAINER}) — healthy"
      return 0
      ;;
    starting)
      echo -e "  ${CYAN}⏳${NC} ${LABEL} (${CONTAINER}) — starting..."
      return 1
      ;;
    *)
      echo -e "  ${ERR} ${LABEL} (${CONTAINER}) — ${STATE}"
      return 1
      ;;
  esac
}

wait_docker_health() {
  local CONTAINER="$1" LABEL="$2" MAX=25 INTERVAL=3

  for ((i=1; i<=MAX; i++)); do
    if docker_health "$CONTAINER" "$LABEL" 2>/dev/null; then
      return 0
    fi
    read -rt "$INTERVAL" <> <(:) 2>/dev/null || true
  done
  return 1
}

# ── Startup ─────────────────────────────────────────────────
do_startup() {
  cd "$CC_ROOT" || die "Não foi possível aceder a ${CC_ROOT}"

  if $DO_CLEAN; then
    echo -e "${YELLOW}${BOLD}Limpando tudo (--clean)...${NC}"
    $COMPOSE_CMD down -v --remove-orphans 2>&1 || true
    echo ""
  elif $DO_RESTART; then
    echo -e "${BOLD}Parando containers existentes...${NC}"
    $COMPOSE_CMD down --remove-orphans 2>&1 || true
    echo ""
  fi

  if $DO_BUILD; then
    echo -e "${BOLD}Build das imagens...${NC}"
    $COMPOSE_CMD build 2>&1 || die "Build falhou."
    echo ""
  fi

  echo -e "${BOLD}Iniciando serviços...${NC}"
  $COMPOSE_CMD up -d 2>&1 || die "docker compose up falhou."
  echo ""
}

# ── Health checks ───────────────────────────────────────────
do_health_checks() {
  echo -e "${BOLD}Health checks${NC}"
  local FAILS=0

  # postgres (Docker healthcheck: pg_isready)
  wait_docker_health "central-postgres-test" "PostgreSQL" || ((FAILS++))

  # orchestrator (FastAPI — demora mais por causa de migrate)
  health_with_retry "Orchestrator" "http://127.0.0.1:8004/health" || ((FAILS++))

  # centralchat-web (TanStack Start dev server)
  health_check "Web UI" "http://127.0.0.1:5174" || ((FAILS++))

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

# ── Status ──────────────────────────────────────────────────
show_status() {
  echo -e "${BOLD}Status dos containers${NC}"
  $COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
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

bootstrap_env
check_prereqs
do_startup
show_status
echo ""
do_health_checks
