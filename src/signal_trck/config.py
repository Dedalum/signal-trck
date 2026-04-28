"""Runtime configuration: ``.env`` secrets + optional YAML overlay.

Pattern borrowed from ``signalfetch/src/config.py:41`` (env-var resolution in YAML),
adapted for signal-trck's provider-agnostic LLM stance and crypto pairs.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["anthropic", "openai", "moonshot", "deepseek"]


class Settings(BaseSettings):
    """Secrets and per-process env from ``.env``.

    The active LLM provider is selected by ``LLM_PROVIDER``. Only the
    matching provider's API key is required; others may be left empty.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    llm_provider: LLMProvider = "anthropic"
    llm_model: str = ""

    anthropic_api_key: str = ""
    openai_api_key: str = ""
    moonshot_api_key: str = ""
    deepseek_api_key: str = ""

    coingecko_api_key: str = ""

    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"


_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: Any) -> Any:
    """Replace ``${VAR}`` references in strings with environment values.

    Recurses through dict/list values. Missing vars are left as-is so the
    caller sees the raw placeholder rather than a silent empty string.
    """
    if isinstance(value, str):
        return _ENV_VAR_PATTERN.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def load_yaml_config(config_path: str | Path | None = "config.yaml") -> dict:
    """Load a YAML config file with ``${VAR}`` env-var resolution.

    Returns an empty dict if the file does not exist.
    """
    if config_path is None:
        return {}
    path = Path(config_path)
    if not path.exists():
        return {}
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return _resolve_env_vars(raw)


class AppConfig:
    """Combined configuration: env settings + optional YAML overlay."""

    def __init__(self, config_path: str | Path | None = "config.yaml"):
        self.settings = Settings()
        self.yaml = load_yaml_config(config_path)

    def provider_api_key(self, provider: LLMProvider | None = None) -> str:
        """Return the API key for the given provider (or active provider)."""
        p = provider or self.settings.llm_provider
        return {
            "anthropic": self.settings.anthropic_api_key,
            "openai": self.settings.openai_api_key,
            "moonshot": self.settings.moonshot_api_key,
            "deepseek": self.settings.deepseek_api_key,
        }[p]

    @property
    def default_pairs(self) -> list[str]:
        return list(self.yaml.get("default_pairs", []))

    @property
    def default_intervals(self) -> list[str]:
        return list(self.yaml.get("default_intervals", ["1d"]))
