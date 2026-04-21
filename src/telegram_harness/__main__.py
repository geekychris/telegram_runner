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


@app.command("setup")
def setup_wizard(
    path: str = typer.Option("telegram_harness.json", "--path", "-p"),
) -> None:
    """Interactive setup wizard — creates bot, generates config, verifies connection."""
    console.print("[bold]Telegram Harness Setup Wizard[/bold]\n")

    # Step 1: BotFather instructions
    console.print("[bold cyan]Step 1: Create a Telegram Bot[/bold cyan]")
    console.print(
        "  1. Open Telegram and search for [bold]@BotFather[/bold]\n"
        "  2. Send: /newbot\n"
        "  3. Choose a display name (e.g., 'My CI Bot')\n"
        "  4. Choose a username ending in 'bot' (e.g., 'my_ci_runner_bot')\n"
        "  5. BotFather will reply with an API token like:\n"
        "     [dim]123456789:ABCdefGHIjklMNOpqrSTUvwxYZ[/dim]\n"
    )

    token = typer.prompt("Paste your bot token (or press Enter to skip)", default="", show_default=False)
    token = token.strip()

    if not token:
        console.print("[yellow]Skipped. Set TELEGRAM_BOT_TOKEN later.[/yellow]\n")

    # Step 2: Get user ID for authorization
    console.print("[bold cyan]Step 2: Lock Down Access (Recommended)[/bold cyan]")
    console.print(
        "  To find your Telegram user ID:\n"
        "  1. Search for [bold]@userinfobot[/bold] on Telegram\n"
        "  2. Send it any message — it replies with your user ID\n"
        "  3. Or search for [bold]@getidsbot[/bold] as an alternative\n"
    )

    user_id_str = typer.prompt("Your Telegram user ID (or press Enter to allow all users)", default="", show_default=False)
    user_ids: list[int] = []
    if user_id_str.strip():
        try:
            user_ids = [int(uid.strip()) for uid in user_id_str.split(",")]
            console.print(f"  Will restrict to user IDs: {user_ids}\n")
        except ValueError:
            console.print("[yellow]  Invalid user ID, skipping restriction.[/yellow]\n")

    # Step 3: Configure review-tool path
    console.print("[bold cyan]Step 3: Configure review-tool Integration[/bold cyan]")
    import shutil
    review_tool_path = shutil.which("review-tool") or "review-tool"
    console.print(f"  Detected review-tool at: [cyan]{review_tool_path}[/cyan]")

    review_config_str = typer.prompt(
        "Path to review-tool config (or press Enter for default)",
        default="",
        show_default=False,
    )

    # Step 4: Generate config
    console.print("\n[bold cyan]Step 4: Generate Configuration[/bold cyan]")
    generate_default_config(path)

    # Patch with user-provided values
    import json
    config_data = json.loads(Path(path).read_text())

    if token:
        config_data["telegram"]["bot_token"] = token
    if user_ids:
        config_data["telegram"]["allowed_user_ids"] = user_ids
    if review_tool_path != "review-tool":
        config_data["review_tool"]["review_tool_path"] = review_tool_path
    if review_config_str.strip():
        config_data["review_tool"]["default_args"] = ["--config", review_config_str.strip()]

    Path(path).write_text(json.dumps(config_data, indent=2) + "\n")
    console.print(f"  Config saved to [green]{path}[/green]\n")

    # Step 5: Verify bot token
    if token:
        console.print("[bold cyan]Step 5: Verify Bot Connection[/bold cyan]")
        try:
            import httpx
            r = httpx.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            if r.status_code == 200:
                bot_info = r.json().get("result", {})
                bot_name = bot_info.get("username", "unknown")
                console.print(f"  [green]Connected to bot: @{bot_name}[/green]")
                console.print(f"  Bot ID: {bot_info.get('id', '?')}")
            else:
                console.print(f"  [red]Token verification failed: {r.json().get('description', r.status_code)}[/red]")
                console.print("  Check the token and try again.\n")
        except Exception as e:
            console.print(f"  [yellow]Could not verify: {e}[/yellow]")
    else:
        console.print("[bold cyan]Step 5: Skipped (no token provided)[/bold cyan]")

    # Step 6: Summary
    console.print("\n[bold cyan]Setup Complete![/bold cyan]")
    console.print(
        f"\n  Config file: {path}\n"
    )
    if not token:
        console.print(
            "  [yellow]Don't forget to set the bot token:[/yellow]\n"
            "    export TELEGRAM_BOT_TOKEN=your-token\n"
            f"    Or edit {path} and set telegram.bot_token\n"
        )
    console.print(
        "  Start the bot:\n"
        "    ./run.sh\n"
        "\n"
        "  Then message your bot on Telegram:\n"
        "    /help               — see all commands\n"
        "    /status             — check system health\n"
        "    /review <pr-url>    — review a GitHub PR\n"
        "    /ask <question>     — ask Claude a question\n"
        "    /run list           — see available run commands\n"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
