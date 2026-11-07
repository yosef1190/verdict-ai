"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

OXYLABS_SCRAPE_ENDPOINT = "https://webapi.oxylabs.io/v1/scrape"
NVIDIA_CHAT_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
GEMINI_BASE_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
OPENROUTER_CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODELS_ENDPOINT = "https://openrouter.ai/api/v1/models"

# Tried in order. Free models rotate, so the client automatically falls back
# when a model is unavailable, overloaded, or rate limited.
DEFAULT_FREE_MODELS = [
    "openrouter/free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-lightning:free",
    "thinkingmachines/inkling:free",
]


# Tried in order. "-latest" aliases follow Google's current Flash model, so the
# app keeps working as model names change. Pin an exact id with GEMINI_MODELS.
DEFAULT_GEMINI_MODELS = ["gemini-flash-latest"]


DEFAULT_NVIDIA_MODELS = ["meta/muse-glimmer-30b"]


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_models() -> list[str]:
    raw = os.getenv("OPENROUTER_MODELS", "").strip()
    if raw:
        models = [model.strip() for model in raw.split(",") if model.strip()]
        if models:
            return models

    single = os.getenv("OPENROUTER_MODEL", "").strip()
    if single:
        return [single, *(m for m in DEFAULT_FREE_MODELS if m != single)]

    return list(DEFAULT_FREE_MODELS)


def _env_nvidia_models() -> list[str]:
    raw = os.getenv("NVIDIA_MODELS", "").strip() or os.getenv("NVIDIA_MODEL", "").strip()
    models = [m.strip() for m in raw.split(",") if m.strip()]
    return models or list(DEFAULT_NVIDIA_MODELS)


def _env_gemini_models() -> list[str]:
    raw = os.getenv("GEMINI_MODELS", "").strip() or os.getenv("GEMINI_MODEL", "").strip()
    models = [m.strip() for m in raw.split(",") if m.strip()]
    return models or list(DEFAULT_GEMINI_MODELS)


@dataclass
class Settings:
    oxylabs_api_key: str = ""
    openrouter_api_key: str = ""
    nvidia_api_key: str = ""
    nvidia_models: list[str] = field(default_factory=lambda: list(DEFAULT_NVIDIA_MODELS))
    nvidia_endpoint: str = NVIDIA_CHAT_ENDPOINT
    gemini_api_key: str = ""
    gemini_models: list[str] = field(default_factory=lambda: list(DEFAULT_GEMINI_MODELS))
    gemini_endpoint: str = GEMINI_BASE_ENDPOINT
    openrouter_models: list[str] = field(default_factory=lambda: list(DEFAULT_FREE_MODELS))
    oxylabs_endpoint: str = OXYLABS_SCRAPE_ENDPOINT
    openrouter_endpoint: str = OPENROUTER_CHAT_ENDPOINT
    openrouter_models_endpoint: str = OPENROUTER_MODELS_ENDPOINT
    max_chars: int = 30_000
    chunk_size: int = 12_000
    chunk_overlap: int = 600
    timeout: int = 120
    max_workers: int = 3
    report_dir: Path = PROJECT_ROOT / "reports"

    @classmethod
    def from_env(
        cls,
        *,
        oxylabs_api_key: str | None = None,
        openrouter_api_key: str | None = None,
        nvidia_api_key: str | None = None,
        gemini_api_key: str | None = None,
        models: list[str] | None = None,
        report_dir: str | Path | None = None,
        max_chars: int | None = None,
        max_workers: int | None = None,
    ) -> "Settings":
        env_report_dir = os.getenv("VERDICT_REPORT_DIR", "").strip()
        resolved_report_dir = (
            Path(report_dir)
            if report_dir
            else Path(env_report_dir) if env_report_dir else PROJECT_ROOT / "reports"
        )

        return cls(
            oxylabs_api_key=(
                oxylabs_api_key
                if oxylabs_api_key is not None
                else os.getenv("OXYLABS_API_KEY", "").strip()
            ),
            openrouter_api_key=(
                openrouter_api_key
                if openrouter_api_key is not None
                else os.getenv("OPENROUTER_API_KEY", "").strip()
            ),
            nvidia_api_key=(
                nvidia_api_key
                if nvidia_api_key is not None
                else (os.getenv("NVIDIA_API_KEY") or "").strip()
            ),
            nvidia_models=_env_nvidia_models(),
            nvidia_endpoint=os.getenv("NVIDIA_ENDPOINT", NVIDIA_CHAT_ENDPOINT).strip()
            or NVIDIA_CHAT_ENDPOINT,
            gemini_api_key=(
                gemini_api_key
                if gemini_api_key is not None
                else (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
            ),
            gemini_models=_env_gemini_models(),
            gemini_endpoint=os.getenv("GEMINI_ENDPOINT", GEMINI_BASE_ENDPOINT).strip()
            or GEMINI_BASE_ENDPOINT,
            openrouter_models=(
                [m.strip() for m in models if m.strip()]
                if models
                else _env_models()
            ),
            oxylabs_endpoint=os.getenv("OXYLABS_ENDPOINT", OXYLABS_SCRAPE_ENDPOINT).strip()
            or OXYLABS_SCRAPE_ENDPOINT,
            openrouter_endpoint=os.getenv("OPENROUTER_ENDPOINT", OPENROUTER_CHAT_ENDPOINT).strip()
            or OPENROUTER_CHAT_ENDPOINT,
            openrouter_models_endpoint=os.getenv(
                "OPENROUTER_MODELS_ENDPOINT", OPENROUTER_MODELS_ENDPOINT
            ).strip()
            or OPENROUTER_MODELS_ENDPOINT,
            max_chars=(
                max_chars
                if max_chars and max_chars > 0
                else _env_int("VERDICT_MAX_CHARS", 30_000)
            ),
            timeout=_env_int("VERDICT_TIMEOUT", 120),
            max_workers=(
                max_workers
                if max_workers and max_workers > 0
                else _env_int("VERDICT_WORKERS", 3)
            ),
            report_dir=resolved_report_dir.expanduser(),
        )
