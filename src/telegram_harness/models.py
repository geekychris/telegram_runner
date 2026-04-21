"""Data models for the command framework."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    """Result of a command execution."""

    status: TaskStatus
    message: str  # short summary for Telegram reply
    detail: str = ""  # full output (may be truncated for Telegram)
    duration_seconds: float = 0.0
    url: str = ""  # optional link (e.g., PR URL, deploy URL)


@dataclass
class RunningTask:
    """A background task currently executing."""

    task_id: str
    command_name: str
    args: str
    chat_id: int
    user_id: int
    username: str
    started_at: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.RUNNING
    result: TaskResult | None = None
    # asyncio handles for cancellation
    asyncio_task: asyncio.Task | None = field(default=None, repr=False)
    subprocess: asyncio.subprocess.Process | None = field(default=None, repr=False)

    @property
    def elapsed_seconds(self) -> float:
        return (datetime.now() - self.started_at).total_seconds()
