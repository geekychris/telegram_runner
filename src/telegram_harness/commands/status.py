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
        # The review-tool auto-starts code_graph_search per review on a dynamic port,
        # so it's normal for it not to be running between reviews.
        cgs_status = await _check_code_graph_search(config)
        lines.append(f"  {cgs_status}")

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


async def _check_code_graph_search(config: AppConfig) -> str:
    """Check code_graph_search status — jar existence, java, and any running instance."""
    import os
    from pathlib import Path

    # Check if review-tool config points to a JAR
    rt_args = config.review_tool.default_args
    rt_config_path = None
    for i, arg in enumerate(rt_args):
        if arg == "--config" and i + 1 < len(rt_args):
            rt_config_path = rt_args[i + 1]
            break

    jar_found = False
    auto_start = False
    if rt_config_path and Path(rt_config_path).exists():
        try:
            import json
            rt_cfg = json.loads(Path(rt_config_path).read_text())
            graph = rt_cfg.get("graph", {})
            jar_path = graph.get("jar_path", "")
            auto_start = graph.get("auto_start", False)
            if jar_path and Path(jar_path).exists():
                jar_found = True
        except Exception:
            pass

    if jar_found and auto_start:
        return "✅ code_graph_search (auto-start per review, JAR ready)"
    elif jar_found:
        return "✅ code_graph_search (JAR found, manual start)"
    elif auto_start:
        return "⚠️ code_graph_search (auto-start configured but JAR not found)"
    else:
        return "⬚ code_graph_search (not configured — set graph.jar_path in review-tool config)"


CommandRegistry.register(StatusCommand())
