# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Extensible Telegram bot harness for remote command execution. Long-lived daemon that listens for Telegram messages and dispatches commands as async background tasks. Reports results back to the chat.

## Build & Run

```bash
./run.sh setup       # install deps, generate config
export TELEGRAM_BOT_TOKEN=your-token
./run.sh             # start the bot daemon
./run.sh commands    # list available commands
```

## Architecture

The bot (`bot.py`) receives Telegram messages, routes them to registered command handlers, executes them as async tasks, and replies with results. Long-running commands (review, ask, run) send a "working on it" message before starting.

**Key modules:**
- `bot.py` — Telegram bot daemon using python-telegram-bot. Handles auth, message routing, task tracking, reply formatting.
- `commands/__init__.py` — `BaseCommand` ABC and `CommandRegistry`. Extension point for new commands.
- `commands/review.py` — Invokes review-tool CLI as subprocess
- `commands/status.py` — System health: disk, tools availability, running tasks
- `commands/run.py` — Execute predefined shell commands from an allowlist in config
- `commands/ask.py` — Send questions to Claude Code CLI (`claude -p`)
- `config.py` — Pydantic config with `${ENV_VAR}` interpolation
- `models.py` — TaskResult, RunningTask, TaskStatus

**Adding a new command:** Subclass `BaseCommand`, implement `name`, `description`, `execute(args, config)`, call `CommandRegistry.register()`. The bot auto-discovers it.

## Security

- `allowed_chat_ids` / `allowed_user_ids` in config restrict who can use the bot
- `run_commands.allowed_commands` is an explicit allowlist — no arbitrary shell execution
- Bot token via env var, not committed to repo
