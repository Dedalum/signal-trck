"""LLM client factory.

Wraps ``instructor`` so the rest of the codebase sees a uniform
``LLMClient.analyze(system, user, response_model)`` regardless of provider.
Anthropic, OpenAI, Moonshot/Kimi, DeepSeek are supported. Moonshot and
DeepSeek go through the ``OpenAI`` SDK pointed at their compatible
endpoints — no provider-specific SDKs needed for those.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol, TypeVar

import instructor
import structlog
from anthropic import Anthropic
from openai import OpenAI
from pydantic import BaseModel

log = structlog.get_logger(__name__)

Provider = Literal["anthropic", "openai", "moonshot", "deepseek"]
SUPPORTED_PROVIDERS: tuple[Provider, ...] = ("anthropic", "openai", "moonshot", "deepseek")

# Sensible defaults per provider. Override per-run via --model.
DEFAULT_MODELS: Final[dict[Provider, str]] = {
    "anthropic": "claude-opus-4-7",
    "openai": "gpt-4.1",
    "moonshot": "moonshot-v1-128k",
    "deepseek": "deepseek-chat",
}

# OpenAI-compatible base URLs for non-OpenAI providers using the OpenAI SDK.
_OPENAI_COMPAT_BASE_URLS: Final[dict[Provider, str]] = {
    "moonshot": "https://api.moonshot.ai/v1",
    "deepseek": "https://api.deepseek.com/v1",
}

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    """Uniform call surface for any supported provider."""

    provider: Provider
    model: str

    def analyze(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> T:
        """Send the prompt and return a validated ``response_model`` instance.

        Raises ``pydantic.ValidationError`` if the model fails to produce a
        schema-conformant response. Caller decides whether to retry.
        """
        ...


@dataclass
class _AnthropicClient:
    """Wraps ``instructor.from_anthropic``."""

    provider: Provider
    model: str
    _client: instructor.Instructor

    def analyze(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> T:
        return self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            response_model=response_model,
            system=system,
            messages=[{"role": "user", "content": user}],
        )


@dataclass
class _OpenAICompatClient:
    """Wraps ``instructor.from_openai``. Used for OpenAI itself, Moonshot, DeepSeek."""

    provider: Provider
    model: str
    _client: instructor.Instructor

    def analyze(
        self,
        *,
        system: str,
        user: str,
        response_model: type[T],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> T:
        return self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )


def build_client(provider: Provider, *, api_key: str, model: str | None = None) -> LLMClient:
    """Build a configured ``LLMClient`` for the chosen provider.

    ``model`` defaults to ``DEFAULT_MODELS[provider]`` when not given.
    Raises ``ValueError`` for unsupported providers or empty API keys.
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"unsupported provider {provider!r}; supported: {list(SUPPORTED_PROVIDERS)}"
        )
    if not api_key:
        raise ValueError(f"empty api_key for provider {provider!r}")

    chosen_model = model or DEFAULT_MODELS[provider]
    log.debug("llm.build_client", provider=provider, model=chosen_model)

    if provider == "anthropic":
        raw = Anthropic(api_key=api_key)
        wrapped = instructor.from_anthropic(raw)
        return _AnthropicClient(provider=provider, model=chosen_model, _client=wrapped)

    base_url = _OPENAI_COMPAT_BASE_URLS.get(provider)
    raw_oa = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    wrapped_oa = instructor.from_openai(raw_oa)
    return _OpenAICompatClient(provider=provider, model=chosen_model, _client=wrapped_oa)


def resolve_model(provider: Provider, model: str | None) -> str:
    """Apply the per-provider default model when the user hasn't specified one."""
    return model or DEFAULT_MODELS[provider]
