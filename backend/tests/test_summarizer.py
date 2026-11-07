import json

import pytest

from verdict.config import Settings
from verdict.errors import OpenRouterError
from verdict.models import Source, SourceSummary
from verdict.openrouter_client import Completion
from verdict.summarizer import Summarizer


class FakeClient:
    def __init__(self, text="### TL;DR\nA compact summary."):
        self.text = text
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return Completion(self.text, "fake/model")


class FailingClient:
    def complete(self, messages, **kwargs):
        raise OpenRouterError("model unavailable")


def plan_source() -> Source:
    return Source(
        url="https://shop.example.com/sony-wh-1000xm5",
        title="Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        description="Buy the flagship Sony headphones.",
        text="Detailed page copy. " * 30,
    )


def test_summarize_page_then_create_link_report():
    client = FakeClient()
    summarizer = Summarizer(client, Settings(max_chars=1000))
    source = Source(
        url="https://example.com/post",
        title="An example post",
        text="Useful content about the topic. " * 40,
    )

    summary = summarizer.summarize_page(source)
    assert summary.model == "fake/model"
    assert "TL;DR" in summary.summary
    assert summary.url == source.url

    report = summarizer.build_report("An example post", [summary], kind="link")
    assert "TL;DR" in report

    prompts = "\n".join(message["content"] for message in client.calls[-1])
    assert "single web page" in prompts
    assert "https://example.com/post" in prompts


def test_long_pages_are_chunked_before_the_final_summary():
    client = FakeClient("A useful note.")
    summarizer = Summarizer(
        client,
        Settings(max_chars=120, chunk_size=60, chunk_overlap=10),
    )
    source = Source(
        url="https://example.com/long",
        title="Long page",
        text="Sentence with facts and numbers. " * 80,
    )

    summary = summarizer.summarize_page(source)

    assert summary.summary == "A useful note."
    assert len(client.calls) > 2


def test_multi_source_report_includes_numbered_sources():
    client = FakeClient("Report body.")
    summarizer = Summarizer(client, Settings(max_chars=1000))
    summaries = [
        SourceSummary("First", "https://example.com/a", "Summary A", "fake/model"),
        SourceSummary("Second", "https://example.com/b", "Summary B", "fake/model"),
    ]

    report = summarizer.build_report("A topic", summaries, kind="multi")
    assert report == "Report body."

    prompt = client.calls[-1][-1]["content"]
    assert "[1] First" in prompt
    assert "[2] Second" in prompt
    assert "URL: https://example.com/a" in prompt


def test_report_requires_at_least_one_summary():
    summarizer = Summarizer(FakeClient(), Settings())

    with pytest.raises(OpenRouterError, match="no summaries"):
        summarizer.build_report("topic", [], kind="multi")


def test_derive_research_plan_parses_json_queries_and_dedupes():
    plan_json = json.dumps(
        {
            "product": {
                "name": "Sony WH-1000XM5",
                "brand": "Sony",
                "model": "WH-1000XM5",
                "category": "headphones",
            },
            "important_claims": [
                "Industry-leading noise cancellation",
                "Industry-leading noise cancellation",
                "x",
            ],
            "research_queries": [
                "Sony WH-1000XM5 honest reviews",
                "  Sony WH-1000XM5 honest reviews  ",
                "",
                "Sony WH-1000XM5 problems complaints",
                "Sony WH-1000XM5 scam",
                "Sony WH-1000XM5 noise cancellation real world evidence",
            ],
        }
    )
    wrapped = f"Here is the plan:\n```json\n{plan_json}\n```"
    client = FakeClient(wrapped)
    summarizer = Summarizer(client, Settings(max_chars=1000))

    plan = summarizer.derive_research_plan(plan_source())

    assert plan.name == "Sony WH-1000XM5"
    assert plan.brand == "Sony"
    assert plan.category == "headphones"
    assert plan.claims == ["Industry-leading noise cancellation"]
    assert plan.queries == [
        "Sony WH-1000XM5 honest reviews",
        "Sony WH-1000XM5 problems complaints",
        "Sony WH-1000XM5 scam",
        "Sony WH-1000XM5 noise cancellation real world evidence",
    ]


def test_derive_research_plan_falls_back_when_ai_output_is_unusable():
    client = FakeClient("I could not produce JSON, sorry!")
    summarizer = Summarizer(client, Settings(max_chars=1000))

    plan = summarizer.derive_research_plan(plan_source())

    assert plan.queries
    assert plan.queries[0].casefold().endswith("review")
    assert len(plan.queries) == 3


def test_derive_research_plan_falls_back_when_ai_fails():
    summarizer = Summarizer(FailingClient(), Settings(max_chars=1000))

    plan = summarizer.derive_research_plan(plan_source())

    assert plan.queries
    assert "Sony WH-1000XM5" in plan.queries[0]
