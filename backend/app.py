#!/usr/bin/env python3
"""Verdict Research — Oxylabs scraping/search + NVIDIA NIM reports (Gemini, then OpenRouter, as fallbacks)."""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.table import Table

from verdict import __version__
from verdict.config import Settings
from verdict.errors import ExtractionError, LLMError, OxylabsError, VerdictError
from verdict.extract import extract_page, extract_urls, normalize_url
from verdict.models import ResearchPlan, SearchResult, Source, SourceSummary
from verdict.llm import ai_available, build_llm
from verdict.openrouter_client import fetch_free_models
from verdict.oxylabs_client import OxylabsClient
from verdict.product import (
    fallback_research_plan,
    finalize_search_query,
    same_page,
)
from verdict.report import (
    build_raw_report,
    product_sources_markdown,
    report_footer,
    save_report,
    sources_markdown,
)
from verdict.search import ENGINES
from verdict.summarizer import Summarizer

console = Console()
err_console = Console(stderr=True)


def short(value: str, limit: int = 62) -> str:
    value = " ".join(str(value).split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


@contextmanager
def working(message: str, quiet: bool = False) -> Iterator[object | None]:
    safe = escape(message)
    if quiet:
        yield None
    elif console.is_terminal:
        with console.status(f"[cyan]{safe}[/cyan]", spinner="dots") as status:
            yield status
    else:
        err_console.print(f"[dim]{safe}[/dim]")
        yield None


def update_status(status: object | None, message: str) -> None:
    if status is not None and hasattr(status, "update"):
        status.update(f"[cyan]{escape(message)}[/cyan]")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--model",
        action="append",
        metavar="MODEL",
        help="OpenRouter fallback model id (repeatable). Overrides OPENROUTER_MODELS.",
    )
    common.add_argument("--out", type=Path, metavar="DIR", help="Report output directory.")
    common.add_argument("--max-chars", type=int, metavar="N", help="Max characters per source sent to the AI.")
    common.add_argument("--workers", type=int, metavar="N", help="Concurrent page scrapes.")
    common.add_argument("--focus", default="", metavar="TOPIC", help="Steer the summary toward a topic.")
    common.add_argument(
        "--render",
        action="store_true",
        help="Run JavaScript before extracting pages (slower, uses more Oxylabs credits).",
    )
    common.add_argument("--no-ai", action="store_true", help="Scrape only; skip AI summarization.")
    common.add_argument("--no-save", action="store_true", help="Do not write a Markdown report file.")
    common.add_argument("--quiet", action="store_true", help="Hide progress messages and search table.")
    common.add_argument("--verbose", action="store_true", help="Show debug logging from HTTP clients.")

    search_options = argparse.ArgumentParser(add_help=False)
    search_options.add_argument("--limit", type=int, default=8, metavar="N", help="Search results to fetch (default 8).")
    search_options.add_argument(
        "--scrape",
        dest="scrape_count",
        type=int,
        default=3,
        metavar="N",
        help="Top results to scrape and summarize (default 3).",
    )
    search_options.add_argument(
        "--engine",
        choices=ENGINES,
        default="yahoo",
        help="Search engine to scrape (default yahoo; others are fallbacks).",
    )

    review_options = argparse.ArgumentParser(add_help=False)
    review_options.add_argument(
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Search results to fetch (default 10).",
    )
    review_options.add_argument(
        "--scrape",
        dest="scrape_count",
        type=int,
        default=5,
        metavar="N",
        help="Top independent sources to scrape and summarize (default 5).",
    )
    review_options.add_argument(
        "--engine",
        choices=ENGINES,
        default="yahoo",
        help="Search engine to scrape (default yahoo; others are fallbacks).",
    )
    review_options.add_argument(
        "--keywords",
        default="",
        metavar="QUERY",
        help="Optional override for the AI-generated research queries.",
    )

    parser = argparse.ArgumentParser(
        prog="verdict",
        description="Scrape and search the web with Oxylabs, then get an AI research report from NVIDIA NIM (Gemini, then OpenRouter, as fallbacks).",
    )
    parser.add_argument("--version", action="version", version=f"Verdict Research {__version__}")
    parser.add_argument("--oxylabs-key", metavar="KEY", help="Oxylabs API key (overrides .env).")
    parser.add_argument("--nvidia-key", metavar="KEY", help="NVIDIA NIM API key (overrides .env).")
    parser.add_argument("--gemini-key", metavar="KEY", help="Gemini fallback API key (overrides .env).")
    parser.add_argument("--openrouter-key", metavar="KEY", help="OpenRouter fallback API key (overrides .env).")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape = subparsers.add_parser(
        "scrape", parents=[common], help="Scrape one URL and write a report."
    )
    scrape.add_argument("url", help="Page URL to scrape.")

    search = subparsers.add_parser(
        "search", parents=[common, search_options], help="Search the web, scrape top hits, and compare them."
    )
    search.add_argument("query", help="Search query.")

    review = subparsers.add_parser(
        "review",
        parents=[common, review_options],
        help="Research a product page and write a 100-point Verdict report.",
    )
    review.add_argument(
        "url",
        nargs="?",
        help="Product page URL (prompted for when omitted).",
    )

    run = subparsers.add_parser(
        "run", parents=[common, search_options], help="Auto-detect a pasted URL or a search query."
    )
    run.add_argument("input", nargs="+", help="URL or search query.")

    subparsers.add_parser(
        "interactive",
        parents=[common, search_options],
        help="Paste links or type searches in a loop.",
    )

    models = subparsers.add_parser("models", help="List currently free OpenRouter models.")
    models.add_argument("--limit", type=int, default=100, metavar="N", help="Max models to show.")

    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    return Settings.from_env(
        oxylabs_api_key=getattr(args, "oxylabs_key", None),
        nvidia_api_key=getattr(args, "nvidia_key", None),
        gemini_api_key=getattr(args, "gemini_key", None),
        openrouter_api_key=getattr(args, "openrouter_key", None),
        models=getattr(args, "model", None),
        report_dir=getattr(args, "out", None),
        max_chars=getattr(args, "max_chars", None),
        max_workers=getattr(args, "workers", None),
    )


def configure_logging(args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
        force=True,
    )


def fetch_source(client: OxylabsClient, url: str, *, run_js: bool = False) -> Source:
    page = client.scrape(url, run_js=run_js)
    source = extract_page(page.html, page.url or url, status_code=page.status_code)
    if not source.text.strip():
        raise ExtractionError(f"No readable text found at {url}")
    return source


def fetch_sources(
    client: OxylabsClient,
    urls: list[str],
    settings: Settings,
    *,
    quiet: bool,
    run_js: bool = False,
) -> list[Source]:
    normalized: list[str] = []
    for raw_url in urls:
        url = normalize_url(raw_url)
        if url and url not in normalized:
            normalized.append(url)

    if not normalized:
        raise VerdictError("No valid http(s) URL found.")

    sources: dict[str, Source] = {}
    failures: list[str] = []

    if len(normalized) == 1:
        url = normalized[0]
        with working(f"Scraping {short(url)} with Oxylabs…", quiet):
            try:
                sources[url] = fetch_source(client, url, run_js=run_js)
            except (OxylabsError, ExtractionError) as exc:
                failures.append(f"{url}: {exc}")
    else:
        workers = max(1, min(settings.max_workers, len(normalized)))
        with working(f"Scraping {len(normalized)} pages with Oxylabs…", quiet) as status:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(fetch_source, client, url, run_js=run_js): url
                    for url in normalized
                }
                for future in as_completed(futures):
                    url = futures[future]
                    try:
                        sources[url] = future.result()
                    except Exception as exc:  # isolate per-URL failures
                        failures.append(f"{url}: {exc}")
                    update_status(
                        status,
                        f"Scraped {len(sources) + len(failures)}/{len(normalized)} pages…",
                    )

    if not quiet:
        for failure in failures:
            err_console.print(f"[yellow]Skipped:[/yellow] {escape(failure)}")

    ordered = [sources[url] for url in normalized if url in sources]
    if not ordered:
        raise VerdictError("Every page failed:\n" + "\n".join(f"- {item}" for item in failures))
    return ordered


def make_summarizer(settings: Settings) -> Summarizer:
    return Summarizer(build_llm(settings), settings)


def summarize_sources(
    summarizer: Summarizer,
    sources: list[Source],
    *,
    focus: str,
    quiet: bool,
) -> list[SourceSummary]:
    summaries: list[SourceSummary] = []
    total = len(sources)

    for index, source in enumerate(sources, 1):
        with working(f"Summarizing {index}/{total}: {short(source.title)}…", quiet):
            summaries.append(summarizer.summarize_page(source, focus))

    return summaries


def present_report(
    markdown: str,
    topic: str,
    settings: Settings,
    args: argparse.Namespace,
) -> Path | None:
    path = None
    if not getattr(args, "no_save", False):
        path = save_report(markdown, settings.report_dir, topic)

    if not getattr(args, "quiet", False):
        console.print()
        console.print(Markdown(markdown))

    if path is not None and not getattr(args, "quiet", False):
        console.print(f"\n[green]Report saved:[/green] {escape(str(path))}")

    return path


def run_link_flow(urls: list[str], settings: Settings, args: argparse.Namespace) -> Path | None:
    client = OxylabsClient(
        settings.oxylabs_api_key,
        endpoint=settings.oxylabs_endpoint,
        timeout=settings.timeout,
    )
    sources = fetch_sources(
        client, urls, settings, quiet=args.quiet, run_js=getattr(args, "render", False)
    )
    topic = sources[0].title if len(sources) == 1 else f"Pasted pages ({len(sources)})"

    if args.no_ai:
        markdown = build_raw_report(
            topic,
            sources,
            note="AI summary disabled or no AI key configured.",
        )
        markdown += "\n\n" + report_footer([])
        return present_report(markdown, topic, settings, args)

    summarizer = make_summarizer(settings)
    summaries = summarize_sources(summarizer, sources, focus=args.focus, quiet=args.quiet)

    with working("Writing the AI report…", args.quiet):
        body = summarizer.build_report(
            topic,
            summaries,
            focus=args.focus,
            kind="link" if len(summaries) == 1 else "multi",
        )

    models = sorted({summary.model for summary in summaries if summary.model})
    markdown = (
        body.rstrip()
        + "\n\n"
        + sources_markdown(summaries)
        + "\n\n"
        + report_footer(models)
    )
    return present_report(markdown, topic, settings, args)


def print_search_table(query: str, results: list[SearchResult]) -> None:
    table = Table(title=f"Top results for: {short(query, 70)}", title_justify="left")
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Title", style="bold", max_width=48, overflow="fold")
    table.add_column("URL", style="blue", max_width=52, overflow="fold")
    table.add_column("Snippet", max_width=60, overflow="fold")

    for index, result in enumerate(results, 1):
        table.add_row(
            str(index),
            short(result.title, 90),
            result.url,
            short(result.snippet, 140),
        )

    console.print(table)


def gather_search_sources(
    client: OxylabsClient,
    results: list[SearchResult],
    *,
    count: int,
    quiet: bool,
    run_js: bool = False,
) -> tuple[list[Source], list[str]]:
    targets = results[: max(1, count)]
    sources: list[Source] = []
    failures: list[str] = []

    for index, result in enumerate(targets, 1):
        with working(f"Scraping {index}/{len(targets)}: {short(result.title)}…", quiet):
            try:
                sources.append(fetch_source(client, result.url, run_js=run_js))
            except (OxylabsError, ExtractionError) as exc:
                if result.snippet:
                    sources.append(result.as_source(error=short(str(exc), 160)))
                    if not quiet:
                        err_console.print(
                            f"[yellow]Partial:[/yellow] {escape(result.url)} — using search snippet"
                        )
                else:
                    failures.append(f"{result.url}: {exc}")

    return sources, failures


def run_search_flow(query: str, settings: Settings, args: argparse.Namespace) -> Path | None:
    query = query.strip()
    if not query:
        raise VerdictError("Enter a search query.")

    client = OxylabsClient(
        settings.oxylabs_api_key,
        endpoint=settings.oxylabs_endpoint,
        timeout=settings.timeout,
    )

    with working(f"Searching {args.engine} for “{short(query)}”…", args.quiet):
        results = client.search(query, engine=args.engine, limit=args.limit)

    if not results:
        raise VerdictError("The search returned no usable results.")

    if not args.quiet:
        print_search_table(query, results)

    sources, failures = gather_search_sources(
        client,
        results,
        count=args.scrape_count,
        quiet=args.quiet,
        run_js=getattr(args, "render", False),
    )

    if not sources:
        raise VerdictError(
            "None of the top results could be scraped:\n"
            + "\n".join(f"- {item}" for item in failures)
        )

    if args.no_ai:
        markdown = build_raw_report(
            query,
            sources,
            results=results,
            note="AI summary disabled or no AI key configured.",
        )
        markdown += "\n\n" + report_footer([])
        return present_report(markdown, query, settings, args)

    summarizer = make_summarizer(settings)
    summaries = summarize_sources(summarizer, sources, focus=args.focus, quiet=args.quiet)

    with working("Comparing sources and writing the report…", args.quiet):
        body = summarizer.build_report(query, summaries, focus=args.focus, kind="multi")

    models = sorted({summary.model for summary in summaries if summary.model})
    markdown = (
        body.rstrip()
        + "\n\n"
        + sources_markdown(summaries)
        + "\n\n"
        + report_footer(models)
    )
    return present_report(markdown, query, settings, args)


def resolve_product_url(value: str) -> str:
    raw = " ".join(str(value or "").split())
    if not raw:
        if not console.is_terminal:
            raise VerdictError("A product URL is required.")
        try:
            raw = console.input(
                "[bold cyan]Product URL[/bold cyan] [dim]›[/dim] "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            raise VerdictError("A product URL is required.")

    url = normalize_url(raw)
    if not url:
        urls = extract_urls(raw)
        url = urls[0] if urls else ""
    if not url:
        raise VerdictError("Enter a valid http(s) product URL.")
    return url


def dedupe_queries(queries: Iterable[str]) -> list[str]:
    """Trim, drop empties and near-identical repeats, preserving order."""

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


def summarize_product_pages(
    summarizer: Summarizer,
    product: Source,
    sources: list[Source],
    *,
    quiet: bool,
) -> list[SourceSummary]:
    summaries: list[SourceSummary] = []

    with working("Extracting evidence from the product page…", quiet):
        try:
            summaries.append(
                summarizer.summarize_product_source(product, primary=True)
            )
        except LLMError as exc:
            if not quiet:
                err_console.print(
                    f"[yellow]Skipped product page summary:[/yellow] {escape(str(exc))}"
                )

    total = len(sources)
    for index, source in enumerate(sources, 1):
        with working(f"Summarizing source {index}/{total}: {short(source.title)}…", quiet):
            try:
                summaries.append(summarizer.summarize_product_source(source))
            except LLMError as exc:
                if not quiet:
                    err_console.print(
                        f"[yellow]Skipped source:[/yellow] {escape(str(exc))}"
                    )

    return summaries


def run_review_flow(
    url: str, settings: Settings, args: argparse.Namespace
) -> Path | None:
    product_url = resolve_product_url(url)
    client = OxylabsClient(
        settings.oxylabs_api_key,
        endpoint=settings.oxylabs_endpoint,
        timeout=settings.timeout,
    )

    with working(f"Scraping product page {short(product_url)}…", args.quiet):
        product = fetch_source(
            client, product_url, run_js=getattr(args, "render", False)
        )

    summarizer: Summarizer | None = None
    manual_query = str(getattr(args, "keywords", "") or "").strip()
    if manual_query:
        plan = ResearchPlan(queries=[finalize_search_query(manual_query)])
    elif args.no_ai:
        plan = fallback_research_plan(product)
    else:
        summarizer = make_summarizer(settings)
        with working("AI is analyzing the product details…", args.quiet):
            plan = summarizer.derive_research_plan(product)

    queries = dedupe_queries(plan.queries)
    if not queries:
        queries = dedupe_queries(fallback_research_plan(product).queries)
    if not queries:
        raise VerdictError(
            "Could not determine what to research about this product. "
            "Try --keywords."
        )

    identity = plan.name or product.title or product_url
    topic = f"{identity} review"

    if not args.quiet:
        if plan.name or plan.brand or plan.model or plan.category:
            detail = ", ".join(
                part
                for part in (plan.name, plan.model, plan.brand, plan.category)
                if part
            )
            console.print(f"[cyan]Product identified:[/cyan] {escape(short(detail, 120))}")
        if plan.claims:
            console.print(
                f"[cyan]Seller claims to verify:[/cyan] "
                f"{escape(short(' | '.join(plan.claims[:3]), 160))}"
            )
        console.print("[cyan]Research topics selected:[/cyan]")
        for index, query in enumerate(queries, 1):
            console.print(f"  {index}. {escape(query)}")

    limit = max(1, int(getattr(args, "limit", 10)))
    primary_urls = {product.url, product_url}
    merged: list[SearchResult] = []
    seen_urls: set[str] = set()

    for query in queries:
        if len(merged) >= limit:
            break
        with working(f"Searching {args.engine} for “{short(query)}”…", args.quiet):
            try:
                found = client.search(
                    query,
                    engine=args.engine,
                    limit=max(3, min(10, limit - len(merged))),
                )
            except OxylabsError as exc:
                if not args.quiet:
                    err_console.print(
                        f"[yellow]Search failed for “{short(query, 60)}”:[/yellow] "
                        f"{escape(short(str(exc), 160))} — continuing."
                    )
                continue

        for result in found:
            if any(same_page(result.url, primary) for primary in primary_urls):
                continue
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            merged.append(result)
            if len(merged) >= limit:
                break

    if not merged:
        raise VerdictError(
            "The search returned no independent results for this product."
        )

    if not args.quiet:
        print_search_table(
            ", ".join(queries[:3]),
            merged,
        )

    sources, failures = gather_search_sources(
        client,
        merged,
        count=int(getattr(args, "scrape_count", 5)),
        quiet=args.quiet,
        run_js=getattr(args, "render", False),
    )
    if not sources:
        raise VerdictError(
            "None of the independent search results could be scraped:\n"
            + "\n".join(f"- {item}" for item in failures)
        )

    if args.no_ai:
        markdown = build_raw_report(
            topic,
            [product, *sources],
            results=merged,
            note="AI summary disabled or no AI key configured.",
        )
        markdown += "\n\n" + report_footer([])
        return present_report(markdown, topic, settings, args)

    if summarizer is None:
        summarizer = make_summarizer(settings)

    summaries = summarize_product_pages(
        summarizer, product, sources, quiet=args.quiet
    )
    if not summaries:
        raise VerdictError("The AI could not summarize any of the sources.")

    with working("Writing the Verdict report…", args.quiet):
        body = summarizer.build_product_report(
            identity,
            ", ".join(queries[:5]),
            summaries,
            product_url=product.url or product_url,
            focus=args.focus,
        )

    models = sorted({summary.model for summary in summaries if summary.model})
    markdown = (
        body.rstrip()
        + "\n\n"
        + product_sources_markdown(
            product.title or product_url,
            summaries,
            product.url or product_url,
        )
        + "\n\n"
        + report_footer(models)
    )
    return present_report(markdown, topic, settings, args)


def run_auto(text: str, settings: Settings, args: argparse.Namespace) -> Path | None:
    url = normalize_url(text)
    urls = [url] if url else extract_urls(text)

    if urls:
        return run_link_flow(urls, settings, args)
    if not text.strip():
        raise VerdictError("Enter a URL or a search query.")
    return run_search_flow(text.strip(), settings, args)


def print_free_models(limit: int, settings: Settings, quiet: bool = False) -> int:
    with working("Fetching OpenRouter's free model list…", quiet):
        models = fetch_free_models(settings.openrouter_models_endpoint, limit=limit)

    if not models:
        err_console.print("[yellow]OpenRouter returned no free models right now.[/yellow]")
        return 1

    table = Table(title="OpenRouter free models", title_justify="left")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Model id", style="bold", overflow="fold")
    table.add_column("Context", justify="right")

    for index, model in enumerate(models, 1):
        context = model.get("context_length") or 0
        table.add_row(
            str(index),
            model["id"],
            f"{context:,}" if context else "?",
        )

    console.print(table)
    console.print(
        "[dim]Set OPENROUTER_MODELS to a comma-separated list, "
        "e.g. OPENROUTER_MODELS=model/a:free,model/b:free[/dim]"
    )
    return 0


def print_banner(settings: Settings, no_ai: bool) -> None:
    if no_ai:
        ai_state = "AI: off (extract-only)"
    else:
        chain = []
        if settings.nvidia_api_key:
            chain.append(f"NVIDIA ({', '.join(settings.nvidia_models[:2])})")
        if settings.gemini_api_key:
            chain.append("Gemini")
        if settings.openrouter_api_key:
            chain.append("OpenRouter")
        ai_state = "AI: " + " → ".join(chain) if chain else "AI: not configured"

    console.print(
        f"[bold]Verdict Research[/bold] [dim]v{__version__}[/dim]  "
        f"[dim]Oxylabs scraping · AI reports[/dim]"
    )
    console.print(
        f"[dim]{escape(ai_state)} · Reports: {escape(str(settings.report_dir))}[/dim]"
    )


def print_interactive_help() -> None:
    console.print(
        Markdown(
            "Paste a URL to scrape and summarize it. Type anything else to search the web.\n\n"
            "**Commands**\n"
            "- `/review <url>` — research a product and write a Verdict report\n"
            "- `/focus <topic>` — steer summaries toward a topic\n"
            "- `/clearfocus` — clear the focus\n"
            "- `/models` — list free OpenRouter models\n"
            "- `/help` — show this help\n"
            "- `/quit` — exit"
        )
    )


def interactive(settings: Settings, args: argparse.Namespace) -> int:
    print_banner(settings, args.no_ai)
    print_interactive_help()
    focus = args.focus

    while True:
        try:
            raw = console.input("\n[bold cyan]verdict[/bold cyan] [dim]›[/dim] ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        text = raw.strip()
        if not text:
            continue

        lowered = text.casefold()
        if lowered in {"/quit", "/exit", "quit", "exit", "q"}:
            break

        if lowered in {"/help", "help", "?"}:
            print_interactive_help()
            continue

        if lowered == "/models":
            try:
                print_free_models(20, settings, quiet=args.quiet)
            except LLMError as exc:
                err_console.print(f"[red]Error:[/red] {escape(str(exc))}")
            continue

        if lowered == "/review" or lowered.startswith("/review "):
            target = text[len("/review") :].strip()
            args.focus = focus
            try:
                run_review_flow(target, settings, args)
            except VerdictError as exc:
                err_console.print(f"[red]Error:[/red] {escape(str(exc))}")
            continue

        if lowered.startswith("/focus"):
            focus = text[len("/focus") :].strip()
            console.print(
                f"[cyan]Focus:[/cyan] {escape(focus)}"
                if focus
                else "[cyan]Focus cleared.[/cyan]"
            )
            continue

        if lowered == "/clearfocus":
            focus = ""
            console.print("[cyan]Focus cleared.[/cyan]")
            continue

        args.focus = focus
        try:
            run_auto(text, settings, args)
        except VerdictError as exc:
            err_console.print(f"[red]Error:[/red] {escape(str(exc))}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args)

    try:
        settings = settings_from_args(args)

        if args.command == "models":
            return print_free_models(args.limit, settings, quiet=getattr(args, "quiet", False))

        if not settings.oxylabs_api_key:
            console.print(
                "[red]OXYLABS_API_KEY is missing.[/red] Add it to .env "
                "or pass --oxylabs-key."
            )
            return 2

        if not getattr(args, "no_ai", False) and not ai_available(settings):
            console.print(
                "[yellow]No NVIDIA_API_KEY, GEMINI_API_KEY or OPENROUTER_API_KEY is set — running in extract-only mode.[/yellow]"
            )
            args.no_ai = True

        if args.command == "scrape":
            run_link_flow([args.url], settings, args)
        elif args.command == "search":
            run_search_flow(args.query, settings, args)
        elif args.command == "review":
            run_review_flow(args.url or "", settings, args)
        elif args.command == "run":
            run_auto(" ".join(args.input), settings, args)
        elif args.command == "interactive":
            return interactive(settings, args)

        return 0
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return 130
    except VerdictError as exc:
        err_console.print(f"[red]Error:[/red] {escape(str(exc))}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
