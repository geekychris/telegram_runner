"""Review command — runs review-tool against a GitHub PR."""

from __future__ import annotations

import asyncio
import logging
import re
import time

from telegram_harness.commands import BaseCommand, CommandRegistry
from telegram_harness.config import AppConfig
from telegram_harness.models import RunningTask, TaskResult, TaskStatus

log = logging.getLogger(__name__)

PR_URL_PATTERN = re.compile(r"https?://github\.com/[^/]+/[^/]+/pull/\d+")


class ReviewCommand(BaseCommand):
    @property
    def name(self) -> str:
        return "review"

    @property
    def description(self) -> str:
        return "Run AI code review on a GitHub PR"

    @property
    def usage(self) -> str:
        return "/review <pr-url> [--skills defects,security] [--dry-run] [-v 0|1|2]"

    @property
    def is_long_running(self) -> bool:
        return True

    def validate_args(self, args: str) -> str | None:
        if not args.strip():
            return "Please provide a PR URL.\nUsage: /review https://github.com/owner/repo/pull/123"
        if not PR_URL_PATTERN.search(args):
            return f"No valid GitHub PR URL found in: {args}"
        return None

    async def execute(
        self,
        args: str,
        config: AppConfig,
        task: RunningTask | None = None,
    ) -> TaskResult:
        if not config.review_tool.enabled:
            return TaskResult(
                status=TaskStatus.FAILED,
                message="Review tool is disabled in configuration.",
            )

        # Extract PR URL and any extra flags
        m = PR_URL_PATTERN.search(args)
        pr_url = m.group(0) if m else ""
        extra_args = args.replace(pr_url, "").strip()

        # Build the command
        cmd = [config.review_tool.review_tool_path, "review", pr_url]
        cmd.extend(config.review_tool.default_args)
        if extra_args:
            cmd.extend(extra_args.split())

        log.info("Executing review: %s", " ".join(cmd))
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            # Register subprocess so /cancel can kill it
            if task:
                task.subprocess = proc

            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=900)
            output = stdout.decode() if stdout else ""
            elapsed = time.monotonic() - start

            if proc.returncode == 0:
                return TaskResult(
                    status=TaskStatus.COMPLETED,
                    message=f"Review posted to {pr_url}",
                    detail=_truncate(output, 3000),
                    duration_seconds=elapsed,
                    url=pr_url,
                )
            elif proc.returncode == 1:
                # Exit code 1 = review posted but has critical/high findings
                return TaskResult(
                    status=TaskStatus.COMPLETED,
                    message=f"Review posted (has critical/high findings): {pr_url}",
                    detail=_truncate(output, 3000),
                    duration_seconds=elapsed,
                    url=pr_url,
                )
            else:
                return TaskResult(
                    status=TaskStatus.FAILED,
                    message=f"Review failed (exit {proc.returncode})",
                    detail=_truncate(output, 3000),
                    duration_seconds=elapsed,
                    url=pr_url,
                )

        except asyncio.TimeoutError:
            return TaskResult(
                status=TaskStatus.FAILED,
                message="Review timed out after 15 minutes.",
                duration_seconds=time.monotonic() - start,
                url=pr_url,
            )
        except Exception as e:
            return TaskResult(
                status=TaskStatus.FAILED,
                message=f"Review failed: {e}",
                duration_seconds=time.monotonic() - start,
            )


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n... (truncated)"


CommandRegistry.register(ReviewCommand())
