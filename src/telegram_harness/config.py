"""Configuration models and loader."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import BaseModel


def _interpolate_env(value: str) -> str:
    """Replace ${ENV_VAR} patterns with environment variable values."""
    def _replace(match: re.Match) -> str:
        var = match.group(1)
        if ":-" in var:
            var_name, default = var.split(":-", 1)
            return os.environ.get(var_name, default)
        return os.environ.get(var, "")
    return re.sub(r"\$\{([^}]+)}", _replace, value)


def _interpolate_recursive(obj: object) -> object:
    if isinstance(obj, str):
        return _interpolate_env(obj)
    if isinstance(obj, dict):
        return {k: _interpolate_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_recursive(v) for v in obj]
    return obj


class TelegramConfig(BaseModel):
    bot_token: str = "${TELEGRAM_BOT_TOKEN}"
    allowed_chat_ids: list[int] = []  # empty = allow all (dangerous in prod)
    allowed_user_ids: list[int] = []  # empty = allow all

    def resolved_token(self) -> str:
        return _interpolate_env(self.bot_token)


class ReviewToolConfig(BaseModel):
    enabled: bool = True
    review_tool_path: str = "review-tool"  # CLI command or path
    default_args: list[str] = []  # e.g., ["--config", "/path/to/config.json"]


class ClaudeConfig(BaseModel):
    enabled: bool = True
    model: str = "sonnet"
    max_budget_usd: float = 0.50


class RunCommandConfig(BaseModel):
    enabled: bool = True
    allowed_commands: dict[str, str] = {}  # name -> shell command template


class AppConfig(BaseModel):
    telegram: TelegramConfig = TelegramConfig()
    review_tool: ReviewToolConfig = ReviewToolConfig()
    claude: ClaudeConfig = ClaudeConfig()
    run_commands: RunCommandConfig = RunCommandConfig()
    work_dir: str = "/tmp/telegram_harness"


def load_config(path: Path | str | None = None) -> AppConfig:
    if path is None:
        path = Path("telegram_harness.json")
    else:
        path = Path(path)
    if not path.exists():
        return AppConfig()
    raw = json.loads(path.read_text())
    interpolated = _interpolate_recursive(raw)
    return AppConfig.model_validate(interpolated)


def generate_default_config(path: Path | str) -> Path:
    path = Path(path)
    config = AppConfig()
    # Add example commands
    config.run_commands.allowed_commands = {
        "deploy-staging": "cd /app && git pull && make deploy-staging",
        "run-tests": "cd /app && make test",
        "disk-usage": "df -h",
    }
    data = config.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path
