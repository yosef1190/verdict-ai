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
    assert req.limit == 50 and req.scrape_count == 1


def test_parallel_searches_run_concurrently():
    """Five 0.2s queries should finish in roughly 0.2s, not 1.0s.

    This measures the orchestration only (a fake client), so it proves branches
    are dispatched together without depending on external API latency.
    """
    import time as _time

    calls: list[str] = []

    class SlowClient:
        def search(self, query, engine="yahoo", limit=10, fallback=True):
            calls.append(query)
            _time.sleep(0.2)
            return [SearchResult(f"r {query}", f"https://example.com/{query.replace(' ', '-')}", "s")]

    started = _time.monotonic()
    merged = pipeline.run_parallel_searches(
        SlowClient(),
        [f"query {i}" for i in range(5)],
        lambda _msg: None,
        engine="yahoo",
        results_per_query=5,
        primary_urls=set(),
        deadline=_time.monotonic() + 30,
    )
    elapsed = _time.monotonic() - started

    assert len(calls) == 5
    assert len(merged) == 5
    # Sequential would be ~1.0s. Allow generous headroom for slow CI machines.
    assert elapsed < 0.9, f"searches did not run concurrently ({elapsed:.2f}s)"


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
    assert any("search queries" in s for s in steps)
    assert result.mode == "light"
    assert result.stage_timings.get("total_time", 0) >= 0


def test_scraped_pages_are_cached_between_runs(monkeypatch):
    """The same URL should be scraped once, then served from the short-lived cache."""
    pipeline.clear_source_cache()
    scrapes: list[str] = []

    class Page:
        html = "<html><body><p>" + ("Review text. " * 40) + "</p></body></html>"
        url = "https://blog.example/widget"
        status_code = 200

    class FakeOxylabs:
        def scrape(self, url, run_js=False):
            scrapes.append(url)
            return Page()

    monkeypatch.setattr(pipeline, "_SOURCE_CACHE_TTL", 60.0)
    first = pipeline.fetch_source(FakeOxylabs(), "https://blog.example/widget")
    second = pipeline.fetch_source(FakeOxylabs(), "https://blog.example/widget")
    assert scrapes == ["https://blog.example/widget"]
    assert first.text == second.text
    # run_js pages are cached separately, since the rendered HTML differs.
    pipeline.fetch_source(FakeOxylabs(), "https://blog.example/widget", run_js=True)
    assert len(scrapes) == 2
    pipeline.clear_source_cache()
