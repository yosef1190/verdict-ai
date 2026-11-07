"""Oxylabs Web Scraper API client for page scraping and search-engine scraping."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import OXYLABS_SCRAPE_ENDPOINT
from .errors import OxylabsError
from .models import SearchResult
from .search import ENGINES, build_search_url, parse_search_results

logger = logging.getLogger(__name__)


@dataclass
class ScrapeResult:
    url: str
    status_code: int
    html: str
    raw: dict[str, Any]


def _error_detail(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("message", "error", "detail"):
            value = data.get(key)
            if value:
                return str(value)[:600]
        return str(data)[:600]
    return str(data)[:600]


def _first_result(data: Any) -> dict[str, Any] | None:
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list) and results:
            first = results[0]
            return first if isinstance(first, dict) else None
        if isinstance(data.get("content"), str) or isinstance(data.get("html"), str):
            return data
    return None


def _result_html(result: dict[str, Any]) -> str:
    for key in ("content", "html", "body"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _result_status(result: dict[str, Any], fallback: int) -> int:
    direct = result.get("status_code")
    if direct:
        try:
            return int(direct)
        except (TypeError, ValueError):
            pass

    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        code = metadata.get("status_code")
        if code:
            try:
                return int(code)
            except (TypeError, ValueError):
                pass

        statuses = metadata.get("statuses")
        if isinstance(statuses, dict):
            for value in statuses.values():
                if isinstance(value, dict) and value.get("code"):
                    try:
                        return int(value["code"])
                    except (TypeError, ValueError):
                        continue

    return fallback


def _result_url(result: dict[str, Any], fallback: str) -> str:
    direct = result.get("url")
    if isinstance(direct, str) and direct.strip():
        return direct

    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        url = metadata.get("url")
        if isinstance(url, str) and url.strip():
            return url

    return fallback


class OxylabsClient:
    """Thin, retrying wrapper around the Oxylabs Web Scraper API."""

    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = OXYLABS_SCRAPE_ENDPOINT,
        timeout: int = 120,
        retries: int = 2,
    ) -> None:
        if not api_key:
            raise OxylabsError(
                "OXYLABS_API_KEY is not set. Add it to .env or pass --oxylabs-key."
            )
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
        )

    def scrape(self, url: str, *, run_js: bool = False) -> ScrapeResult:
        """Fetch a URL through Oxylabs and return its HTML."""

        payload = {"url": url, "output": ["html"], "run_js": bool(run_js)}
        last_error: OxylabsError | None = None

        for attempt in range(self.retries + 1):
            try:
                response = self.session.post(
                    self.endpoint, json=payload, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = OxylabsError(f"Oxylabs request failed: {exc}")
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
                raise last_error from exc

            if response.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                logger.warning(
                    "Oxylabs returned HTTP %s for %s; retrying (%s/%s)",
                    response.status_code,
                    url,
                    attempt + 1,
                    self.retries,
                )
                time.sleep(min(10, 2 ** (attempt + 1)))
                continue

            try:
                data = response.json()
            except ValueError as exc:
                raise OxylabsError(
                    f"Oxylabs returned non-JSON (HTTP {response.status_code}): "
                    f"{response.text[:300]}"
                ) from exc

            if not response.ok:
                raise OxylabsError(
                    f"Oxylabs HTTP {response.status_code}: {_error_detail(data)}"
                )

            result = _first_result(data)
            if result is None:
                raise OxylabsError(f"Oxylabs returned no results: {_error_detail(data)}")

            html = _result_html(result)
            status_code = _result_status(result, response.status_code)

            if status_code >= 400 or not html.strip():
                raise OxylabsError(
                    f"Oxylabs could not fetch {url} (target status {status_code})"
                )

            return ScrapeResult(
                url=_result_url(result, url),
                status_code=status_code,
                html=html,
                raw=data,
            )

        raise last_error or OxylabsError("Oxylabs request failed for an unknown reason")

    def search(
        self,
        query: str,
        *,
        engine: str = "duckduckgo",
        limit: int = 10,
        fallback: bool = True,
    ) -> list[SearchResult]:
        """Scrape a search-engine results page and parse organic results.

        Oxylabs fetches the SERP; the parser extracts titles, URLs, and snippets.
        If the requested engine yields nothing, the other engines are tried in turn.
        Yahoo is the default because it is the most reliable through the generic
        Web Scraper API; Brave, DuckDuckGo, Bing, and Google are also supported.
        """

        if engine not in ENGINES:
            raise OxylabsError(
                f"Unknown search engine '{engine}'. Choose from: {', '.join(ENGINES)}"
            )

        order = [engine]
        if fallback:
            order.extend(candidate for candidate in ENGINES if candidate != engine)

        errors: list[str] = []
        for name in order:
            search_url = build_search_url(name, query, limit)
            try:
                page = self.scrape(search_url, run_js=(name == "google"))
            except OxylabsError as exc:
                errors.append(f"{name}: {exc}")
                continue

            results = parse_search_results(page.html, name, limit)
            if results:
                if name != engine:
                    logger.info("Fell back to %s for query %r", name, query)
                return results
            errors.append(f"{name}: no organic results parsed")

        raise OxylabsError(
            "Search failed on every engine:\n" + "\n".join(f"- {item}" for item in errors)
        )
