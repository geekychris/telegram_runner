"""CLI entry point for telegram-harness."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from telegram_harness.config import AppConfig, generate_default_config, load_config

app = typer.Typer(
    name="telegram-harness",
    help="Extensible Telegram bot for remote command execution",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbosity: int) -> None:
    level = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}.get(
        verbosity, logging.DEBUG
    )
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def start(
    config_path: Optional[str] = typer.Option(
        None, "--config", "-c", help="Path to config JSON"
    ),
    verbosity: int = typer.Option(1, "--verbosity", "-v", help="0=quiet, 1=info, 2=debug"),
) -> None:
    """Start the Telegram bot daemon."""
    _setup_logging(verbosity)

    config = load_config(config_path)
    token = config.telegram.resolved_token()
    if not token:
        console.print(
            "[red]TELEGRAM_BOT_TOKEN not set.[/red]\n"
            "1. Talk to @BotFather on Telegram to create a bot\n"
            "2. Set the token: export TELEGRAM_BOT_TOKEN=your-token\n"
            "   Or add it to your config file"
        )
        raise SystemExit(1)

    console.print("[bold]Starting Telegram Harness bot...[/bold]")

    # Import here to trigger command registration
    from telegram_harness.commands import CommandRegistry
    console.print(f"Commands: {', '.join(sorted(CommandRegistry.all_commands()))}")

    from telegram_harness.bot import run_bot
    asyncio.run(run_bot(config))


@app.command("commands")
def list_commands() -> None:
    """List available bot commands."""
    from telegram_harness.commands import CommandRegistry

    table = Table(title="Bot Commands")
    table.add_column("Command", style="cyan")
    table.add_column("Long-running", style="yellow")
    table.add_column("Description")

    for name, cmd in sorted(CommandRegistry.all_commands().items()):
        table.add_row(f"/{name}", "yes" if cmd.is_long_running else "no", cmd.description)

    # Built-in commands
    table.add_row("/help", "no", "Show available commands")
    table.add_row("/tasks", "no", "Show running tasks")

    console.print(table)


@app.command("config")
def config_cmd(
    action: str = typer.Argument(help="'init' to generate default config, 'check' to validate"),
    path: str = typer.Option("telegram_harness.json", "--path", "-p"),
) -> None:
    """Manage configuration (init or check)."""
    if action == "init":
        out = generate_default_config(path)
        console.print(f"[green]Config written to {out}[/green]")
    elif action == "check":
        try:
            config = load_config(path)
            console.print("[green]Configuration is valid[/green]")
            console.print(f"  Bot token: {'set' if config.telegram.resolved_token() else 'NOT SET'}")
            console.print(f"  Allowed chats: {config.telegram.allowed_chat_ids or 'all'}")
            console.print(f"  Allowed users: {config.telegram.allowed_user_ids or 'all'}")
            console.print(f"  Review tool: {'enabled' if config.review_tool.enabled else 'disabled'}")
            console.print(f"  Claude: {'enabled' if config.claude.enabled else 'disabled'}")
            console.print(f"  Run commands: {len(config.run_commands.allowed_commands)} configured")
        except Exception as e:
            console.print(f"[red]Config error: {e}[/red]")
            raise SystemExit(1)
    else:
        console.print(f"[red]Unknown action: {action}. Use 'init' or 'check'.[/red]")
        raise SystemExit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
