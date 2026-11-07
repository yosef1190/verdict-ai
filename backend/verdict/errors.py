"""Shared exceptions."""


class VerdictError(RuntimeError):
    """Base error raised by Verdict Research."""


class OxylabsError(VerdictError):
    """Oxylabs request failed or returned unusable data."""


class LLMError(VerdictError):
    """An AI provider (Gemini, OpenRouter) failed. ``fatal`` means retrying is pointless."""

    fatal = False


class OpenRouterError(LLMError):
    """OpenRouter request failed on every configured model."""


class NvidiaError(LLMError):
    """NVIDIA NIM request failed on every configured model."""


class GeminiError(LLMError):
    """Gemini request failed on every configured model."""


class ExtractionError(VerdictError):
    """A page could not be reduced to readable text."""
