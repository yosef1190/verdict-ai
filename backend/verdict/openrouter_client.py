"""OpenRouter chat-completions client with automatic free-model fallback."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import (
    DEFAULT_FREE_MODELS,
    OPENROUTER_CHAT_ENDPOINT,
    OPENROUTER_MODELS_ENDPOINT,
)
from .errors import OpenRouterError

logger = logging.getLogger(__name__)


@dataclass
class Completion:
    text: str
    model: str


def _extract_error(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:400] or f"HTTP {response.status_code}"

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:400]
        if error:
            return str(error)[:400]
        if data.get("message"):
            return str(data["message"])[:400]
    return str(data)[:400]


def _content_from_payload(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""

    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts).strip()

    return ""


class OpenRouterClient:
    """Calls OpenRouter, falling through a list of models on failure."""

    def __init__(
        self,
        api_key: str,
        *,
        models: list[str] | None = None,
        endpoint: str = OPENROUTER_CHAT_ENDPOINT,
        timeout: int = 180,
        app_url: str = "https://github.com/verdict-research",
        app_name: str = "Verdict Research",
    ) -> None:
        if not api_key:
            raise OpenRouterError(
                "OPENROUTER_API_KEY is not set. Add it to .env or pass --openrouter-key."
            )
        self.models = [model for model in (models or DEFAULT_FREE_MODELS) if model]
        if not self.models:
            raise OpenRouterError("No OpenRouter models configured.")
        self.endpoint = endpoint
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": app_url,
                "X-Title": app_name,
            }
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 1600,
    ) -> Completion:
        errors: list[str] = []

        for model in self.models:
            for attempt in range(2):
                payload = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }

                try:
                    response = self.session.post(
                        self.endpoint, json=payload, timeout=self.timeout
                    )
                except requests.RequestException as exc:
                    errors.append(f"{model}: request failed: {exc}")
                    break

                if response.status_code == 401:
                    raise OpenRouterError(
                        "OpenRouter rejected the API key (HTTP 401). "
                        "Check OPENROUTER_API_KEY."
                    )

                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After", "")
                    wait = min(15, max(2, int(retry_after) if retry_after.isdigit() else 3))
                    errors.append(f"{model}: rate limited (429)")
                    if attempt == 0:
                        logger.info("Rate limited on %s; retrying in %ss", model, wait)
                        time.sleep(wait)
                        continue
                    break

                if response.status_code >= 500:
                    errors.append(f"{model}: HTTP {response.status_code}")
                    if attempt == 0:
                        time.sleep(3)
                        continue
                    break

                if not response.ok:
                    errors.append(
                        f"{model}: HTTP {response.status_code} — {_extract_error(response)}"
                    )
                    break

                try:
                    data = response.json()
                except ValueError:
                    errors.append(f"{model}: non-JSON response")
                    break

                text = _content_from_payload(data)
                if not text:
                    errors.append(f"{model}: empty response")
                    break

                reported_model = data.get("model")
                return Completion(
                    text=text,
                    model=reported_model if isinstance(reported_model, str) else model,
                )

        detail = "\n".join(f"- {error}" for error in errors)
        raise OpenRouterError(
            "Every configured OpenRouter model failed. Free models are often busy; "
            "retry in a minute or pick another model with: python app.py models\n"
            f"{detail}"
        )


def fetch_free_models(
    endpoint: str = OPENROUTER_MODELS_ENDPOINT,
    *,
    timeout: int = 30,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return currently available OpenRouter models that cost nothing."""

    try:
        response = requests.get(endpoint, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OpenRouterError(f"Could not load the OpenRouter model list: {exc}") from exc

    models: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict):
            continue
        pricing = item.get("pricing") or {}
        try:
            prompt_price = float(pricing.get("prompt") or 0)
            completion_price = float(pricing.get("completion") or 0)
        except (TypeError, ValueError):
            continue
        if prompt_price != 0 or completion_price != 0:
            continue

        architecture = item.get("architecture") or {}
        output_modalities = architecture.get("output_modalities") or []
        if output_modalities and "text" not in output_modalities:
            continue
        if "audio" in output_modalities or "image" in output_modalities:
            continue

        models.append(
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "context_length": item.get("context_length") or 0,
            }
        )

    models.sort(key=lambda model: model["id"])
    return models[:limit]
