"""Status command — check health of services and system."""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import time

from telegram_harness.commands import BaseCommand, CommandRegistry
from telegram_harness.config import AppConfig
from telegram_harness.models import RunningTask, TaskResult, TaskStatus

log = logging.getLogger(__name__)


class StatusCommand(BaseCommand):
    @property
    def name(self) -> str:
        return "status"

    @property
    def description(self) -> str:
        return "Check health of services and system info"

    @property
    def usage(self) -> str:
        return "/status"

    async def execute(self, args: str, config: AppConfig, task: RunningTask | None = None) -> TaskResult:
        lines = ["**System Status**\n"]

        # System info
        lines.append(f"Host: `{platform.node()}`")
        lines.append(f"Platform: `{platform.system()} {platform.release()}`")
        lines.append(f"Python: `{platform.python_version()}`")

        # Disk
        total, used, free = shutil.disk_usage("/")
        lines.append(f"Disk: {free // (1 << 30)}GB free / {total // (1 << 30)}GB total")

        # Check tools
        lines.append("\n**Tools:**")
        for tool, check_cmd in [
            ("review-tool", ["review-tool", "--help"]),
            ("gh CLI", ["gh", "--version"]),
            ("claude CLI", ["claude", "--version"]),
            ("java", ["java", "--version"]),
        ]:
            available = await _check_tool(check_cmd)
            icon = "✅" if available else "❌"
            lines.append(f"  {icon} {tool}")

        # Check code_graph_search
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get("http://localhost:8080/api/health")
                if r.status_code == 200:
                    lines.append("  ✅ code_graph_search (port 8080)")
                else:
                    lines.append("  ⬚ code_graph_search (not running)")
        except Exception:
            lines.append("  ⬚ code_graph_search (not running)")

        # Running tasks (from the bot's task tracker)
        if args.strip() == "tasks":
            lines.append("\n_Use /tasks to see running tasks_")

        return TaskResult(
            status=TaskStatus.COMPLETED,
            message="\n".join(lines),
        )


async def _check_tool(cmd: list[str]) -> bool:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)
        return proc.returncode == 0
    except Exception:
        return False


CommandRegistry.register(StatusCommand())
