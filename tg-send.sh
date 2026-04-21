#!/usr/bin/env bash
# tg-send.sh — Send a message to Telegram from any script
#
# Usage:
#   ./tg-send.sh "Deploy complete"
#   echo "Build failed" | ./tg-send.sh -
#   ./tg-send.sh -t 123456789 "Alert: disk at 95%"
#   make test && ./tg-send.sh "Tests passed" || ./tg-send.sh "Tests FAILED"
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
    echo "Run ./run.sh setup first" >&2
    exit 1
fi

exec "$VENV_DIR/bin/tg-send" "$@"
