import json

from verdict.models import Source, SourceSummary
from verdict.product import (
    clean_product_title,
    fallback_search_query,
    finalize_search_query,
    same_page,
)
from verdict.summarizer import Summarizer
from verdict.config import Settings
from verdict.openrouter_client import Completion
from verdict.verdict_prompt import VERDICT_SYSTEM_PROMPT


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return Completion(self.text, "fake/model")


def test_clean_product_title_removes_store_price_and_category():
    title = "Amazon.com: Sony WH-1000XM5 Wireless Headphones - Black : Electronics"

    assert (
        clean_product_title(title)
        == "Sony WH-1000XM5 Wireless Headphones - Black"
    )


def test_fallback_query_uses_product_title():
    source = Source(
        url="https://www.amazon.com/dp/B09XS7JWHH",
        title="Sony WH-1000XM5 Wireless Noise Canceling Headphones",
        text="Product details",
    )

    assert fallback_search_query(source) == (
        "Sony WH-1000XM5 Wireless Noise Canceling Headphones review"
    )


def test_fallback_query_uses_search_url_keywords():
    source = Source(
        url="https://www.amazon.com/s?k=sony+wh-1000xm5",
        title="Amazon.com",
        text="Search results",
    )

    assert fallback_search_query(source) == "sony wh-1000xm5 review"


def test_fallback_query_uses_url_slug_for_store_listing():
    source = Source(
        url="https://www.walmart.com/ip/Sony-WH-1000XM5-Wireless-Headphones/123456789",
        title="",
        text="Product details",
    )

    assert fallback_search_query(source) == (
        "Sony WH 1000XM5 Wireless Headphones review"
    )


def test_finalize_query_does_not_duplicate_review():
    assert finalize_search_query("Sony XM5 review") == "Sony XM5 review"
    assert finalize_search_query("  Sony XM5  ") == "Sony XM5 review"


def test_same_page_ignores_tracking_host_prefix_and_trailing_slash():
    assert same_page(
        "https://www.example.com/product/abc/?ref=home",
        "https://example.com/product/abc",
    )
    assert not same_page(
        "https://example.com/product/abc",
        "https://example.com/product/xyz",
    )


def test_same_page_matches_amazon_asin_across_url_shapes():
    assert same_page(
        "https://www.amazon.com/dp/B09XS7JWHH",
        "https://amazon.com/Sony-WH-1000XM5/dp/B09XS7JWHH/ref=sr_1_1",
    )
    assert same_page(
        "https://www.amazon.com/clp/B09XS7JWHH",
        "https://www.amazon.com/dp/B09XS7JWHH",
    )


def test_derive_research_plan_prompts_use_the_page_text():
    plan_json = json.dumps(
        {
            "product": {"name": "Sony WH-1000XM5", "brand": "Sony"},
            "important_claims": [],
            "research_queries": ["Sony WH-1000XM5 honest reviews"],
        }
    )
    client = FakeClient(plan_json)
    summarizer = Summarizer(client, Settings(max_chars=1000))
    source = Source(
        url="https://example.com/xm5",
        title="Sony WH-1000XM5",
        text="Noise canceling headphones with 30 hour battery life.",
    )

    plan = summarizer.derive_research_plan(source)

    assert plan.queries == ["Sony WH-1000XM5 honest reviews"]
    prompt = "\n".join(message["content"] for message in client.calls[-1][0])
    assert "Sony WH-1000XM5" in prompt
    assert "Noise canceling headphones" in prompt


def _complete_report() -> str:
    sections = [
        "## 🏆 Overall Verdict",
        "**Verdict Score: 82/100**",
        "",
        "## 📦 Product Overview",
        "A product.",
        "",
        "## ✅ What Looks Good",
        "Good things.",
        "",
        "## ❌ Problems and Red Flags",
        "Bad things.",
        "",
        "## 🗣️ What Real Customers Are Saying",
        "Feedback.",
        "",
        "## 🔍 Claims vs Reality",
        "Claims.",
        "",
        "## 💰 Value for Money",
        "Value.",
        "",
        "## 🏢 Brand and Seller Trustworthiness",
        "Brand.",
        "",
        "## 🔄 Alternatives",
        "Alternatives.",
        "",
        "## 🎯 Who Should Buy It?",
        "Buyers.",
        "",
        "## 🚫 Who Should Avoid It?",
        "Avoiders.",
        "",
        "## 🧠 Final Recommendation",
        "Buy it if the price is right and you value noise cancellation.",
    ]
    return "\n".join(sections)


def test_build_product_report_uses_verdict_prompt_and_primary_source():
    client = FakeClient(_complete_report())
    summarizer = Summarizer(client, Settings(max_chars=1000))
    summaries = [
        SourceSummary("Product", "https://shop.example.com/xm5", "Seller claims"),
        SourceSummary("Review", "https://reviews.example.com/xm5", "Independent test"),
    ]

    report = summarizer.build_product_report(
        "Sony WH-1000XM5",
        "Sony WH-1000XM5 review",
        summaries,
        product_url="https://shop.example.com/xm5",
    )

    assert "82/100" in report
    assert report.startswith("# 🏆 Overall Verdict")
    messages, kwargs = client.calls[-1]
    assert messages[0]["content"] == VERDICT_SYSTEM_PROMPT
    prompt = messages[1]["content"]
    assert "[1] Product" in prompt
    assert "Role: Primary product page (seller claims)" in prompt
    assert "Role: Independent research source" in prompt
    assert kwargs["max_tokens"] == 4000


def test_incomplete_product_report_is_continued_from_cutoff():
    complete = _complete_report()
    cutoff = complete.index("Buy it if")
    first = complete[: cutoff + len("Buy it if")]
    tail = complete[cutoff + len("Buy it if") :]

    class RetryClient(FakeClient):
        def __init__(self):
            super().__init__(first)
            self.count = 0

        def complete(self, messages, **kwargs):
            self.count += 1
            self.calls.append((messages, kwargs))
            return Completion(first if self.count == 1 else tail, "fake/model")

    client = RetryClient()
    summarizer = Summarizer(client, Settings(max_chars=1000))
    summaries = [
        SourceSummary("Product", "https://shop.example.com/xm5", "Seller claims"),
    ]

    report = summarizer.build_product_report(
        "Sony WH-1000XM5",
        "Sony WH-1000XM5 review",
        summaries,
        product_url="https://shop.example.com/xm5",
    )

    assert client.count == 2
    assert report.startswith("# 🏆 Overall Verdict")
    assert "Final Recommendation" in report
    assert report.rstrip().endswith(".")
    continuation_prompt = client.calls[-1][0][-1]["content"]
    assert "CONTINUE the report above" in continuation_prompt
