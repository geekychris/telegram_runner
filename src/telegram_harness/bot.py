"""Telegram bot daemon — receives messages, dispatches commands, replies with results."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from telegram_harness.commands import BaseCommand, CommandRegistry
from telegram_harness.config import AppConfig
from telegram_harness.models import RunningTask, TaskResult, TaskStatus

log = logging.getLogger(__name__)

# Track running tasks so /tasks can report them
_running_tasks: dict[str, RunningTask] = {}


def _is_authorized(update: Update, config: AppConfig) -> bool:
    """Check if the user/chat is authorized to use the bot."""
    chat_id = update.effective_chat.id if update.effective_chat else 0
    user_id = update.effective_user.id if update.effective_user else 0

    if config.telegram.allowed_chat_ids and chat_id not in config.telegram.allowed_chat_ids:
        log.warning("Unauthorized chat_id: %d", chat_id)
        return False

    if config.telegram.allowed_user_ids and user_id not in config.telegram.allowed_user_ids:
        log.warning("Unauthorized user_id: %d (chat: %d)", user_id, chat_id)
        return False

    return True


def _escape_markdown(text: str) -> str:
    """Minimal escape for Telegram MarkdownV2 — only escape in non-code contexts."""
    # For simplicity, send as plain text or HTML instead of MarkdownV2
    return text


async def _send_reply(update: Update, text: str, parse_mode: str | None = None) -> None:
    """Send a reply, splitting into chunks if too long for Telegram."""
    max_len = 4096
    if len(text) <= max_len:
        await update.message.reply_text(text, parse_mode=parse_mode)
        return

    # Split into chunks
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode=parse_mode)


async def _handle_command(
    command: BaseCommand,
    args: str,
    update: Update,
    config: AppConfig,
) -> None:
    """Execute a command and reply with the result."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    username = user.username or user.first_name if user else "unknown"

    log.info(
        "Command /%s from %s (chat=%d): %s",
        command.name,
        username,
        chat_id,
        args[:100],
    )

    # Validate
    error = command.validate_args(args)
    if error:
        await update.message.reply_text(f"❌ {error}")
        return

    # For long-running commands, send a "working on it" message
    if command.is_long_running:
        await update.message.reply_text(f"⏳ Working on `/{command.name}`...\nThis may take a few minutes.")

    # Track the task
    task_id = str(uuid.uuid4())[:8]
    task = RunningTask(
        task_id=task_id,
        command_name=command.name,
        args=args,
        chat_id=chat_id,
        user_id=user.id if user else 0,
        username=username,
    )
    _running_tasks[task_id] = task

    try:
        result = await command.execute(args, config)
        task.status = result.status
        task.result = result
    except Exception as e:
        log.exception("Command /%s failed", command.name)
        result = TaskResult(
            status=TaskStatus.FAILED,
            message=f"Internal error: {e}",
        )
        task.status = TaskStatus.FAILED
        task.result = result
    finally:
        # Remove from running tasks (keep for a bit for /tasks)
        _running_tasks.pop(task_id, None)

    # Format and send the reply
    icon = "✅" if result.status == TaskStatus.COMPLETED else "❌"
    reply = f"{icon} **/{command.name}**"
    if result.duration_seconds > 0:
        reply += f" ({result.duration_seconds:.1f}s)"
    reply += f"\n\n{result.message}"

    if result.detail:
        # Send detail as a separate message in a code block
        await _send_reply(update, reply)
        detail_msg = f"```\n{result.detail[:3900]}\n```"
        await _send_reply(update, detail_msg, parse_mode=ParseMode.MARKDOWN_V2)
    else:
        await _send_reply(update, reply)

    if result.url:
        await update.message.reply_text(f"🔗 {result.url}")


def _make_command_handler(command: BaseCommand, config: AppConfig):
    """Create a telegram CommandHandler for a BaseCommand."""

    async def handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _is_authorized(update, config):
            await update.message.reply_text("⛔ You are not authorized to use this bot.")
            return
        args = " ".join(context.args) if context.args else ""
        await _handle_command(command, args, update, config)

    return handler


async def _help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show available commands."""
    lines = ["**Telegram Harness** — Remote command runner\n"]
    lines.append("Available commands:\n")
    for name, cmd in sorted(CommandRegistry.all_commands().items()):
        lines.append(f"  /{name} — {cmd.description}")
    lines.append(f"\n  /help — Show this message")
    lines.append(f"  /tasks — Show running tasks")
    await update.message.reply_text("\n".join(lines))


async def _tasks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show currently running tasks."""
    if not _running_tasks:
        await update.message.reply_text("No tasks currently running.")
        return

    lines = ["**Running Tasks:**\n"]
    for tid, task in _running_tasks.items():
        elapsed = (datetime.now() - task.started_at).total_seconds()
        lines.append(
            f"  `{tid}` /{task.command_name} — {task.args[:50]} ({elapsed:.0f}s, by {task.username})"
        )
    await update.message.reply_text("\n".join(lines))


async def _unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands."""
    await update.message.reply_text(
        "Unknown command. Use /help to see available commands."
    )


def build_application(config: AppConfig) -> Application:
    """Build the Telegram bot application with all registered commands."""
    token = config.telegram.resolved_token()
    if not token:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN not set. "
            "Create a bot via @BotFather and set the token in config or TELEGRAM_BOT_TOKEN env var."
        )

    app = Application.builder().token(token).build()

    # Register built-in handlers
    app.add_handler(CommandHandler("help", _help_handler))
    app.add_handler(CommandHandler("tasks", _tasks_handler))

    # Register all command handlers
    for name, command in CommandRegistry.all_commands().items():
        handler = _make_command_handler(command, config)
        app.add_handler(CommandHandler(name, handler))
        log.info("Registered Telegram handler: /%s", name)

    # Catch unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, _unknown_handler))

    return app


async def run_bot(config: AppConfig) -> None:
    """Start the bot and run until interrupted."""
    app = build_application(config)
    log.info("Starting Telegram bot...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    log.info("Bot is running. Press Ctrl+C to stop.")
    try:
        # Run forever
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down bot...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
