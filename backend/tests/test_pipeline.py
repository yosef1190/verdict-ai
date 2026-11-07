import pytest

from verdict import pipeline
from verdict.config import Settings
from verdict.errors import VerdictError
from verdict.models import SearchResult, Source
from verdict.pipeline import ResearchRequest, run_research, validate_request


def test_validate_requires_text():
    with pytest.raises(VerdictError):
        validate_request(ResearchRequest(text="  "))


def test_validate_rejects_bad_engine():
    with pytest.raises(VerdictError):
        validate_request(ResearchRequest(text="a", engine="nope"))


def test_validate_clamps_numbers():
    req = validate_request(ResearchRequest(text="a", limit=999, scrape_count=0))
    assert req.limit == 20 and req.scrape_count == 1


def test_missing_oxylabs_key_is_clear_error():
    with pytest.raises(VerdictError, match="OXYLABS_API_KEY"):
        run_research(ResearchRequest(text="https://shop.example/p"), Settings(oxylabs_api_key=""))


def test_review_extract_only_flow(monkeypatch):
    product = Source(url="https://shop.example/p/1", title="Widget Pro", text="A widget. " * 20)

    class FakeOxylabs:
        def __init__(self, *a, **k):
            pass

        def search(self, query, engine="yahoo", limit=10, fallback=True):
            return [
                SearchResult("Widget Pro review", "https://blog.example/widget", "great"),
                SearchResult("Same page", "https://shop.example/p/1", "dup"),
            ]

    monkeypatch.setattr(pipeline, "OxylabsClient", FakeOxylabs)
    monkeypatch.setattr(
        pipeline,
        "fetch_source",
        lambda client, url, run_js=False: product
        if "shop.example" in url
        else Source(url=url, title="Blog", text="Review text " * 20),
    )

    steps = []
    result = run_research(
        ResearchRequest(text="https://shop.example/p/1", no_ai=True),
        Settings(oxylabs_api_key="k"),
        steps.append,
    )
    assert "Widget Pro" in result.title
    assert "blog.example" in result.markdown
    assert any("Searching" in s for s in steps)
