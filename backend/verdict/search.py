"""Search-engine URL builders and organic-result parsers."""

from __future__ import annotations

from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote_plus,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

from bs4 import BeautifulSoup

from .models import SearchResult

ENGINE_URLS = {
    # Yahoo is the most reliable with Oxylabs' generic Web Scraper API today.
    "yahoo": "https://search.yahoo.com/search?p={query}&n={limit}",
    "brave": "https://search.brave.com/search?q={query}",
    "duckduckgo": "https://html.duckduckgo.com/html/?q={query}",
    "bing": "https://www.bing.com/search?q={query}&count={limit}",
    "google": "https://www.google.com/search?q={query}&num={limit}",
}
ENGINES = tuple(ENGINE_URLS)

_ENGINE_HOSTS = (
    "duckduckgo.com",
    "bing.com",
    "microsoft.com",
    "google.com",
    "googleusercontent.com",
    "gstatic.com",
    "yahoo.com",
    "yimg.com",
)
_TRACKING_PARAMS = {
    "gclid",
    "fbclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}
_BLOCKED_SUFFIXES = (
    ".pdf",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".mp4",
    ".mp3",
)


def build_search_url(engine: str, query: str, limit: int = 10) -> str:
    template = ENGINE_URLS.get(engine)
    if template is None:
        raise ValueError(f"Unsupported search engine: {engine}")
    return template.format(query=quote_plus(query), limit=max(1, min(limit, 20)))


def _clean_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""

    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in _TRACKING_PARAMS
    ]

    path = parsed.path
    if path == "/":
        path = ""

    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            urlencode(query),
            "",
        )
    )


def _is_engine_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == blocked or host.endswith("." + blocked) for blocked in _ENGINE_HOSTS)


def _is_blocked_asset(url: str) -> bool:
    path = (urlparse(url).path or "").lower()
    return path.endswith(_BLOCKED_SUFFIXES)


def _unwrap_duckduckgo(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    full = urljoin("https://duckduckgo.com", href)
    parsed = urlparse(full)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path.startswith(
        "/l/"
    ):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return target[0]
    return full


def _unwrap_yahoo(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.hostname and parsed.hostname.endswith("yahoo.com") and "/RU=" in parsed.path:
        encoded = parsed.path.split("/RU=", 1)[1].split("/", 1)[0]
        decoded = unquote(encoded)
        if decoded.startswith(("http://", "https://")):
            return decoded
    return href


def _unwrap_google(href: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/"):
        href = urljoin("https://www.google.com", href)
    parsed = urlparse(href)
    if parsed.path == "/url":
        target = parse_qs(parsed.query).get("q")
        if target:
            return target[0]
    return href


def _parse_duckduckgo(soup: BeautifulSoup, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for block in soup.select("div.result"):
        classes = block.get("class") or []
        if "result--ad" in classes or "result--ad--small" in classes:
            continue
        anchor = block.select_one("a.result__a")
        if anchor is None or not anchor.get("href"):
            continue
        snippet_tag = block.select_one(".result__snippet")
        results.append(
            SearchResult(
                title=anchor.get_text(" ", strip=True),
                url=_unwrap_duckduckgo(anchor["href"]),
                snippet=snippet_tag.get_text(" ", strip=True) if snippet_tag else "",
                engine="duckduckgo",
            )
        )
        if len(results) >= limit:
            break
    return results


def _parse_yahoo(soup: BeautifulSoup, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for block in soup.select("div.algo"):
        anchor = (
            block.select_one("div.compTitle a[href]")
            or block.select_one("h3 a[href]")
            or block.select_one("a[href]")
        )
        if anchor is None:
            continue
        title_tag = block.select_one("h3") or anchor
        snippet_tag = block.select_one("div.compText") or block.select_one("p")
        results.append(
            SearchResult(
                title=title_tag.get_text(" ", strip=True),
                url=_unwrap_yahoo(anchor["href"]),
                snippet=snippet_tag.get_text(" ", strip=True) if snippet_tag else "",
                engine="yahoo",
            )
        )
        if len(results) >= limit:
            break
    return results


def _parse_brave(soup: BeautifulSoup, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for block in soup.select("div.snippet"):
        anchor = (
            block.select_one("a.title[href]")
            or block.select_one("div.result-content a[href]")
            or block.select_one("a[href]")
        )
        if anchor is None:
            continue
        title_tag = block.select_one(".title") or anchor
        snippet_tag = (
            block.select_one(".generic-snippet")
            or block.select_one(".description")
            or block.select_one(".snippet-content")
        )
        results.append(
            SearchResult(
                title=title_tag.get_text(" ", strip=True),
                url=anchor["href"],
                snippet=snippet_tag.get_text(" ", strip=True) if snippet_tag else "",
                engine="brave",
            )
        )
        if len(results) >= limit:
            break
    return results


def _parse_bing(soup: BeautifulSoup, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for block in soup.select("li.b_algo"):
        anchor = block.select_one("h2 a") or block.select_one("a[href]")
        if anchor is None or not anchor.get("href"):
            continue
        snippet_tag = (
            block.select_one(".b_caption p")
            or block.select_one(".b_snippet")
            or block.select_one("p")
        )
        results.append(
            SearchResult(
                title=anchor.get_text(" ", strip=True),
                url=anchor["href"],
                snippet=snippet_tag.get_text(" ", strip=True) if snippet_tag else "",
                engine="bing",
            )
        )
        if len(results) >= limit:
            break
    return results


def _parse_google(soup: BeautifulSoup, limit: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    for heading in soup.select("#search h3, #rso h3, h3"):
        anchor = heading.find_parent("a")
        if anchor is None:
            anchor = heading.find("a")
        if anchor is None or not anchor.get("href"):
            continue

        block = heading.find_parent("div") or heading.parent
        snippet = ""
        if block is not None:
            text = block.get_text(" ", strip=True)
            title = heading.get_text(" ", strip=True)
            if title in text:
                text = text.replace(title, " ", 1)
            snippet = text.strip()[:400]

        results.append(
            SearchResult(
                title=heading.get_text(" ", strip=True),
                url=_unwrap_google(anchor["href"]),
                snippet=snippet,
                engine="google",
            )
        )
        if len(results) >= limit:
            break
    return results


def _finalize(results: list[SearchResult], limit: int) -> list[SearchResult]:
    cleaned: list[SearchResult] = []
    seen: set[str] = set()

    for result in results:
        url = _clean_url(result.url)
        if not url or _is_engine_host(url) or _is_blocked_asset(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        cleaned.append(
            SearchResult(
                title=result.title.strip(),
                url=url,
                snippet=" ".join(result.snippet.split()),
                engine=result.engine,
            )
        )
        if len(cleaned) >= limit:
            break

    return cleaned


def parse_search_results(html: str, engine: str, limit: int = 10) -> list[SearchResult]:
    """Parse organic results from a search-engine results page."""

    if limit <= 0:
        return []

    soup = BeautifulSoup(html or "", "html.parser")

    if engine == "yahoo":
        raw = _parse_yahoo(soup, limit * 2)
    elif engine == "brave":
        raw = _parse_brave(soup, limit * 2)
    elif engine == "duckduckgo":
        raw = _parse_duckduckgo(soup, limit * 2)
    elif engine == "bing":
        raw = _parse_bing(soup, limit * 2)
    elif engine == "google":
        raw = _parse_google(soup, limit * 2)
    else:
        raise ValueError(f"Unsupported search engine: {engine}")

    return _finalize(raw, limit)
