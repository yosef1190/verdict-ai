"""NVIDIA NIM client (OpenAI-compatible chat completions) with model fallback."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .config import DEFAULT_NVIDIA_MODELS, NVIDIA_CHAT_ENDPOINT
from .errors import NvidiaError
from .openrouter_client import Completion, _content_from_payload, _extract_error

logger = logging.getLogger(__name__)


class NvidiaAuthError(NvidiaError):
    """The API key was rejected; no model will work, so don't keep trying."""

    fatal = True


class NvidiaClient:
    """Calls NVIDIA NIM (integrate.api.nvidia.com), falling through a model list."""

    name = "NVIDIA"

    def __init__(
        self,
        api_key: str,
        *,
        models: list[str] | None = None,
        endpoint: str = NVIDIA_CHAT_ENDPOINT,
        timeout: int = 180,
    ) -> None:
        if not api_key:
            raise NvidiaError("NVIDIA_API_KEY is not set.")
        self.models = [m for m in (models or DEFAULT_NVIDIA_MODELS) if m]
        if not self.models:
            raise NvidiaError("No NVIDIA models configured.")
        self.endpoint = endpoint
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
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
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                }
                try:
                    response = self.session.post(self.endpoint, json=payload, timeout=self.timeout)
                except requests.RequestException as exc:
                    errors.append(f"{model}: request failed: {exc}")
                    break

                status = response.status_code
                if status in (401, 403):
                    raise NvidiaAuthError(
                        f"NVIDIA rejected the API key (HTTP {status}). Check NVIDIA_API_KEY."
                    )

                if status == 429 or status >= 500:
                    errors.append(f"{model}: HTTP {status}")
                    if attempt == 0:
                        retry_after = response.headers.get("Retry-After", "")
                        wait = min(15, max(2, int(retry_after))) if retry_after.isdigit() else 3
                        logger.info("NVIDIA %s on %s; retrying in %ss", status, model, wait)
                        time.sleep(wait)
                        continue
                    break

                if not response.ok:
                    errors.append(f"{model}: HTTP {status} — {_extract_error(response)}")
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

                reported = data.get("model")
                return Completion(
                    text=text, model=reported if isinstance(reported, str) and reported else model
                )

        detail = "\n".join(f"- {error}" for error in errors)
        raise NvidiaError(f"Every configured NVIDIA model failed.\n{detail}")
