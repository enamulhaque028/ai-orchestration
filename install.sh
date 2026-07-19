#!/usr/bin/env bash
# Install Engineering Manager (`em`) and runtime prerequisites.
# macOS and Linux.
#
# One-liner:
#   curl -fsSL https://raw.githubusercontent.com/enamulhaque028/ai-orchestration/main/install.sh | bash
#
# Windows: use install.ps1 instead (see README).
set -euo pipefail

REPO_GIT="git+https://github.com/enamulhaque028/ai-orchestration.git"
LOCAL_BIN="${HOME}/.local/bin"
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
RED=$'\033[0;31m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

ok() { printf '%s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
err() { printf '%s✗%s %s\n' "$RED" "$RESET" "$*" >&2; }
info() { printf '%s\n' "$*"; }

have() { command -v "$1" >/dev/null 2>&1; }

python_ok() {
  local bin="$1" ver major minor
  ver="$("$bin" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  [[ -n "$ver" ]] || return 1
  major="${ver%%.*}"
  minor="${ver#*.}"
  (( major > 3 || (major == 3 && minor >= 11) ))
}

find_python() {
  local c
  for c in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if have "$c" || [[ -x "$c" ]]; then
      if python_ok "$c"; then
        printf '%s\n' "$c"
        return 0
      fi
    fi
  done
  return 1
}

setup_brew_shellenv() {
  if [[ -x /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -x /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

ensure_brew() {
  if have brew; then
    ok "Homebrew found"
    return 0
  fi
  [[ "$(uname -s)" == "Darwin" ]] || return 1
  warn "Installing Homebrew (may ask for your password)…"
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  setup_brew_shellenv
  have brew || { err "Homebrew not available after install"; return 1; }
  ok "Homebrew installed"
}

ensure_python() {
  local py
  if py="$(find_python)"; then
    ok "Python $($py --version 2>&1) ($py)"
    return 0
  fi

  warn "Python 3.11+ not found — installing…"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    ensure_brew || true
    if have brew; then
      brew install python
    fi
  elif have apt-get; then
    sudo apt-get update -y
    sudo apt-get install -y python3 python3-venv python3-pip
  else
    err "Install Python 3.11+ manually, then re-run this script."
    return 1
  fi

  setup_brew_shellenv || true
  if py="$(find_python)"; then
    ok "Python $($py --version 2>&1) ($py)"
    return 0
  fi
  err "Python 3.11+ still missing after install attempt."
  return 1
}

ensure_pipx() {
  if have pipx; then
    ok "pipx found ($(command -v pipx))"
    return 0
  fi

  warn "Installing pipx…"
  if have brew; then
    brew install pipx
  elif have apt-get; then
    sudo apt-get install -y pipx || true
  fi

  if ! have pipx; then
    local py
    py="$(find_python)"
    mkdir -p "$LOCAL_BIN"
    export PATH="$LOCAL_BIN:$PATH"
    "$py" -m pip install --user pipx 2>/dev/null \
      || "$py" -m pip install --user --break-system-packages pipx
  fi

  have pipx || { err "Could not install pipx — see https://pipx.pypa.io/"; return 1; }
  ok "pipx installed"
}

ensure_path() {
  mkdir -p "$LOCAL_BIN"
  export PATH="$LOCAL_BIN:$PATH"
  pipx ensurepath >/dev/null 2>&1 || true

  local rc_line='export PATH="$HOME/.local/bin:$PATH"'
  local rc="${HOME}/.profile"
  case "${SHELL:-}" in
    */zsh) rc="${HOME}/.zshrc" ;;
    */bash) rc="${HOME}/.bashrc" ;;
  esac

  touch "$rc"
  if grep -Fq '.local/bin' "$rc" 2>/dev/null; then
    ok "PATH already includes ~/.local/bin ($rc)"
  else
    printf '\n# Added by Engineering Manager (em) installer\n%s\n' "$rc_line" >>"$rc"
    ok "Added ~/.local/bin to PATH in $rc"
    warn "Open a new terminal (or: source $rc) so em works everywhere"
  fi
}

install_em() {
  info "Installing em…"
  if pipx list 2>/dev/null | grep -qE '(^|[[:space:]])em([[:space:]]|$)'; then
    pipx install --force "$REPO_GIT"
  else
    pipx install "$REPO_GIT"
  fi
  ok "em package installed"
}

verify() {
  export PATH="$LOCAL_BIN:$PATH"
  if ! have em; then
    err "em not on PATH in this shell. Run:"
    err "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    return 1
  fi
  ok "em ready: $(command -v em)"
  echo ""
  em doctor || true
}

main() {
  info "${BOLD}Engineering Manager (em) installer${RESET}"
  info "https://github.com/enamulhaque028/ai-orchestration"
  echo ""

  if [[ "$(uname -s)" == "Darwin" ]]; then
    ensure_brew || warn "Continuing without Homebrew"
  fi
  ensure_python
  ensure_pipx
  ensure_path
  install_em
  verify
  setup_telegram_optional

  echo ""
  ok "Done. Try: em --help"
  info "Then open a new terminal, or: export PATH=\"\$HOME/.local/bin:\$PATH\""
}

setup_telegram_optional() {
  if [[ "${EM_SKIP_TELEGRAM:-}" == "1" ]]; then
    return 0
  fi
  if [[ ! -t 0 ]]; then
    info "Skipping Telegram setup (non-interactive). Later: em config telegram"
    return 0
  fi
  echo ""
  info "Telegram remote control (optional — each developer uses their own bot)"
  read -r -p "Set up Telegram now? [y/N] " ans || true
  case "${ans:-}" in
    y|Y|yes|YES)
      read -r -p "Bot token (from @BotFather): " token || true
      if [[ -z "${token:-}" ]]; then
        warn "No token entered — skip. Run later: em config telegram"
        return 0
      fi
      read -r -p "Your chat id (optional, can set later): " chat || true
      export PATH="$LOCAL_BIN:$PATH"
      if [[ -n "${chat:-}" ]]; then
        em config telegram --token "$token" --chat-id "$chat" || warn "em config telegram failed"
      else
        em config telegram --token "$token" || warn "em config telegram failed"
      fi
      ;;
    *)
      info "Skipped. Configure later with: em config telegram"
      ;;
  esac
}

main "$@"
