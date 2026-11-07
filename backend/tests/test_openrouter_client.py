import pytest

from verdict.errors import OpenRouterError
from verdict.openrouter_client import OpenRouterClient, fetch_free_models
from tests.conftest import FakeResponse


def make_client(models):
    return OpenRouterClient("test-key", models=models)


def test_complete_falls_back_when_model_is_missing():
    client = make_client(["missing/free", "working/free"])
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json["model"])
        if json["model"] == "missing/free":
            return FakeResponse(404, {"error": {"message": "model not found"}})
        return FakeResponse(
            200, {"choices": [{"message": {"content": "  hello  "}}]}
        )

    client.session.post = fake_post
    completion = client.complete([{"role": "user", "content": "hi"}])

    assert completion.text == "hello"
    assert completion.model == "working/free"
    assert calls == ["missing/free", "working/free"]


def test_complete_retries_rate_limit_then_falls_back(monkeypatch):
    monkeypatch.setattr("verdict.openrouter_client.time.sleep", lambda _seconds: None)
    client = make_client(["busy/free", "working/free"])
    calls = []

    def fake_post(url, json=None, timeout=None):
        model = json["model"]
        calls.append(model)
        if model == "busy/free":
            return FakeResponse(429, {"error": {"message": "rate limited"}})
        return FakeResponse(
            200, {"choices": [{"message": {"content": "fallback worked"}}]}
        )

    client.session.post = fake_post
    completion = client.complete([{"role": "user", "content": "hi"}])

    assert completion.model == "working/free"
    assert completion.text == "fallback worked"
    assert calls == ["busy/free", "busy/free", "working/free"]


def test_complete_stops_immediately_on_invalid_key():
    client = make_client(["one/free", "two/free"])
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json["model"])
        return FakeResponse(401, {"error": {"message": "bad key"}})

    client.session.post = fake_post

    with pytest.raises(OpenRouterError, match="401"):
        client.complete([{"role": "user", "content": "hi"}])

    assert calls == ["one/free"]


def test_complete_reports_all_failures():
    client = make_client(["one/free", "two/free"])
    client.session.post = lambda *args, **kwargs: FakeResponse(
        404, {"error": {"message": "gone"}}
    )

    with pytest.raises(OpenRouterError, match="Every configured OpenRouter model failed"):
        client.complete([{"role": "user", "content": "hi"}])


def test_missing_key_is_rejected():
    with pytest.raises(OpenRouterError, match="OPENROUTER_API_KEY"):
        OpenRouterClient("")


def test_fetch_free_models_filters_paid_models(monkeypatch):
    payload = {
        "data": [
            {
                "id": "paid/model",
                "name": "Paid",
                "context_length": 1000,
                "pricing": {"prompt": "0.001", "completion": "0.002"},
            },
            {
                "id": "free/b",
                "name": "Free B",
                "context_length": 2000,
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "free/a",
                "name": "Free A",
                "context_length": 3000,
                "pricing": {"prompt": "0", "completion": "0"},
            },
            {
                "id": "audio/model",
                "name": "Audio model",
                "context_length": 4000,
                "pricing": {"prompt": "0", "completion": "0"},
                "architecture": {"output_modalities": ["text", "audio"]},
            },
        ]
    }
    monkeypatch.setattr(
        "verdict.openrouter_client.requests.get",
        lambda *args, **kwargs: FakeResponse(200, payload),
    )

    models = fetch_free_models()

    assert [model["id"] for model in models] == ["free/a", "free/b"]
    assert models[0]["context_length"] == 3000
