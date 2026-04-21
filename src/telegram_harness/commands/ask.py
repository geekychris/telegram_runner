"""Ask command — send a question to Claude about the codebase."""

from __future__ import annotations

import asyncio
import json
import logging
import time

from telegram_harness.commands import BaseCommand, CommandRegistry
from telegram_harness.config import AppConfig
from telegram_harness.models import TaskResult, TaskStatus

log = logging.getLogger(__name__)


class AskCommand(BaseCommand):
    @property
    def name(self) -> str:
        return "ask"

    @property
    def description(self) -> str:
        return "Ask Claude a question about a codebase or topic"

    @property
    def usage(self) -> str:
        return "/ask <question>"

    @property
    def is_long_running(self) -> bool:
        return True

    def validate_args(self, args: str) -> str | None:
        if not args.strip():
            return "Please provide a question.\nUsage: /ask What does the auth middleware do?"
        return None

    async def execute(self, args: str, config: AppConfig) -> TaskResult:
        if not config.claude.enabled:
            return TaskResult(
                status=TaskStatus.FAILED,
                message="Claude integration is disabled in configuration.",
            )

        question = args.strip()

        cmd = [
            "claude",
            "-p",
            question,
            "--output-format", "json",
            "--model", config.claude.model,
            "--max-budget-usd", str(config.claude.max_budget_usd),
        ]

        log.info("Asking Claude: %s", question[:100])
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            elapsed = time.monotonic() - start

            if proc.returncode != 0:
                error = stderr.decode()[:500] if stderr else "unknown error"
                return TaskResult(
                    status=TaskStatus.FAILED,
                    message=f"Claude failed: {error}",
                    duration_seconds=elapsed,
                )

            # Parse response
            raw = stdout.decode()
            try:
                data = json.loads(raw)
                if isinstance(data, list):
                    # Streaming format — extract text from events
                    texts = []
                    for event in data:
                        if isinstance(event, dict):
                            if "result" in event:
                                texts.append(str(event["result"]))
                            elif event.get("type") == "result":
                                texts.append(str(event.get("result", "")))
                    answer = "\n".join(texts) if texts else raw
                else:
                    answer = data.get("result", raw)
            except json.JSONDecodeError:
                answer = raw

            return TaskResult(
                status=TaskStatus.COMPLETED,
                message=_truncate(answer, 4000),
                duration_seconds=elapsed,
            )

        except asyncio.TimeoutError:
            return TaskResult(
                status=TaskStatus.FAILED,
                message="Claude timed out after 2 minutes.",
                duration_seconds=time.monotonic() - start,
            )
        except Exception as e:
            return TaskResult(
                status=TaskStatus.FAILED,
                message=f"Claude failed: {e}",
            )


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... (truncated)"


CommandRegistry.register(AskCommand())
