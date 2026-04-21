"""Extensible command framework.

To add a new command:
1. Subclass BaseCommand
2. Implement name, description, usage, and execute()
3. Call CommandRegistry.register(YourCommand())
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from telegram_harness.config import AppConfig
from telegram_harness.models import TaskResult

log = logging.getLogger(__name__)


class BaseCommand(ABC):
    """Abstract base for all bot commands."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Command name (e.g., 'review'). Used as /review in Telegram."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description shown in /help."""
        ...

    @property
    def usage(self) -> str:
        """Usage string shown when args are wrong."""
        return f"/{self.name}"

    @abstractmethod
    async def execute(self, args: str, config: AppConfig) -> TaskResult:
        """Execute the command with the given arguments.

        Args:
            args: Everything after the command name.
            config: Application configuration.

        Returns:
            TaskResult with status, message, and optional detail/url.
        """
        ...

    def validate_args(self, args: str) -> str | None:
        """Validate arguments. Return error message or None if valid."""
        return None

    @property
    def is_long_running(self) -> bool:
        """If True, the bot sends a 'working on it' message before executing."""
        return False


class CommandRegistry:
    """Central registry for bot commands."""

    _commands: dict[str, BaseCommand] = {}

    @classmethod
    def register(cls, command: BaseCommand) -> None:
        cls._commands[command.name] = command
        log.debug("Registered command: /%s", command.name)

    @classmethod
    def get(cls, name: str) -> BaseCommand | None:
        return cls._commands.get(name)

    @classmethod
    def all_commands(cls) -> dict[str, BaseCommand]:
        return dict(cls._commands)


# Import built-in commands to auto-register
from telegram_harness.commands import ask as _ask  # noqa: F401, E402
from telegram_harness.commands import review as _review  # noqa: F401, E402
from telegram_harness.commands import run as _run  # noqa: F401, E402
from telegram_harness.commands import status as _status  # noqa: F401, E402
