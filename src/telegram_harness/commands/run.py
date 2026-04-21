"""Run command — execute predefined shell commands."""

from __future__ import annotations

import asyncio
import logging
import time

from telegram_harness.commands import BaseCommand, CommandRegistry
from telegram_harness.config import AppConfig
from telegram_harness.models import RunningTask, TaskResult, TaskStatus

log = logging.getLogger(__name__)


class RunCommand(BaseCommand):
    @property
    def name(self) -> str:
        return "run"

    @property
    def description(self) -> str:
        return "Execute a predefined command (see /run list)"

    @property
    def usage(self) -> str:
        return "/run <command-name> [args...]\n/run list — show available commands"

    @property
    def is_long_running(self) -> bool:
        return True

    def validate_args(self, args: str) -> str | None:
        if not args.strip():
            return "Please specify a command.\nUsage: /run <command-name>\nUse /run list to see available commands."
        return None

    async def execute(self, args: str, config: AppConfig, task: RunningTask | None = None) -> TaskResult:
        if not config.run_commands.enabled:
            return TaskResult(
                status=TaskStatus.FAILED,
                message="Run commands are disabled in configuration.",
            )

        parts = args.strip().split(None, 1)
        cmd_name = parts[0]
        cmd_args = parts[1] if len(parts) > 1 else ""

        # List available commands
        if cmd_name == "list":
            if not config.run_commands.allowed_commands:
                return TaskResult(
                    status=TaskStatus.COMPLETED,
                    message="No commands configured. Add them to `run_commands.allowed_commands` in config.",
                )
            lines = ["**Available Commands:**\n"]
            for name, template in config.run_commands.allowed_commands.items():
                lines.append(f"  `{name}` → `{template}`")
            return TaskResult(
                status=TaskStatus.COMPLETED,
                message="\n".join(lines),
            )

        # Look up the command
        template = config.run_commands.allowed_commands.get(cmd_name)
        if not template:
            available = ", ".join(config.run_commands.allowed_commands.keys())
            return TaskResult(
                status=TaskStatus.FAILED,
                message=f"Unknown command: `{cmd_name}`\nAvailable: {available or '(none)'}",
            )

        # Substitute args into template if it contains {args}
        if "{args}" in template:
            shell_cmd = template.replace("{args}", cmd_args)
        elif cmd_args:
            shell_cmd = f"{template} {cmd_args}"
        else:
            shell_cmd = template

        log.info("Executing run command '%s': %s", cmd_name, shell_cmd)
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            if task:
                task.subprocess = proc
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=300)
            output = stdout.decode() if stdout else ""
            elapsed = time.monotonic() - start

            if proc.returncode == 0:
                return TaskResult(
                    status=TaskStatus.COMPLETED,
                    message=f"`{cmd_name}` completed successfully ({elapsed:.1f}s)",
                    detail=_truncate(output, 3000),
                    duration_seconds=elapsed,
                )
            else:
                return TaskResult(
                    status=TaskStatus.FAILED,
                    message=f"`{cmd_name}` failed (exit {proc.returncode}, {elapsed:.1f}s)",
                    detail=_truncate(output, 3000),
                    duration_seconds=elapsed,
                )

        except asyncio.TimeoutError:
            return TaskResult(
                status=TaskStatus.FAILED,
                message=f"`{cmd_name}` timed out after 5 minutes.",
                duration_seconds=time.monotonic() - start,
            )
        except Exception as e:
            return TaskResult(
                status=TaskStatus.FAILED,
                message=f"`{cmd_name}` failed: {e}",
            )


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... (truncated)"


CommandRegistry.register(RunCommand())
