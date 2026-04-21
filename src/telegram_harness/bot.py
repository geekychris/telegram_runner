"""Telegram bot daemon — receives messages, dispatches commands, replies with results.

Long-running commands execute as background asyncio tasks so the bot
stays responsive to /tasks, /cancel, /status, and other commands while
a review or shell command is running.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import uuid
from datetime import datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from telegram_harness.commands import BaseCommand, CommandRegistry
from telegram_harness.config import AppConfig
from telegram_harness.models import RunningTask, TaskResult, TaskStatus

log = logging.getLogger(__name__)

# Global task tracker — visible to /tasks and /cancel
_running_tasks: dict[str, RunningTask] = {}
# Completed tasks kept briefly so /tasks can show recent results
_recent_tasks: list[RunningTask] = []
_MAX_RECENT = 10


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


async def _send_reply(update_or_bot, text: str, chat_id: int | None = None, parse_mode: str | None = None) -> None:
    """Send a reply, splitting into chunks if too long for Telegram.

    Accepts either an Update (for direct replies) or a Bot instance + chat_id
    (for background task notifications).
    """
    max_len = 4096

    if hasattr(update_or_bot, "message"):
        # It's an Update
        send = update_or_bot.message.reply_text
    else:
        # It's a Bot instance — need chat_id
        async def send(text, **kwargs):
            await update_or_bot.send_message(chat_id=chat_id, text=text, **kwargs)

    if len(text) <= max_len:
        await send(text, parse_mode=parse_mode)
        return

    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]
    for chunk in chunks:
        await send(chunk, parse_mode=parse_mode)


async def _run_background_task(
    command: BaseCommand,
    args: str,
    task: RunningTask,
    config: AppConfig,
    bot,
) -> None:
    """Execute a command in the background and send the result when done."""
    try:
        result = await command.execute(args, config, task=task)
        task.status = result.status
        task.result = result
    except asyncio.CancelledError:
        # Kill the subprocess if it's still running
        if task.subprocess and task.subprocess.returncode is None:
            try:
                task.subprocess.terminate()
                await asyncio.sleep(1)
                if task.subprocess.returncode is None:
                    task.subprocess.kill()
            except ProcessLookupError:
                pass
        result = TaskResult(
            status=TaskStatus.CANCELLED,
            message="Task was cancelled.",
            duration_seconds=task.elapsed_seconds,
        )
        task.status = TaskStatus.CANCELLED
        task.result = result
    except Exception as e:
        log.exception("Background command /%s failed", command.name)
        result = TaskResult(
            status=TaskStatus.FAILED,
            message=f"Internal error: {e}",
        )
        task.status = TaskStatus.FAILED
        task.result = result
    finally:
        # Move from running to recent
        _running_tasks.pop(task.task_id, None)
        _recent_tasks.insert(0, task)
        while len(_recent_tasks) > _MAX_RECENT:
            _recent_tasks.pop()

    # Send the result back to the chat
    icons = {
        TaskStatus.COMPLETED: "✅",
        TaskStatus.FAILED: "❌",
        TaskStatus.CANCELLED: "🚫",
    }
    icon = icons.get(result.status, "❓")
    reply = f"{icon} **/{command.name}**"
    if result.duration_seconds > 0:
        reply += f" ({result.duration_seconds:.1f}s)"
    reply += f"\n\n{result.message}"

    await _send_reply(bot, reply, chat_id=task.chat_id)

    if result.detail:
        detail_msg = f"```\n{result.detail[:3900]}\n```"
        try:
            await _send_reply(bot, detail_msg, chat_id=task.chat_id, parse_mode=ParseMode.MARKDOWN_V2)
        except Exception:
            # MarkdownV2 can be finicky — fall back to plain text
            await _send_reply(bot, result.detail[:3900], chat_id=task.chat_id)

    if result.url:
        await bot.send_message(chat_id=task.chat_id, text=f"🔗 {result.url}")


async def _handle_command(
    command: BaseCommand,
    args: str,
    update: Update,
    config: AppConfig,
) -> None:
    """Execute a command — inline for fast commands, background for long-running ones."""
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

    # Create task entry
    task_id = str(uuid.uuid4())[:8]
    task = RunningTask(
        task_id=task_id,
        command_name=command.name,
        args=args,
        chat_id=chat_id,
        user_id=user.id if user else 0,
        username=username,
    )

    if command.is_long_running:
        # Dispatch as background task — bot stays responsive
        _running_tasks[task_id] = task
        await update.message.reply_text(
            f"⏳ Started `/{command.name}` (task `{task_id}`)\n"
            f"Use /tasks to check progress, /cancel {task_id} to stop."
        )
        bot = update.get_bot()
        asyncio_task = asyncio.create_task(
            _run_background_task(command, args, task, config, bot)
        )
        task.asyncio_task = asyncio_task
        log.info("Dispatched background task %s for /%s", task_id, command.name)
    else:
        # Run inline — fast commands like /status, /help
        try:
            result = await command.execute(args, config, task=task)
        except Exception as e:
            log.exception("Command /%s failed", command.name)
            result = TaskResult(status=TaskStatus.FAILED, message=f"Internal error: {e}")

        icon = "✅" if result.status == TaskStatus.COMPLETED else "❌"
        reply = f"{icon} **/{command.name}**\n\n{result.message}"
        await _send_reply(update, reply)

        if result.detail:
            detail_msg = f"```\n{result.detail[:3900]}\n```"
            try:
                await _send_reply(update, detail_msg, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception:
                await _send_reply(update, result.detail[:3900])


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
    lines.append(f"  /tasks — Show running and recent tasks")
    lines.append(f"  /cancel <id> — Cancel a running task")
    await update.message.reply_text("\n".join(lines))


async def _tasks_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show running and recently completed tasks."""
    lines = []

    if _running_tasks:
        lines.append("**Running Tasks:**\n")
        for tid, task in _running_tasks.items():
            elapsed = task.elapsed_seconds
            lines.append(
                f"  🔄 `{tid}` /{task.command_name} — {task.args[:50]} "
                f"({elapsed:.0f}s, by {task.username})"
            )
    else:
        lines.append("No tasks currently running.\n")

    if _recent_tasks:
        lines.append("\n**Recent Tasks:**\n")
        for task in _recent_tasks[:5]:
            icons = {
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.CANCELLED: "🚫",
            }
            icon = icons.get(task.status, "❓")
            duration = task.result.duration_seconds if task.result else 0
            lines.append(
                f"  {icon} `{task.task_id}` /{task.command_name} — "
                f"{task.args[:40]} ({duration:.0f}s)"
            )

    await update.message.reply_text("\n".join(lines))


async def _cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel a running task by ID."""
    if not context.args:
        if not _running_tasks:
            await update.message.reply_text("No tasks running.")
            return
        # If only one task, cancel it
        if len(_running_tasks) == 1:
            task_id = next(iter(_running_tasks))
        else:
            task_ids = ", ".join(f"`{tid}`" for tid in _running_tasks)
            await update.message.reply_text(
                f"Which task? Running: {task_ids}\nUsage: /cancel <task-id>"
            )
            return
    else:
        task_id = context.args[0]

    task = _running_tasks.get(task_id)
    if not task:
        await update.message.reply_text(f"Task `{task_id}` not found or already finished.")
        return

    log.info("Cancelling task %s (/%s) by user request", task_id, task.command_name)

    # Cancel the asyncio task — this triggers CancelledError in _run_background_task
    if task.asyncio_task and not task.asyncio_task.done():
        task.asyncio_task.cancel()
        await update.message.reply_text(f"🚫 Cancelling task `{task_id}` (/{task.command_name})...")
    else:
        await update.message.reply_text(f"Task `{task_id}` is already finishing.")


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
    app.add_handler(CommandHandler("cancel", _cancel_handler))

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
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down bot...")
    finally:
        # Cancel all running tasks
        for tid, task in list(_running_tasks.items()):
            if task.asyncio_task and not task.asyncio_task.done():
                task.asyncio_task.cancel()
                log.info("Cancelled task %s on shutdown", tid)

        await app.updater.stop()
        await app.stop()
        await app.shutdown()
