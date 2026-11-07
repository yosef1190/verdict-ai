"""UI-agnostic research pipeline.

The CLI in ``app.py`` prints progress with ``rich``. The website needs the same
steps but reports progress through a callback instead, so the flows live here
without any terminal code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from .config import Settings
from .errors import ExtractionError, LLMError, OxylabsError, VerdictError
from .extract import extract_page, extract_urls, normalize_url
from .models import ResearchPlan, SearchResult, Source, SourceSummary
from .llm import ai_available, build_llm
from .oxylabs_client import OxylabsClient
from .product import fallback_research_plan, finalize_search_query, same_page
from .report import (
    build_raw_report,
    product_sources_markdown,
    report_footer,
)
from .search import ENGINES
from .summarizer import Summarizer

Progress = Callable[[str], None]

def _noop(_message: str) -> None:
    return None


def short(value: str, limit: int = 62) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


@dataclass
class ResearchRequest:
    text: str = ""
    keywords: str = ""
    focus: str = ""
    engine: str = "yahoo"
    render: bool = False
    no_ai: bool = False
    limit: int | None = None
    scrape_count: int | None = None


@dataclass
class ResearchResult:
    title: str
    markdown: str
    sources: list[dict] = field(default_factory=list)
    models: list[str] = field(default_factory=list)


def validate_request(req: ResearchRequest) -> ResearchRequest:
    """Clamp and sanity-check user input. Raises VerdictError on bad input."""

    req.text = " ".join(str(req.text or "").split())
    if not req.text:
        raise VerdictError("Paste a product URL.")
    if len(req.text) > 2000:
        raise VerdictError("Input is too long.")

    req.keywords = " ".join(str(req.keywords or "").split())[:300]
    req.focus = " ".join(str(req.focus or "").split())[:300]

    req.engine = (req.engine or "yahoo").strip().lower()
    if req.engine not in ENGINES:
        raise VerdictError(f"Unknown search engine '{req.engine}'.")

    if req.limit is not None:
        req.limit = max(1, min(int(req.limit), 20))
    if req.scrape_count is not None:
        req.scrape_count = max(1, min(int(req.scrape_count), 10))
    return req


def _oxylabs(settings: Settings) -> OxylabsClient:
    if not settings.oxylabs_api_key:
        raise VerdictError("OXYLABS_API_KEY is not configured on the server.")
    return OxylabsClient(
        settings.oxylabs_api_key,
        endpoint=settings.oxylabs_endpoint,
        timeout=settings.timeout,
    )


def _summarizer(settings: Settings) -> Summarizer:
    return Summarizer(build_llm(settings), settings)


def _ai_enabled(req: ResearchRequest, settings: Settings) -> bool:
    return not req.no_ai and ai_available(settings)


def fetch_source(client: OxylabsClient, url: str, *, run_js: bool = False) -> Source:
    page = client.scrape(url, run_js=run_js)
    source = extract_page(page.html, page.url or url, status_code=page.status_code)
    if not source.text.strip():
        raise ExtractionError(f"No readable text found at {url}")
    return source


def gather_search_sources(
    client: OxylabsClient,
    results: list[SearchResult],
    progress: Progress,
    *,
    count: int,
    run_js: bool = False,
) -> tuple[list[Source], list[str]]:
    targets = results[: max(1, count)]
    sources: list[Source] = []
    failures: list[str] = []
    for index, result in enumerate(targets, 1):
        progress(f"Reading source {index}/{len(targets)}: {short(result.title)}")
        try:
            sources.append(fetch_source(client, result.url, run_js=run_js))
        except (OxylabsError, ExtractionError) as exc:
            if result.snippet:
                sources.append(result.as_source(error=short(str(exc), 160)))
            else:
                failures.append(f"{result.url}: {exc}")
    return sources, failures


def dedupe_queries(queries: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for query in queries:
        query = " ".join(str(query or "").split()).strip(" \"'`*")
        if len(query) < 4:
            continue
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(query)
    return cleaned


def _source_rows(summaries: list[SourceSummary]) -> list[dict]:
    return [
        {"title": s.title or s.url, "url": s.url, "partial": bool(s.error)}
        for s in summaries
    ]


def _finish(body: str, tail: str, summaries: list[SourceSummary]) -> tuple[str, list[str]]:
    models = sorted({s.model for s in summaries if s.model})
    markdown = body.rstrip() + "\n\n" + tail + "\n\n" + report_footer(models)
    return markdown, models


# --------------------------------------------------------------------------- flows


def run_review(req: ResearchRequest, settings: Settings, progress: Progress) -> ResearchResult:
    product_url = normalize_url(req.text)
    if not product_url:
        found = extract_urls(req.text)
        product_url = found[0] if found else ""
    if not product_url:
        raise VerdictError("Enter a valid http(s) product URL.")

    client = _oxylabs(settings)
    progress(f"Scraping product page {short(product_url)}")
    product = fetch_source(client, product_url, run_js=req.render)

    use_ai = _ai_enabled(req, settings)
    summarizer: Summarizer | None = None

    if req.keywords:
        plan = ResearchPlan(queries=[finalize_search_query(req.keywords)])
    elif not use_ai:
        plan = fallback_research_plan(product)
    else:
        summarizer = _summarizer(settings)
        progress("Analyzing the product details")
        plan = summarizer.derive_research_plan(product)

    queries = dedupe_queries(plan.queries) or dedupe_queries(fallback_research_plan(product).queries)
    if not queries:
        raise VerdictError(
            "Could not determine what to research about this product. Try adding keywords."
        )

    identity = plan.name or product.title or product_url
    topic = f"{identity} review"
    if plan.name or plan.brand or plan.model or plan.category:
        detail = ", ".join(p for p in (plan.name, plan.model, plan.brand, plan.category) if p)
        progress(f"Product identified: {short(detail, 120)}")
    progress(f"Researching {len(queries)} topic{'s' if len(queries) != 1 else ''}")

    limit = req.limit or 10
    primary_urls = {product.url, product_url}
    merged: list[SearchResult] = []
    seen: set[str] = set()

    for query in queries:
        if len(merged) >= limit:
            break
        progress(f"Searching for “{short(query)}”")
        try:
            found = client.search(query, engine=req.engine, limit=max(3, min(10, limit - len(merged))))
        except OxylabsError:
            continue
        for result in found:
            if any(same_page(result.url, p) for p in primary_urls) or result.url in seen:
                continue
            seen.add(result.url)
            merged.append(result)
            if len(merged) >= limit:
                break

    if not merged:
        raise VerdictError("The search returned no independent results for this product.")
    progress(f"Found {len(merged)} independent results")

    sources, failures = gather_search_sources(
        client, merged, progress, count=req.scrape_count or 5, run_js=req.render
    )
    if not sources:
        raise VerdictError(
            "None of the independent search results could be scraped:\n"
            + "\n".join(f"- {f}" for f in failures)
        )

    if not use_ai:
        md = build_raw_report(
            topic, [product, *sources], results=merged,
            note="AI summary disabled or no AI key configured.",
        )
        md += "\n\n" + report_footer([])
        return ResearchResult(topic, md)

    if summarizer is None:
        summarizer = _summarizer(settings)

    summaries: list[SourceSummary] = []
    progress("Extracting evidence from the product page")
    try:
        summaries.append(summarizer.summarize_product_source(product, primary=True))
    except LLMError:
        pass
    for index, source in enumerate(sources, 1):
        progress(f"Summarizing source {index}/{len(sources)}: {short(source.title)}")
        try:
            summaries.append(summarizer.summarize_product_source(source))
        except LLMError:
            continue
    if not summaries:
        raise VerdictError("The AI could not summarize any of the sources.")

    progress("Writing the Verdict report")
    body = summarizer.build_product_report(
        identity,
        ", ".join(queries[:5]),
        summaries,
        product_url=product.url or product_url,
        focus=req.focus,
    )
    tail = product_sources_markdown(product.title or product_url, summaries, product.url or product_url)
    md, models = _finish(body, tail, summaries)
    return ResearchResult(topic, md, _source_rows(summaries), models)


def run_research(
    req: ResearchRequest, settings: Settings, progress: Progress = _noop
) -> ResearchResult:
    return run_review(validate_request(req), settings, progress)
