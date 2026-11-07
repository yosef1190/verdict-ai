import pytest

from verdict.config import Settings
from verdict.errors import GeminiError, LLMError, OpenRouterError
from verdict.gemini_client import GeminiAuthError, GeminiClient
from verdict.llm import FallbackClient, ai_available, build_llm
from verdict.openrouter_client import Completion
from tests.conftest import FakeResponse

MSGS = [
    {"role": "system", "content": "be brief"},
    {"role": "user", "content": "hi"},
]


def ok_payload(text="hello", model="gemini-x"):
    return {"candidates": [{"content": {"parts": [{"text": text}]}}], "modelVersion": model}


def test_gemini_success_maps_system_and_roles():
    client = GeminiClient("key", models=["m1"])
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"], seen["body"] = url, json
        return FakeResponse(200, ok_payload("  hi there  "))

    client.session.post = fake_post
    out = client.complete(MSGS + [{"role": "assistant", "content": "a"}, {"role": "user", "content": "b"}])

    assert out.text == "hi there"
    assert seen["url"].endswith("/models/m1:generateContent")
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]
    assert "temperature" not in seen["body"]["generationConfig"]
    assert client.session.headers["x-goog-api-key"] == "key"


def test_gemini_skips_thought_parts():
    client = GeminiClient("key", models=["m1"])
    payload = {"candidates": [{"content": {"parts": [
        {"text": "private reasoning", "thought": True}, {"text": "final answer"}]}}]}
    client.session.post = lambda url, json=None, timeout=None: FakeResponse(200, payload)
    assert client.complete(MSGS).text == "final answer"


def test_gemini_falls_through_models_and_retries_429(monkeypatch):
    monkeypatch.setattr("verdict.gemini_client.time.sleep", lambda _s: None)
    client = GeminiClient("key", models=["busy", "good"])
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(url.split("/models/")[1])
        if "busy" in url:
            return FakeResponse(429, {"error": {"message": "quota"}})
        return FakeResponse(200, ok_payload())

    client.session.post = fake_post
    assert client.complete(MSGS).text == "hello"
    assert calls == ["busy:generateContent", "busy:generateContent", "good:generateContent"]


def test_gemini_bad_key_is_fatal_for_http_400_api_key_invalid():
    client = GeminiClient("bad", models=["m"])
    client.session.post = lambda url, json=None, timeout=None: FakeResponse(
        400, {"error": {"message": "API key not valid. Please pass a valid API key."}}
    )
    with pytest.raises(GeminiAuthError) as exc:
        client.complete(MSGS)
    assert exc.value.fatal


def test_gemini_blocked_prompt_raises():
    client = GeminiClient("key", models=["m"])
    client.session.post = lambda url, json=None, timeout=None: FakeResponse(
        200, {"promptFeedback": {"blockReason": "SAFETY"}}
    )
    with pytest.raises(GeminiError, match="blocked"):
        client.complete(MSGS)


class Stub:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def complete(self, messages, *, temperature=0.2, max_tokens=1600):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_fallback_uses_openrouter_when_gemini_fails():
    gem = Stub(error=GeminiError("down"))
    router = Stub(result=Completion("from router", "r/free"))
    out = FallbackClient([("Gemini", gem), ("OpenRouter", router)]).complete(MSGS)
    assert out.text == "from router"
    assert gem.calls == 1 and router.calls == 1


def test_fallback_prefers_gemini_when_it_works():
    gem = Stub(result=Completion("from gemini", "g"))
    router = Stub(result=Completion("from router", "r"))
    out = FallbackClient([("Gemini", gem), ("OpenRouter", router)]).complete(MSGS)
    assert out.text == "from gemini" and router.calls == 0


def test_fallback_stops_retrying_gemini_after_auth_failure():
    gem = Stub(error=GeminiAuthError("bad key"))
    router = Stub(result=Completion("ok", "r"))
    chain = FallbackClient([("Gemini", gem), ("OpenRouter", router)])
    chain.complete(MSGS)
    chain.complete(MSGS)
    assert gem.calls == 1 and router.calls == 2


def test_fallback_all_fail_raises_llm_error_listing_both():
    chain = FallbackClient([
        ("Gemini", Stub(error=GeminiError("g down"))),
        ("OpenRouter", Stub(error=OpenRouterError("r down"))),
    ])
    with pytest.raises(LLMError) as exc:
        chain.complete(MSGS)
    assert "g down" in str(exc.value) and "r down" in str(exc.value)


def test_build_llm_order_and_requirements():
    both = build_llm(Settings(gemini_api_key="g", openrouter_api_key="o"))
    assert both.names == ["Gemini", "OpenRouter"]
    assert build_llm(Settings(openrouter_api_key="o")).names == ["OpenRouter"]
    assert build_llm(Settings(gemini_api_key="g")).names == ["Gemini"]
    with pytest.raises(LLMError):
        build_llm(Settings())
    assert ai_available(Settings(gemini_api_key="g"))
    assert not ai_available(Settings())


def test_settings_reads_gemini_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", " abc ")
    monkeypatch.setenv("GEMINI_MODELS", "gemini-a, gemini-b")
    s = Settings.from_env()
    assert s.gemini_api_key == "abc"
    assert s.gemini_models == ["gemini-a", "gemini-b"]


# ---- NVIDIA NIM (primary) ----
from verdict.errors import NvidiaError
from verdict.nvidia_client import NvidiaAuthError, NvidiaClient


def test_nvidia_success_and_payload():
    client = NvidiaClient("nvapi-test", models=["meta/muse-glimmer-30b"])
    seen = {}

    def fake_post(url, json=None, timeout=None):
        seen["url"], seen["body"] = url, json
        return FakeResponse(200, {"model": "meta/muse-glimmer-30b",
                                  "choices": [{"message": {"content": " 9.8 "}}]})

    client.session.post = fake_post
    out = client.complete(MSGS, temperature=0.1, max_tokens=500)
    assert out.text == "9.8"
    assert seen["url"] == "https://integrate.api.nvidia.com/v1/chat/completions"
    assert seen["body"]["model"] == "meta/muse-glimmer-30b"
    assert seen["body"]["max_tokens"] == 500 and seen["body"]["stream"] is False
    assert client.session.headers["Authorization"] == "Bearer nvapi-test"


def test_nvidia_bad_key_is_fatal():
    client = NvidiaClient("bad", models=["m"])
    client.session.post = lambda url, json=None, timeout=None: FakeResponse(401, {"error": "no"})
    with pytest.raises(NvidiaAuthError) as exc:
        client.complete(MSGS)
    assert exc.value.fatal


def test_nvidia_model_failure_raises_nvidia_error(monkeypatch):
    monkeypatch.setattr("verdict.nvidia_client.time.sleep", lambda _s: None)
    client = NvidiaClient("k", models=["m"])
    client.session.post = lambda url, json=None, timeout=None: FakeResponse(500, {"error": "boom"})
    with pytest.raises(NvidiaError, match="Every configured NVIDIA model failed"):
        client.complete(MSGS)


def test_chain_order_is_nvidia_then_gemini_then_openrouter():
    chain = build_llm(Settings(nvidia_api_key="n", gemini_api_key="g", openrouter_api_key="o"))
    assert chain.names == ["NVIDIA", "Gemini", "OpenRouter"]
    assert build_llm(Settings(nvidia_api_key="n")).names == ["NVIDIA"]


def test_full_cascade_nvidia_fails_gemini_fails_openrouter_wins():
    n = Stub(error=NvidiaAuthError("bad key"))
    g = Stub(error=GeminiError("quota"))
    o = Stub(result=Completion("saved by router", "r/free"))
    chain = FallbackClient([("NVIDIA", n), ("Gemini", g), ("OpenRouter", o)])
    assert chain.complete(MSGS).text == "saved by router"
    chain.complete(MSGS)
    assert n.calls == 1          # auth failure -> NVIDIA skipped afterwards
    assert g.calls == 2 and o.calls == 2


def test_settings_reads_nvidia_env(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", " nvapi-x ")
    monkeypatch.setenv("NVIDIA_MODELS", "a/b, c/d")
    s = Settings.from_env()
    assert s.nvidia_api_key == "nvapi-x" and s.nvidia_models == ["a/b", "c/d"]
    assert Settings().nvidia_models == ["meta/muse-glimmer-30b"]
