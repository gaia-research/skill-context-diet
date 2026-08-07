#!/usr/bin/env bash
# Transactional one-liner installer for the context-diet agent skill.
# Usage: bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh)

set -euo pipefail

REPO="gaia-research/skill-context-diet"
RAW="https://raw.githubusercontent.com/${REPO}/main"
SKILL_NAME="context-diet"
FILES=(
  context_diet.py
  context_diet_ablation.py
  SKILL.md
  METHODOLOGY.md
  ABLATION.md
  WORKFLOW.md
  bakeoff.workflow.js
  ablation.workflow.js
)

if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  BLUE=$'\033[34m'; RESET=$'\033[0m'
else
  BOLD=''; DIM=''; GREEN=''; YELLOW=''; BLUE=''; RESET=''
fi

say()  { printf '%s\n' "$*"; }
info() { printf '%s→%s %s\n' "$BLUE" "$RESET" "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }

if ! command -v python3 >/dev/null 2>&1; then
  warn "python3 not found — context-diet requires Python 3.8+"
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  warn "curl not found"
  exit 1
fi

# Locate a skills directory. Pi's user skill directory is checked first when present.
CANDIDATES=()
[ -d "$HOME/.pi/agent/skills" ] && CANDIDATES+=("$HOME/.pi/agent/skills")
[ -d ".agents/skills" ]         && CANDIDATES+=(".agents/skills")
[ -d ".claude/skills" ]         && CANDIDATES+=(".claude/skills")
[ -d "$HOME/.claude/skills" ]   && CANDIDATES+=("$HOME/.claude/skills")
[ -d "$HOME/.agents/skills" ]   && CANDIDATES+=("$HOME/.agents/skills")

TARGET_DIR=""
if [ "${#CANDIDATES[@]}" -eq 0 ]; then
  info "No skills directory found. Creating ${BOLD}.agents/skills${RESET} in current dir."
  mkdir -p ".agents/skills"
  TARGET_DIR=".agents/skills"
elif [ "${#CANDIDATES[@]}" -eq 1 ]; then
  TARGET_DIR="${CANDIDATES[0]}"
  info "Detected skills directory: ${BOLD}${TARGET_DIR}${RESET}"
else
  say ""
  say "${BOLD}Multiple skills directories found. Where should context-diet go?${RESET}"
  i=1
  for candidate in "${CANDIDATES[@]}"; do
    printf "  ${BOLD}%d)${RESET} %s\n" "$i" "$candidate"
    i=$((i + 1))
  done
  say ""
  printf "Select [1-%d]: " "${#CANDIDATES[@]}"
  read -r choice
  if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#CANDIDATES[@]}" ]; then
    warn "Invalid selection. Aborting."
    exit 1
  fi
  TARGET_DIR="${CANDIDATES[$((choice - 1))]}"
fi

INSTALL_DIR="${TARGET_DIR}/${SKILL_NAME}"
if [ -d "$INSTALL_DIR" ]; then
  warn "${BOLD}${INSTALL_DIR}${RESET} already exists."
  printf "Replace transactionally? [y/N]: "
  read -r reply
  case "$reply" in
    y|Y|yes|YES) ;;
    *) info "Aborted. No changes made."; exit 0 ;;
  esac
fi

# Download and validate in the destination filesystem before touching an old install.
STAGE_DIR=$(mktemp -d "${TARGET_DIR}/.${SKILL_NAME}.install.XXXXXX")
BACKUP_DIR=""
cleanup() {
  status=$?
  if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ] && [ ! -d "$INSTALL_DIR" ]; then
    mv "$BACKUP_DIR" "$INSTALL_DIR" || true
  fi
  [ -n "${STAGE_DIR:-}" ] && [ -d "$STAGE_DIR" ] && rm -rf "$STAGE_DIR"
  exit "$status"
}
trap cleanup EXIT HUP INT TERM

for file in "${FILES[@]}"; do
  info "Fetching ${file}..."
  curl -fsSL "${RAW}/${file}" -o "${STAGE_DIR}/${file}"
  if [ ! -s "${STAGE_DIR}/${file}" ]; then
    warn "Downloaded file is empty: ${file}"
    exit 1
  fi
done
chmod 0755 "${STAGE_DIR}/context_diet.py" "${STAGE_DIR}/context_diet_ablation.py"
chmod 0600 "${STAGE_DIR}"/*.md "${STAGE_DIR}"/*.workflow.js

PYTHONPYCACHEPREFIX="${STAGE_DIR}/.pycache" python3 -m py_compile \
  "${STAGE_DIR}/context_diet.py" "${STAGE_DIR}/context_diet_ablation.py"
rm -rf "${STAGE_DIR}/.pycache"
grep -q '^name: context-diet$' "${STAGE_DIR}/SKILL.md"
grep -q 'export const meta' "${STAGE_DIR}/ablation.workflow.js"

if [ -d "$INSTALL_DIR" ]; then
  BACKUP_DIR="${TARGET_DIR}/.${SKILL_NAME}.backup.$$"
  mv "$INSTALL_DIR" "$BACKUP_DIR"
fi
mv "$STAGE_DIR" "$INSTALL_DIR"
STAGE_DIR=""
if [ -n "$BACKUP_DIR" ]; then
  rm -rf "$BACKUP_DIR"
  BACKUP_DIR=""
fi
trap - EXIT HUP INT TERM

ok "Installed and validated at ${BOLD}${INSTALL_DIR}${RESET}"
say ""
say "${BOLD}Requirements check${RESET}"
PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
ok "python3 ${PYVER} available"
if python3 -c "import matplotlib" >/dev/null 2>&1; then
  ok "matplotlib available (charts enabled)"
else
  warn "matplotlib not found — analyzer/ablation work; charts need: pip install matplotlib"
fi

say ""
say "${BOLD}${GREEN}context-diet is ready.${RESET}"
say "  ${DIM}# Pi (other hosts may expose /context-diet):${RESET}"
say "  ${BOLD}/skill:context-diet CLAUDE.md${RESET}"
say ""
say "  ${DIM}# Direct measurement:${RESET}"
say "  ${BOLD}python3 ${INSTALL_DIR}/context_diet.py CLAUDE.md${RESET}"
say ""
say "  ${DIM}# Resumable ablation status:${RESET}"
say "  ${BOLD}python3 ${INSTALL_DIR}/context_diet.py ablate status CLAUDE.md${RESET}"
