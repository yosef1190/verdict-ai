"""UI-agnostic research pipeline.

The CLI in ``app.py`` prints progress with ``rich``. The website needs the same
steps but reports progress through a callback instead, so the flows live here
without any terminal code.

Three research modes are supported (Light / Medium / Deep), each with its own
search-query budget, scrape target, and time budget. Independent searches and
scrapes run concurrently where safe so a commercial investigation finishes
inside its target window (Light < 5 min, Medium < 10 min, Deep < 15 min).
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# Research mode configuration: number of targeted search queries, search results
# per query, scrape targets, and time budget (seconds). Per the spec, the query
# count is the number of *targeted searches*, not a cap on accepted sources.
RESEARCH_MODES: dict[str, dict] = {
    "light": {
        "credits": 1,
        "target_seconds": 300,  # under 5 minutes
        "queries": 3,
        "results_per_query": 6,
        "scrape_count": 4,
        "run_js": False,
        "label": "Light",
    },
    "medium": {
        "credits": 2,
        "target_seconds": 600,  # under 10 minutes
        "queries": 4,
        "results_per_query": 8,
        "scrape_count": 6,
        "run_js": False,
        "label": "Medium",
    },
    "deep": {
        "credits": 3,
        "target_seconds": 900,  # under 15 minutes
        "queries": 5,
        "results_per_query": 10,
        "scrape_count": 8,
        "run_js": False,
        "label": "Deep",
    },
}

MODE_CREDIT_COST = {name: cfg["credits"] for name, cfg in RESEARCH_MODES.items()}


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
    mode: str = "light"  # light | medium | deep


@dataclass
class ResearchResult:
    title: str
    markdown: str
    sources: list[dict] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    mode: str = "light"
    stage_timings: dict[str, float] = field(default_factory=dict)
    search_queries: int = 0
    sources_found: int = 0
    sources_accepted: int = 0
    sources_rejected: int = 0
    retry_count: int = 0
    api_failures: int = 0


@dataclass
class StageTimings:
    """Wall-clock timings for each research stage (seconds)."""

    import_time: float = 0.0
    plan_time: float = 0.0
    search_time: float = 0.0
    scrape_time: float = 0.0
    summarize_time: float = 0.0
    report_time: float = 0.0
    total_time: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "import_time": round(self.import_time, 2),
            "plan_time": round(self.plan_time, 2),
            "search_time": round(self.search_time, 2),
            "scrape_time": round(self.scrape_time, 2),
            "summarize_time": round(self.summarize_time, 2),
            "report_time": round(self.report_time, 2),
            "total_time": round(self.total_time, 2),
        }


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

    req.mode = (req.mode or "light").strip().lower()
    if req.mode not in RESEARCH_MODES:
        raise VerdictError(f"Unknown research mode '{req.mode}'.")

    mode_cfg = RESEARCH_MODES[req.mode]

    if req.limit is not None:
        req.limit = max(1, min(int(req.limit), 50))
    else:
        req.limit = mode_cfg["queries"] * mode_cfg["results_per_query"]
    if req.scrape_count is not None:
        req.scrape_count = max(1, min(int(req.scrape_count), 20))
    else:
        req.scrape_count = mode_cfg["scrape_count"]
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


# A short-lived cache of scraped pages. Investigating the same product twice,
# or hitting the same URL from two search branches, should not scrape twice.
_SOURCE_CACHE: dict[tuple[str, bool], tuple[float, Source]] = {}
_SOURCE_CACHE_LOCK = threading.Lock()
_SOURCE_CACHE_TTL = float(os.getenv("VERDICT_SOURCE_CACHE_TTL", "1800") or 1800)
_SOURCE_CACHE_MAX = 250


def _cache_get(key: tuple[str, bool]) -> Source | None:
    if _SOURCE_CACHE_TTL <= 0:
        return None
    with _SOURCE_CACHE_LOCK:
        hit = _SOURCE_CACHE.get(key)
        if hit is None:
            return None
        stored_at, source = hit
        if time.time() - stored_at > _SOURCE_CACHE_TTL:
            _SOURCE_CACHE.pop(key, None)
            return None
        return source


def _cache_put(key: tuple[str, bool], source: Source) -> None:
    if _SOURCE_CACHE_TTL <= 0:
        return
    with _SOURCE_CACHE_LOCK:
        if len(_SOURCE_CACHE) >= _SOURCE_CACHE_MAX:
            # Drop the oldest quarter rather than evicting one at a time.
            for stale in sorted(_SOURCE_CACHE, key=lambda k: _SOURCE_CACHE[k][0])[
                : max(1, _SOURCE_CACHE_MAX // 4)
            ]:
                _SOURCE_CACHE.pop(stale, None)
        _SOURCE_CACHE[key] = (time.time(), source)


def clear_source_cache() -> None:
    with _SOURCE_CACHE_LOCK:
        _SOURCE_CACHE.clear()


def fetch_source(client: OxylabsClient, url: str, *, run_js: bool = False) -> Source:
    key = (url, bool(run_js))
    cached = _cache_get(key)
    if cached is not None:
        return cached

    page = client.scrape(url, run_js=run_js)
    source = extract_page(page.html, page.url or url, status_code=page.status_code)
    if not source.text.strip():
        raise ExtractionError(f"No readable text found at {url}")
    _cache_put(key, source)
    return source


def gather_search_sources(
    client: OxylabsClient,
    results: list[SearchResult],
    progress: Progress,
    *,
    count: int,
    run_js: bool = False,
) -> tuple[list[Source], list[str]]:
    """Scrape search results concurrently (bounded by ``count``)."""

    targets = results[: max(1, count)]
    sources: list[Source] = []
    failures: list[str] = []
    if not targets:
        return sources, failures

    progress(f"Reading {len(targets)} sources concurrently")

    def scrape_one(index: int, result: SearchResult) -> Source | None:
        try:
            return fetch_source(client, result.url, run_js=run_js)
        except (OxylabsError, ExtractionError) as exc:
            if result.snippet:
                return result.as_source(error=short(str(exc), 160))
            failures.append(f"{result.url}: {exc}")
            return None

    workers = min(4, len(targets))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="verdict-scrape") as pool:
        futures = {
            pool.submit(scrape_one, index, result): (index, result)
            for index, result in enumerate(targets, 1)
        }
        for future in as_completed(futures):
            index, result = futures[future]
            try:
                source = future.result()
            except Exception:  # noqa: BLE001 - individual branch failure is tolerated
                source = None
            if source is not None:
                sources.append(source)
                progress(
                    f"Read source {len(sources)}/{len(targets)}: {short(result.title)}"
                )

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


def _evidence_section(summaries: list[SourceSummary], product_url: str) -> str:
    """A short 'Evidence basis' block appended before the sources list.

    Discloses how many sources fall into each classification and flags when the
    evidence base is thin, so a reader can see the limits behind the scores.
    """
    from .evidence import summarize_source_classes

    counts = summarize_source_classes(summaries, product_url=product_url)
    lines = ["## Evidence Basis", ""]
    lines.append(f"Independent sources collected: **{len(summaries)}**")
    lines.append("")
    for name, count in counts.items():
        if count:
            lines.append(f"- {name}: {count}")
    independent = sum(
        counts.get(name, 0)
        for name in (
            "Independent laboratory testing",
            "Independent expert reviews",
            "Established technology publications",
            "Verified purchaser reviews",
            "Community discussions",
        )
    )
    lines.append("")
    if independent == 0:
        lines.append(
            "**Limitation:** no independent sources were collected. Credibility "
            "claims rely mainly on manufacturer information and should be treated "
            "with caution."
        )
    elif independent < 3:
        lines.append(
            "**Limitation:** independent coverage is thin, so Evidence Strength "
            "and Purchasing Confidence are necessarily limited."
        )
    return "\n".join(lines)


def run_parallel_searches(
    client: OxylabsClient,
    queries: list[str],
    progress: Progress,
    *,
    engine: str,
    results_per_query: int,
    primary_urls: set[str],
    deadline: float | None = None,
    max_workers: int = 5,
) -> list[SearchResult]:
    """Run up to ``len(queries)`` targeted searches concurrently.

    A failed branch never terminates the others. Results are deduplicated and
    the product's own page is excluded. Stops early when the time budget is
    exhausted.
    """

    merged: list[SearchResult] = []
    seen: set[str] = set()
    lock_free_urls = set(seen)
    # We gather into per-query lists first to keep ordering deterministic,
    # then merge in query order.
    progress(f"Running {len(queries)} targeted search queries")

    def search_one(query: str) -> list[SearchResult]:
        if deadline is not None and time.monotonic() > deadline:
            return []
        try:
            return client.search(
                query, engine=engine, limit=max(3, results_per_query)
            )
        except OxylabsError:
            return []

    workers = min(max_workers, max(1, len(queries)))
    ordered: dict[int, list[SearchResult]] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="verdict-search") as pool:
        futures = {
            pool.submit(search_one, query): (index, query)
            for index, query in enumerate(queries)
        }
        for future in as_completed(futures):
            index, query = futures[future]
            try:
                ordered[index] = future.result() or []
            except Exception:  # noqa: BLE001 - tolerate a broken branch
                ordered[index] = []

    for index in range(len(queries)):
        for result in ordered.get(index, []):
            if any(same_page(result.url, p) for p in primary_urls) or result.url in seen:
                continue
            seen.add(result.url)
            merged.append(result)

    progress(f"Found {len(merged)} independent results")
    return merged


# --------------------------------------------------------------------------- flows


def run_review(req: ResearchRequest, settings: Settings, progress: Progress) -> ResearchResult:
    started = time.monotonic()
    timings = StageTimings()
    mode_cfg = RESEARCH_MODES.get(req.mode, RESEARCH_MODES["light"])
    deadline = started + mode_cfg["target_seconds"]

    def mark(stage: str, begun: float) -> None:
        setattr(timings, stage, time.monotonic() - begun)

    product_url = normalize_url(req.text)
    if not product_url:
        found = extract_urls(req.text)
        product_url = found[0] if found else ""
    if not product_url:
        raise VerdictError("Enter a valid http(s) product URL.")

    progress(f"{mode_cfg['label']} investigation starting")

    client = _oxylabs(settings)

    progress(f"Identifying product from {short(product_url)}")
    _t = time.monotonic()
    product = fetch_source(client, product_url, run_js=req.render)
    mark("import_time", _t)

    use_ai = _ai_enabled(req, settings)
    summarizer: Summarizer | None = None

    _t = time.monotonic()
    if req.keywords:
        plan = ResearchPlan(queries=[finalize_search_query(req.keywords)])
    elif not use_ai:
        plan = fallback_research_plan(product)
    else:
        summarizer = _summarizer(settings)
        progress("Analyzing the product details")
        plan = summarizer.derive_research_plan(product)

    queries = dedupe_queries(plan.queries) or dedupe_queries(fallback_research_plan(product).queries)
    mark("plan_time", _t)
    if not queries:
        raise VerdictError(
            "Could not determine what to research about this product. Try adding keywords."
        )

    # Cap the query list to the mode's targeted-query budget.
    queries = queries[: mode_cfg["queries"]]

    identity = plan.name or product.title or product_url
    topic = f"{identity} review"
    if plan.name or plan.brand or plan.model or plan.category:
        detail = ", ".join(p for p in (plan.name, plan.model, plan.brand, plan.category) if p)
        progress(f"Product identified: {short(detail, 120)}")

    primary_urls = {product.url, product_url}
    _t = time.monotonic()
    merged = run_parallel_searches(
        client,
        queries,
        progress,
        engine=req.engine,
        results_per_query=mode_cfg["results_per_query"],
        primary_urls=primary_urls,
        deadline=deadline,
    )
    mark("search_time", _t)

    if not merged:
        raise VerdictError("The search returned no independent results for this product.")

    _t = time.monotonic()
    sources, failures = gather_search_sources(
        client, merged, progress, count=req.scrape_count or mode_cfg["scrape_count"], run_js=req.render
    )
    mark("scrape_time", _t)
    if not sources:
        raise VerdictError(
            "None of the independent search results could be scraped:\n"
            + "\n".join(f"- {f}" for f in failures)
        )

    progress("Validating sources")

    counts = dict(
        search_queries=len(queries),
        sources_found=len(merged),
        sources_accepted=len(sources),
        sources_rejected=max(0, len(merged) - len(sources)),
        api_failures=len(failures),
    )

    if not use_ai:
        md = build_raw_report(
            topic, [product, *sources], results=merged,
            note="AI summary disabled or no AI key configured.",
        )
        md += "\n\n" + report_footer([])
        mark("report_time", _t)
        timings.total_time = time.monotonic() - started
        return ResearchResult(topic, md, mode=req.mode, stage_timings=timings.as_dict(), **counts)

    if summarizer is None:
        summarizer = _summarizer(settings)

    summaries: list[SourceSummary] = []
    llm_failures = 0
    _t = time.monotonic()
    progress("Extracting evidence from the product page")
    try:
        summaries.append(summarizer.summarize_product_source(product, primary=True))
    except LLMError:
        llm_failures += 1
    for index, source in enumerate(sources, 1):
        progress(f"Summarizing source {index}/{len(sources)}: {short(source.title)}")
        try:
            summaries.append(summarizer.summarize_product_source(source))
        except LLMError:
            llm_failures += 1
            continue
    mark("summarize_time", _t)
    if not summaries:
        raise VerdictError("The AI could not summarize any of the sources.")

    progress("Analyzing evidence")
    progress("Generating report")
    _t = time.monotonic()
    body = summarizer.build_product_report(
        identity,
        ", ".join(queries[:5]),
        summaries,
        product_url=product.url or product_url,
        focus=req.focus,
    )

    # Validate before delivering. A failed check does not discard a usable
    # report, but it appends a transparent disclosure so we never present an
    # incomplete investigation as fully verified.
    from .evidence import validate_report

    validation = validate_report(
        body,
        summaries,
        product_name=identity,
        product_url=product.url or product_url,
    )
    if not validation.ok:
        progress("Report validation flagged limitations")
        if validation.problems:
            notes = "\n".join(f"> - {p}" for p in validation.problems)
            body += "\n\n> **Validation notes:**\n" + notes

    evidence = _evidence_section(summaries, product.url or product_url)
    tail = product_sources_markdown(product.title or product_url, summaries, product.url or product_url)
    markdown = body.rstrip() + "\n\n" + evidence + "\n\n" + tail
    models = sorted({s.model for s in summaries if s.model})
    mark("report_time", _t)
    timings.total_time = time.monotonic() - started
    counts["api_failures"] += llm_failures
    return ResearchResult(
        topic, markdown, _source_rows(summaries), models,
        mode=req.mode, stage_timings=timings.as_dict(), **counts,
    )


def run_research(
    req: ResearchRequest, settings: Settings, progress: Progress = _noop
) -> ResearchResult:
    return run_review(validate_request(req), settings, progress)