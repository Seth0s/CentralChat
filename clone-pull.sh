#!/usr/bin/env bash
#
# clone-pull.sh
# CentralChat — sincroniza repositórios (dev e produção)
#
# Clone (se ausente) ou git pull em main para cada repositório.
# Seguro: avisa se há alterações locais, NÃO faz stash automático.
#
# Uso:
#   ./clone-pull.sh                    # no diretório infra/
#   ./clone-pull.sh --dry-run          # só verifica, não altera
#   ./clone-pull.sh --stash            # stash automático de alterações locais
#   CC_ROOT=/custom/path ./clone-pull.sh
#
# Requisitos:
#   - SSH agent com chave carregada
#   - git 2.x+

set -uo pipefail

# ── Config ──────────────────────────────────────────────────
CC_ROOT="${CC_ROOT:-./vhosts}"
BRANCH="main"
DRY_RUN=false
AUTO_STASH=false

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --stash)   AUTO_STASH=true ;;
    --help|-h)
      echo "Uso: $0 [--dry-run] [--stash]"
      echo ""
      echo "  CC_ROOT=/path    Diretório raiz dos vhosts (padrão: ./vhosts)"
      echo "  --dry-run        Verifica sem alterar nada"
      echo "  --stash          Faz git stash automático se houver alterações"
      exit 0
      ;;
  esac
done

# ── Repositórios ────────────────────────────────────────────
# Cada entrada: "NOME|URL"
REPOS=(
  "CentralChat_Backend|git@github.com:CentralChat/CentralChat_Backend.git"
  "CentralChat_Frontend|git@github.com:CentralChat/CentralChat_Frontend.git"
  "CentralChat_CLI|git@github.com:CentralChat/CentralChat_CLI.git"
  "CentralChat_Desktop|git@github.com:CentralChat/CentralChat_Desktop.git"
)

# ── Cores ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'

OK="${GREEN}✓${NC}"; WARN="${YELLOW}⚠${NC}"; ERR="${RED}✗${NC}"
CLONE="${CYAN}⬇${NC}"; PULL="${CYAN}↓${NC}"; DRY="${YELLOW}◎${NC}"

# ── Resolver caminho absoluto ───────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CC_ROOT="$(cd "$SCRIPT_DIR/$CC_ROOT" 2>/dev/null && pwd || echo "$SCRIPT_DIR/$CC_ROOT")"

# ── Helpers ─────────────────────────────────────────────────
banner() {
  echo ""
  echo -e "${BOLD}CentralChat — Repo Sync${NC}"
  echo -e "Root  : ${CYAN}${CC_ROOT}${NC}"
  echo -e "Branch: ${CYAN}${BRANCH}${NC}"
  $DRY_RUN && echo -e "Mode  : ${DRY} ${YELLOW}dry-run (sem alterações)${NC}"
  $AUTO_STASH && echo -e "Stash : ${YELLOW}automático para alterações locais${NC}"
  echo "──────────────────────────────────────────"
  echo ""
}

summary() {
  printf "  %b %-18s %b %s\n" "$1" "$2" "$3" "$4"
}

# ── Sincroniza um repositório ───────────────────────────────
sync_repo() {
  local NAME="$1" URL="$2" DIR="${CC_ROOT}/${NAME}"

  # ── Clone se ausente ──
  if [[ ! -d "$DIR" ]]; then
    if $DRY_RUN; then
      summary "$DRY" "$NAME" "$CLONE" "(dry) would clone"
      return 5  # DRY_SKIP
    fi
    echo -e "${CLONE} Cloning ${BOLD}${NAME}${NC}..."
    if git clone "$URL" "$DIR" 2>&1 | tail -1; then
      summary "$OK" "$NAME" "$CLONE" "cloned"
      return 0  # CLONED
    else
      summary "$ERR" "$NAME" "$CLONE" "FAILED (clone)"
      return 1  # ERROR
    fi
  fi

  cd "$DIR" || { summary "$ERR" "$NAME" "$ERR" "FAILED (cd)"; return 1; }

  # ── Dry-run: apenas verifica estado ──
  if $DRY_RUN; then
    git fetch origin "$BRANCH" 2>/dev/null || true
    local L R
    L=$(git rev-parse HEAD 2>/dev/null) || true
    R=$(git rev-parse "origin/${BRANCH}" 2>/dev/null) || true
    if [[ "$L" != "$R" && -n "$L" && -n "$R" ]]; then
      local DIRTY=""
      git diff-index --quiet HEAD -- 2>/dev/null || DIRTY=" ⚠dirty"
      summary "$DRY" "$NAME" "$PULL" "(dry) behind${DIRTY}"
      cd "$CC_ROOT" || true
      return 5  # DRY_SKIP
    else
      summary "$OK" "$NAME" "$OK" "up-to-date"
      cd "$CC_ROOT" || true
      return 2  # CLEAN
    fi
  fi

  # ── Branch check ──
  local CURRENT
  CURRENT=$(git branch --show-current 2>/dev/null) || true
  if [[ "$CURRENT" != "$BRANCH" ]]; then
    echo -e "${WARN} ${NAME}: em '${YELLOW}${CURRENT:-?}${NC}', trocando para '${GREEN}${BRANCH}${NC}'..."
    git checkout "$BRANCH" 2>/dev/null || true
  fi

  # ── Alterações locais ──
  if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    if $AUTO_STASH; then
      echo -e "${WARN} ${NAME}: stash automático de alterações locais..."
      local MSG="auto-stash $(date -u +%Y-%m-%dT%H:%M:%SZ)"
      git stash push -m "$MSG" 2>/dev/null
      return 4  # STASHED (continua para pull abaixo)
    else
      summary "$WARN" "$NAME" "$WARN" "SKIPPED (uncommitted changes)"
      echo -e "       ${YELLOW}Dica:${NC} cd ${DIR} && git stash"
      cd "$CC_ROOT" || true
      return 1  # ERROR
    fi
  fi

  # ── Fetch + pull ──
  git fetch origin "$BRANCH" 2>/dev/null || true

  local LOCAL REMOTE
  LOCAL=$(git rev-parse HEAD 2>/dev/null) || true
  REMOTE=$(git rev-parse "origin/${BRANCH}" 2>/dev/null) || true

  if [[ "$LOCAL" == "$REMOTE" && -n "$LOCAL" ]]; then
    summary "$OK" "$NAME" "$OK" "up-to-date"
    cd "$CC_ROOT" || true
    return 2  # CLEAN
  fi

  echo -e "${PULL} Pulling ${BOLD}${NAME}${NC}..."
  if git pull origin "$BRANCH" 2>&1 | tail -1; then
    summary "$OK" "$NAME" "$PULL" "pulled"
    cd "$CC_ROOT" || true
    return 3  # PULLED
  else
    summary "$ERR" "$NAME" "$PULL" "FAILED (merge conflict?)"
    cd "$CC_ROOT" || true
    return 1  # ERROR
  fi
}

# ── Instala dependências após clone/pull ─────────────────────
install_deps() {
  local NAME="$1" DIR="$2" ACTION="$3"  # ACTION: cloned|pulled
  local ICON="$4"

  cd "$DIR" || return 1

  # ── Python / pip ── (CentralChat_Backend)
  if [[ -f "requirements.txt" ]]; then
    if $DRY_RUN; then
      echo -e "       ${DRY} pip install (dry)"
    elif command -v pip &>/dev/null; then
      if [[ "$ACTION" == "cloned" ]] || ! git diff --quiet "@{1}" -- requirements.txt 2>/dev/null; then
        echo -e "       ${ICON} pip install -r requirements.txt..."
        pip install -r requirements.txt --quiet 2>&1 | tail -1 || true
      fi
    else
      echo -e "       ${WARN} pip não encontrado — pulando (Docker faz o build)"
    fi
  fi

  # ── Node / Bun ── (CentralChat_Frontend)
  if [[ -f "package.json" ]]; then
    if $DRY_RUN; then
      echo -e "       ${DRY} bun install (dry)"
    elif command -v bun &>/dev/null; then
      if [[ "$ACTION" == "cloned" ]] || ! git diff --quiet "@{1}" -- bun.lock 2>/dev/null; then
        echo -e "       ${ICON} bun install..."
        bun install --silent 2>&1 | tail -1 || true
      fi
    else
      echo -e "       ${WARN} bun não encontrado — pulando (Docker faz o build)"
    fi
  fi

  cd "$CC_ROOT" || true
}

# ── Main ────────────────────────────────────────────────────
banner

FAILURES=0 CLONES=0 PULLS=0 CLEAN=0 STASHED=0 DRY_SKIPS=0

for ENTRY in "${REPOS[@]}"; do
  NAME="${ENTRY%%|*}"
  URL="${ENTRY#*|}"
  DIR="${CC_ROOT}/${NAME}"
  sync_repo "$NAME" "$URL"; RC=$?
  case $RC in
    0) ((CLONES++))
       install_deps "$NAME" "$DIR" "cloned" "$CLONE" ;;
    1) ((FAILURES++)) ;;
    2) ((CLEAN++)) ;;
    3) ((PULLS++))
       install_deps "$NAME" "$DIR" "pulled" "$PULL" ;;
    4) ((STASHED++)) ;;
    5) ((DRY_SKIPS++)) ;;
  esac
done

# ── Resumo ──────────────────────────────────────────────────
echo ""
echo "──────────────────────────────────────────"
echo -e "${BOLD}Resumo${NC}"
echo -e "  ${GREEN}Clones    :${NC} ${CLONES}"
echo -e "  ${CYAN}Pulls     :${NC} ${PULLS}"
echo -e "  ${GREEN}Up-to-date:${NC} ${CLEAN}"
$DRY_RUN && echo -e "  ${YELLOW}Dry skips :${NC} ${DRY_SKIPS}"
[[ $STASHED -gt 0 ]] && echo -e "  ${YELLOW}Stashados :${NC} ${STASHED}"
echo -e "  ${RED}Falhas    :${NC} ${FAILURES}"
echo ""

if [[ $FAILURES -gt 0 ]]; then
  echo -e "${RED}⚠ ${FAILURES} repositório(s) com problemas.${NC}"
  exit 1
elif $DRY_RUN; then
  echo -e "${GREEN}Dry-run concluído.${NC}"
else
  echo -e "${GREEN}Tudo sincronizado.${NC}"
fi
