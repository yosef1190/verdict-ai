"""Product-page helpers that work without an AI call."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from .models import ResearchPlan, Source

_MARKETPLACES = (
    "amazon.com",
    "amazon",
    "walmart.com",
    "walmart",
    "ebay",
    "etsy",
    "best buy",
    "target",
    "aliexpress",
    "temu",
    "shein",
)

_PRICE_RE = re.compile(
    r"(?:US\s*\$|USD\s*|\$|£|€)\s*\d[\d,]*(?:\.\d{1,2})?",
    re.IGNORECASE,
)
_MARKETPLACE_PREFIX_RE = re.compile(
    r"^\s*(?:" + "|".join(re.escape(name) for name in _MARKETPLACES) + r")\s*[:\-|]\s*",
    re.IGNORECASE,
)
_MARKETPLACE_SUFFIX_RE = re.compile(
    r"\s*[:\-|]\s*(?:" + "|".join(re.escape(name) for name in _MARKETPLACES) + r")\s*$",
    re.IGNORECASE,
)
_BOILERPLATE_RE = re.compile(
    r"\b(?:free (?:shipping|delivery)|in stock|add to cart|buy now|prime delivery)\b",
    re.IGNORECASE,
)
_QUERY_PARAM_KEYS = ("k", "q", "query", "keyword", "keywords", "search")
_QUERY_RE = re.compile(r"[^\w\s'&+./-]", re.UNICODE)
_SLUG_ID_RE = re.compile(r"^(?:b0[a-z0-9]{8}|[a-z]?\d{5,}|ref=.*|\d+)$", re.IGNORECASE)


def clean_product_title(title: str) -> str:
    """Remove store names, prices, and listing boilerplate from a title."""

    text = " ".join(str(title or "").split())
    if not text:
        return ""

    text = _MARKETPLACE_PREFIX_RE.sub("", text)
    text = _MARKETPLACE_SUFFIX_RE.sub("", text)
    text = _PRICE_RE.sub(" ", text)
    text = _BOILERPLATE_RE.sub(" ", text)

    segments = re.split(r"\s+[:\|]\s+", text)
    while (
        len(segments) > 1
        and len(segments[-1]) <= 40
        and not re.search(r"\d", segments[-1])
    ):
        segments.pop()
    text = " : ".join(segments)

    return " ".join(text.split()).strip(" -:|•·—–")


def _query_from_url(url: str) -> str:
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    for key in _QUERY_PARAM_KEYS:
        for value in params.get(key, []):
            candidate = " ".join(unquote(value).split())
            if candidate:
                return candidate
    return ""


def _slug_from_url(url: str) -> str:
    parsed = urlparse(url)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if not segments:
        return ""

    for index, segment in enumerate(segments):
        marker = segment.casefold()
        if marker == "gp" and index + 1 < len(segments):
            if segments[index + 1].casefold() == "product":
                continue
        if marker in {"dp", "gp", "product", "products", "ip", "item"}:
            if marker in {"product", "products", "ip", "item"} and index + 1 < len(segments):
                segments = [*segments[:index], segments[index + 1]]
            else:
                segments = segments[:index]
            break

    for segment in reversed(segments):
        slug = re.sub(r"\.[a-z0-9]{2,5}$", "", segment, flags=re.IGNORECASE)
        if _SLUG_ID_RE.match(slug):
            continue
        words = [part for part in re.split(r"[-_+]+", slug) if part]
        if len(words) < 2:
            continue
        candidate = " ".join(words)
        if re.search(r"[A-Za-z]", candidate):
            return candidate
    return ""


def _is_store_name(value: str) -> bool:
    lowered = value.casefold().strip(" .:|•·—–")
    return any(
        lowered == name or lowered == name.removesuffix(".com")
        for name in _MARKETPLACES
    )


def _first_sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    sentence = re.split(r"(?<=[.!?])\s+", text)[0]
    return sentence[:160]


def finalize_search_query(query: str) -> str:
    query = " ".join(str(query or "").split())
    query = _QUERY_RE.sub(" ", query)
    query = " ".join(query.split()).strip(" -:|•·—–,.;")
    if len(query) > 120:
        query = query[:120].rsplit(" ", 1)[0].rstrip(" -:|•·—–,.;")

    lowered = query.casefold()
    if query and not lowered.endswith((" review", " reviews", " review)")):
        query = f"{query} review"
    return query


def fallback_research_plan(source: Source) -> ResearchPlan:
    """Build a research plan without the AI, from title and URL only."""

    name = clean_product_title(source.title)
    if not name or _is_store_name(name):
        name = ""

    queries = [fallback_search_query(source)]
    if name:
        base = " ".join(name.split())
        for suffix in ("problems complaints", "scam fake"):
            variant = " ".join(f"{base} {suffix}".split())[:120].strip()
            if variant not in queries and re.search(r"[A-Za-z]", variant):
                queries.append(variant)

    return ResearchPlan(name=name, queries=queries)


def fallback_search_query(source: Source) -> str:
    """Build a reasonable review query from a product page without the AI."""

    query = _query_from_url(source.url)
    if query:
        return finalize_search_query(query)

    title = clean_product_title(source.title)
    if (
        len(title) >= 4
        and re.search(r"[A-Za-z]", title)
        and not _is_store_name(title)
    ):
        return finalize_search_query(title)

    query = _slug_from_url(source.url) or _first_sentence(source.description)
    return finalize_search_query(query) or "product review"


def _product_key(url: str) -> str:
    path = urlparse(url).path
    match = re.search(
        r"/(?:dp|gp/product|product|d|clp|aw/d)/([a-z0-9]{10})(?:[/?#]|$)",
        path,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper()

    for segment in path.split("/"):
        if (
            re.fullmatch(r"[a-z0-9]{10}", segment, re.IGNORECASE)
            and re.search(r"\d", segment)
            and re.search(r"[a-z]", segment, re.IGNORECASE)
        ):
            return segment.upper()
    return ""


def same_page(left: str, right: str) -> bool:
    """Return True when two URLs point at the same page, ignoring tracking."""

    if not left or not right:
        return False

    left_key = _product_key(left)
    if left_key and left_key == _product_key(right):
        return True

    def parts(value: str) -> tuple[str, str]:
        parsed = urlparse(value)
        host = (parsed.hostname or "").casefold()
        host = host[4:] if host.startswith("www.") else host
        path = parsed.path.rstrip("/") or "/"
        return host, path

    return parts(left) == parts(right)
