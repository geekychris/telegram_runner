#!/usr/bin/env bash
# run.sh — Start the Telegram harness bot
#
# Usage:
#   ./run.sh              # start the bot
#   ./run.sh setup        # first-time setup
#   ./run.sh commands     # list available commands
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CONFIG_FILE="$SCRIPT_DIR/telegram_harness.json"

GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log()  { echo -e "${GREEN}[harness]${NC} $*"; }
warn() { echo -e "${YELLOW}[harness]${NC} $*"; }
err()  { echo -e "${RED}[harness]${NC} $*" >&2; }

do_setup() {
    log "Setting up telegram-harness..."

    local missing=()
    command -v python3 >/dev/null || missing+=("python3")

    if [[ ${#missing[@]} -gt 0 ]]; then
        err "Missing: ${missing[*]}"
        exit 1
    fi

    if [[ ! -d "$VENV_DIR" ]]; then
        log "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi

    log "Installing telegram-harness..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -e "$SCRIPT_DIR"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        log "Generating default config at $CONFIG_FILE"
        "$VENV_DIR/bin/telegram-harness" config init --path "$CONFIG_FILE"
    fi

    log ""
    log "Setup complete!"
    log ""
    log "Next steps:"
    log "  1. Talk to @BotFather on Telegram to create a bot"
    log "  2. Set the token: export TELEGRAM_BOT_TOKEN=your-token"
    log "     Or edit $CONFIG_FILE and set telegram.bot_token"
    log "  3. (Optional) Set allowed_chat_ids / allowed_user_ids for security"
    log "  4. Run: ./run.sh"
}

if [[ $# -gt 0 && "$1" == "setup" ]]; then
    do_setup
    exit 0
fi

if [[ $# -gt 0 && "$1" == "commands" ]]; then
    [[ ! -d "$VENV_DIR" ]] && do_setup
    exec "$VENV_DIR/bin/telegram-harness" commands
fi

# Auto-setup
if [[ ! -d "$VENV_DIR" ]]; then
    warn "First run, setting up..."
    do_setup
    echo ""
fi

# Check token
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    if [[ -f "$CONFIG_FILE" ]]; then
        # Check if token is set in config (not just the env placeholder)
        token_val=$(python3 -c "
import json
c = json.load(open('$CONFIG_FILE'))
t = c.get('telegram', {}).get('bot_token', '')
print('set' if t and not t.startswith('\${') else 'unset')
" 2>/dev/null || echo "unset")
        if [[ "$token_val" == "unset" ]]; then
            err "TELEGRAM_BOT_TOKEN not set."
            err "  export TELEGRAM_BOT_TOKEN=your-token"
            err "  Or edit $CONFIG_FILE"
            exit 1
        fi
    else
        err "TELEGRAM_BOT_TOKEN not set."
        exit 1
    fi
fi

CONFIG_ARGS=()
if [[ -f "$CONFIG_FILE" ]]; then
    CONFIG_ARGS=(--config "$CONFIG_FILE")
fi

exec "$VENV_DIR/bin/telegram-harness" start "${CONFIG_ARGS[@]}" "$@"
