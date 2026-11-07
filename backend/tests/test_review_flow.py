from types import SimpleNamespace

import app
from verdict.config import Settings
from verdict.models import ResearchPlan, SearchResult, SourceSummary


PRODUCT_URL = "https://shop.example.com/sony-wh-1000xm5"

PLAN = ResearchPlan(
    name="Sony WH-1000XM5",
    brand="Sony",
    model="",
    category="headphones",
    claims=["Industry-leading noise cancellation"],
    queries=[
        "Sony WH-1000XM5 review",
        "Sony WH-1000XM5 problems complaints",
    ],
)


class FakeOxylabs:
    def __init__(self, *args, **kwargs):
        self.searched = []

    def scrape(self, url, run_js=False):
        name = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        html = (
            "<html><head><title>"
            f"{name} product page"
            "</title></head><body><article>"
            f"<h1>{name}</h1>"
            f"<p>{'Detailed product information and specifications. ' * 12}</p>"
            "</article></body></html>"
        )
        return SimpleNamespace(html=html, url=url, status_code=200)

    def search(self, query, engine="yahoo", limit=10):
        self.searched.append((query, engine, limit))
        return [
            SearchResult(
                "The product itself",
                PRODUCT_URL,
                "Official product listing.",
                engine,
            ),
            SearchResult(
                "Independent review",
                "https://reviews.example.com/sony-xm5",
                "Hands-on testing and measurements.",
                engine,
            ),
            SearchResult(
                "Customer discussion",
                "https://forum.example.com/sony-xm5",
                "Owner experiences after six months.",
                engine,
            ),
        ]


class FakeSummarizer:
    def __init__(self):
        self.report_call = None
        self.plan = PLAN

    def derive_research_plan(self, source):
        return self.plan

    def summarize_product_source(self, source, *, primary=False):
        role = "primary" if primary else "independent"
        return SourceSummary(
            title=source.title,
            url=source.url,
            summary=f"{role} evidence from {source.url}",
            model="fake/model",
        )

    def build_product_report(
        self, product, query, summaries, *, product_url="", focus=""
    ):
        self.report_call = {
            "product": product,
            "query": query,
            "summaries": summaries,
            "product_url": product_url,
            "focus": focus,
        }
        return "# 🏆 Overall Verdict\n\n**Verdict Score: 84/100**"


def make_args(**overrides):
    values = {
        "quiet": True,
        "no_ai": False,
        "focus": "",
        "render": False,
        "engine": "yahoo",
        "limit": 10,
        "scrape_count": 5,
        "keywords": "",
        "no_save": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_review_flow_uses_ai_queries_and_never_asks_for_keywords(monkeypatch, tmp_path):
    fake_client = FakeOxylabs()
    fake_summarizer = FakeSummarizer()
    monkeypatch.setattr(app, "OxylabsClient", lambda *args, **kwargs: fake_client)
    monkeypatch.setattr(app, "make_summarizer", lambda settings: fake_summarizer)

    settings = Settings(
        oxylabs_api_key="test",
        openrouter_api_key="test",
        report_dir=tmp_path,
    )

    path = app.run_review_flow(PRODUCT_URL, settings, make_args())

    assert path is not None
    assert path.exists()

    # Every AI-generated query was searched, and the product page itself was
    # filtered out of the merged results each time.
    assert [query for query, _, _ in fake_client.searched] == PLAN.queries
    assert all(engine == "yahoo" for _, engine, _ in fake_client.searched)

    call = fake_summarizer.report_call
    assert call["query"] == ", ".join(PLAN.queries[:5])
    assert call["product"] == "Sony WH-1000XM5"
    assert call["product_url"] == PRODUCT_URL
    assert len(call["summaries"]) == 3
    assert all(summary.url != PRODUCT_URL for summary in call["summaries"][1:])

    saved = path.read_text(encoding="utf-8")
    assert "84/100" in saved
    assert "## Sources" in saved
    assert "_primary product page_" in saved


def test_review_flow_keywords_override_runs_one_search(monkeypatch, tmp_path):
    fake_client = FakeOxylabs()
    fake_summarizer = FakeSummarizer()
    monkeypatch.setattr(app, "OxylabsClient", lambda *args, **kwargs: fake_client)
    monkeypatch.setattr(app, "make_summarizer", lambda settings: fake_summarizer)

    settings = Settings(
        oxylabs_api_key="test",
        openrouter_api_key="test",
        report_dir=tmp_path,
    )

    app.run_review_flow(
        PRODUCT_URL, settings, make_args(keywords="Sony WH-1000XM5 quiet review")
    )

    assert len(fake_client.searched) == 1
    query, _, _ = fake_client.searched[0]
    assert query == "Sony WH-1000XM5 quiet review"
