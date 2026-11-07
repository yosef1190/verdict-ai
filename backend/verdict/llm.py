"""Provider chain: NVIDIA NIM first, then Gemini, then OpenRouter."""

from __future__ import annotations

import logging
from typing import Protocol

from .config import Settings
from .errors import LLMError
from .gemini_client import GeminiClient
from .nvidia_client import NvidiaClient
from .openrouter_client import Completion, OpenRouterClient

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    def complete(
        self, messages: list[dict[str, str]], *, temperature: float = ..., max_tokens: int = ...
    ) -> Completion: ...


class FallbackClient:
    """Tries each provider in order and returns the first successful completion."""

    def __init__(self, providers: list[tuple[str, LLMClient]]) -> None:
        if not providers:
            raise LLMError(
                "No AI provider configured. Set NVIDIA_API_KEY (primary) and/or "
                "GEMINI_API_KEY / OPENROUTER_API_KEY (fallbacks)."
            )
        self.providers = providers
        self._disabled: set[str] = set()

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.providers]

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1600,
    ) -> Completion:
        errors: list[str] = []
        for name, client in self.providers:
            if name in self._disabled:
                continue
            try:
                return client.complete(messages, temperature=temperature, max_tokens=max_tokens)
            except LLMError as exc:
                logger.info("%s failed, trying next provider: %s", name, exc)
                errors.append(f"{name}: {exc}")
                if exc.fatal:
                    self._disabled.add(name)

        raise LLMError("Every AI provider failed.\n" + "\n".join(errors))


def ai_available(settings: Settings) -> bool:
    return bool(settings.nvidia_api_key or settings.gemini_api_key or settings.openrouter_api_key)


def build_llm(settings: Settings) -> FallbackClient:
    providers: list[tuple[str, LLMClient]] = []
    if settings.nvidia_api_key:
        providers.append(
            (
                "NVIDIA",
                NvidiaClient(
                    settings.nvidia_api_key,
                    models=settings.nvidia_models,
                    endpoint=settings.nvidia_endpoint,
                    timeout=settings.timeout,
                ),
            )
        )
    if settings.gemini_api_key:
        providers.append(
            (
                "Gemini",
                GeminiClient(
                    settings.gemini_api_key,
                    models=settings.gemini_models,
                    endpoint=settings.gemini_endpoint,
                    timeout=settings.timeout,
                ),
            )
        )
    if settings.openrouter_api_key:
        providers.append(
            (
                "OpenRouter",
                OpenRouterClient(
                    settings.openrouter_api_key,
                    models=settings.openrouter_models,
                    endpoint=settings.openrouter_endpoint,
                    timeout=settings.timeout,
                ),
            )
        )
    return FallbackClient(providers)
