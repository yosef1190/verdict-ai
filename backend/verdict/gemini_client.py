"""Google Gemini client (native generateContent API) with model fallback."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .config import DEFAULT_GEMINI_MODELS, GEMINI_BASE_ENDPOINT
from .errors import GeminiError
from .openrouter_client import Completion

logger = logging.getLogger(__name__)

# Gemini's "thinking" tokens count against maxOutputTokens, so leave headroom or
# a reasoning model can spend the whole budget before writing any answer.
THINKING_HEADROOM = 4
MAX_OUTPUT_CAP = 16_384


class GeminiAuthError(GeminiError):
    """The API key was rejected; no model will work, so don't keep trying."""

    fatal = True


def _error_message(response: requests.Response) -> str:
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
    return str(data)[:400]


def _split_messages(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
    system: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        text = str(message.get("content", ""))
        if role == "system":
            system.append(text)
            continue
        contents.append(
            {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
        )
    return "\n\n".join(system), contents


def _text_from_payload(data: dict[str, Any]) -> tuple[str, str]:
    """Return (text, problem). Skips 'thought' parts."""

    feedback = data.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        return "", f"prompt blocked ({feedback['blockReason']})"

    candidates = data.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return "", "no candidates returned"

    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str) and not part.get("thought")
    ).strip()
    if text:
        return text, ""
    return "", f"empty response (finish reason: {candidate.get('finishReason', 'unknown')})"


class GeminiClient:
    """Calls Gemini, falling through a list of models on failure.

    ``temperature`` is accepted for interface compatibility but not sent: Google
    has deprecated sampling parameters on its newest models.
    """

    name = "Gemini"

    def __init__(
        self,
        api_key: str,
        *,
        models: list[str] | None = None,
        endpoint: str = GEMINI_BASE_ENDPOINT,
        timeout: int = 180,
    ) -> None:
        if not api_key:
            raise GeminiError("GEMINI_API_KEY is not set.")
        self.models = [m for m in (models or DEFAULT_GEMINI_MODELS) if m]
        if not self.models:
            raise GeminiError("No Gemini models configured.")
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"x-goog-api-key": api_key, "Content-Type": "application/json"}
        )

    def _url(self, model: str) -> str:
        model = model.removeprefix("models/")
        return f"{self.endpoint}/models/{model}:generateContent"

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,  # noqa: ARG002 - see class docstring
        max_tokens: int = 1600,
    ) -> Completion:
        system, contents = _split_messages(messages)
        if not contents:
            raise GeminiError("No user content to send.")

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": min(MAX_OUTPUT_CAP, max_tokens * THINKING_HEADROOM)
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        errors: list[str] = []
        for model in self.models:
            for attempt in range(2):
                try:
                    response = self.session.post(
                        self._url(model), json=body, timeout=self.timeout
                    )
                except requests.RequestException as exc:
                    errors.append(f"{model}: request failed: {exc}")
                    break

                status = response.status_code
                if status in (401, 403) or (
                    status == 400 and "api key" in _error_message(response).lower()
                ):
                    raise GeminiAuthError(
                        f"Gemini rejected the API key (HTTP {status}). Check GEMINI_API_KEY."
                    )

                if status == 429 or status >= 500:
                    errors.append(f"{model}: HTTP {status}")
                    if attempt == 0:
                        retry_after = response.headers.get("Retry-After", "")
                        wait = min(15, max(2, int(retry_after))) if retry_after.isdigit() else 3
                        logger.info("Gemini %s on %s; retrying in %ss", status, model, wait)
                        time.sleep(wait)
                        continue
                    break

                if not response.ok:
                    errors.append(f"{model}: HTTP {status} — {_error_message(response)}")
                    break

                try:
                    data = response.json()
                except ValueError:
                    errors.append(f"{model}: non-JSON response")
                    break

                text, problem = _text_from_payload(data)
                if not text:
                    errors.append(f"{model}: {problem}")
                    break

                reported = data.get("modelVersion")
                return Completion(
                    text=text,
                    model=reported if isinstance(reported, str) and reported else model,
                )

        detail = "\n".join(f"- {error}" for error in errors)
        raise GeminiError(f"Every configured Gemini model failed.\n{detail}")
