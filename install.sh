#!/usr/bin/env bash
#
# install.sh — one-liner installer for the context-diet agent skill.
#
# Usage:
#   bash <(curl -sL https://raw.githubusercontent.com/gaia-research/skill-context-diet/main/install.sh)
#
# Detects the local agent skills directory and drops context-diet/ inside it.

set -euo pipefail

REPO="gaia-research/skill-context-diet"
RAW="https://raw.githubusercontent.com/${REPO}/main"
SKILL_NAME="context-diet"

# ---------------------------------------------------------------------------
# Colors (auto-disabled when stdout is not a TTY)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'
  BLUE=$'\033[34m'; RESET=$'\033[0m'
else
  BOLD=''; DIM=''; GREEN=''; YELLOW=''; BLUE=''; RESET=''
fi

say()  { printf '%s\n' "$*"; }
info() { printf '%s→%s %s\n'   "$BLUE"   "$RESET" "$*"; }
ok()   { printf '%s✓%s %s\n'   "$GREEN"  "$RESET" "$*"; }
warn() { printf '%s!%s %s\n'   "$YELLOW" "$RESET" "$*"; }

# ---------------------------------------------------------------------------
# Locate a skills directory
# ---------------------------------------------------------------------------
CANDIDATES=()
[ -d ".agents/skills" ]           && CANDIDATES+=(".agents/skills")
[ -d ".claude/skills" ]           && CANDIDATES+=(".claude/skills")
[ -d "$HOME/.claude/skills" ]     && CANDIDATES+=("$HOME/.claude/skills")
[ -d "$HOME/.agents/skills" ]     && CANDIDATES+=("$HOME/.agents/skills")

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
  for c in "${CANDIDATES[@]}"; do
    printf "  ${BOLD}%d)${RESET} %s\n" "$i" "$c"
    i=$((i + 1))
  done
  say ""
  printf "Select [1-${#CANDIDATES[@]}]: "
  read -r choice
  if ! [[ "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "${#CANDIDATES[@]}" ]; then
    warn "Invalid selection. Aborting."
    exit 1
  fi
  TARGET_DIR="${CANDIDATES[$((choice - 1))]}"
fi

INSTALL_DIR="${TARGET_DIR}/${SKILL_NAME}"

# ---------------------------------------------------------------------------
# Confirm overwrite if already installed
# ---------------------------------------------------------------------------
if [ -d "$INSTALL_DIR" ]; then
  warn "${BOLD}${INSTALL_DIR}${RESET} already exists."
  printf "Overwrite? [y/N]: "
  read -r reply
  case "$reply" in
    y|Y|yes|YES) rm -rf "$INSTALL_DIR" ;;
    *) info "Aborted. No changes made."; exit 0 ;;
  esac
fi

mkdir -p "$INSTALL_DIR"

# ---------------------------------------------------------------------------
# Fetch files
# ---------------------------------------------------------------------------
info "Fetching context_diet.py..."
curl -fsSL "${RAW}/context_diet.py" -o "${INSTALL_DIR}/context_diet.py"
chmod +x "${INSTALL_DIR}/context_diet.py"

info "Fetching SKILL.md..."
curl -fsSL "${RAW}/SKILL.md" -o "${INSTALL_DIR}/SKILL.md"

info "Fetching METHODOLOGY.md..."
curl -fsSL "${RAW}/METHODOLOGY.md" -o "${INSTALL_DIR}/METHODOLOGY.md"

ok "Installed to ${BOLD}${INSTALL_DIR}${RESET}"

# ---------------------------------------------------------------------------
# Post-install checks
# ---------------------------------------------------------------------------
say ""
say "${BOLD}Requirements check${RESET}"

if command -v python3 >/dev/null 2>&1; then
  PYVER=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  ok "python3 ${PYVER} available"
else
  warn "python3 not found — context-diet requires Python 3.8+"
fi

if python3 -c "import matplotlib" >/dev/null 2>&1; then
  ok "matplotlib available (charts enabled)"
else
  warn "matplotlib not found — the analyzer works without it; charts need: pip install matplotlib"
fi

# ---------------------------------------------------------------------------
# Post-install hint
# ---------------------------------------------------------------------------
say ""
say "${BOLD}${GREEN}context-diet is ready.${RESET}"
say ""
say "  ${DIM}# From an agent conversation:${RESET}"
say "  ${BOLD}/context-diet CLAUDE.md${RESET}"
say ""
say "  ${DIM}# Directly — measure any oversized context file:${RESET}"
say "  ${BOLD}python3 ${INSTALL_DIR}/context_diet.py CLAUDE.md${RESET}"
say ""
