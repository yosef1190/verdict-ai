"""Turn raw HTML into clean text plus useful metadata."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .models import Source

try:  # Trafilatura is much better at isolating article text, but it is optional.
    import trafilatura
except Exception:  # pragma: no cover - only hit when the dependency is absent
    trafilatura = None


_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?::\d{2,5})?(?:[/?#].*)?$",
    re.IGNORECASE,
)
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

_NOISE_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "iframe",
    "form",
    "button",
    "nav",
    "footer",
    "header",
    "aside",
    "template",
)

_META_KEYS = {
    "title": ("og:title", "twitter:title"),
    "description": ("description", "og:description", "twitter:description"),
    "site_name": ("og:site_name", "application-name"),
    "author": ("author", "article:author", "twitter:creator"),
    "published": (
        "article:published_time",
        "og:published_time",
        "datePublished",
        "pubdate",
        "date",
    ),
}


def _meta(soup: BeautifulSoup, keys: tuple[str, ...]) -> str:
    for key in keys:
        tag = soup.find("meta", attrs={"property": key}) or soup.find(
            "meta", attrs={"name": key}
        )
        if tag:
            content = (tag.get("content") or "").strip()
            if content:
                return content
    return ""


def _title(soup: BeautifulSoup) -> str:
    titled = _meta(soup, _META_KEYS["title"])
    if titled:
        return " ".join(titled.split())

    if soup.title and soup.title.string:
        text = " ".join(soup.title.string.split())
        if text:
            return text

    heading = soup.find("h1")
    if heading:
        text = " ".join(heading.get_text(" ", strip=True).split())
        if text:
            return text

    return ""


def _canonical(soup: BeautifulSoup, url: str) -> str:
    link = soup.find("link", rel=lambda value: value and "canonical" in value)
    if link and link.get("href"):
        return urljoin(url, link["href"])
    return url


def _published(soup: BeautifulSoup) -> str:
    value = _meta(soup, _META_KEYS["published"])
    if value:
        return value
    time_tag = soup.find("time")
    if time_tag:
        return (time_tag.get("datetime") or time_tag.get_text(" ", strip=True) or "").strip()
    return ""


def _site_name(soup: BeautifulSoup, url: str) -> str:
    name = _meta(soup, _META_KEYS["site_name"])
    if name:
        return name
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def clean_text(text: str) -> str:
    """Normalize whitespace and drop obvious repeated boilerplate lines."""

    text = text.replace("\xa0", " ").replace("\u200b", "")
    lines: list[str] = []
    seen: set[str] = set()

    for raw_line in text.splitlines():
        line = _WHITESPACE_RE.sub(" ", raw_line).strip()
        if not line:
            if lines and lines[-1] != "":
                lines.append("")
            continue

        key = line.casefold()
        if key in seen and len(line) < 140:
            continue
        seen.add(key)
        lines.append(line)

    cleaned = "\n".join(lines).strip()
    return _BLANK_LINES_RE.sub("\n\n", cleaned)


def _main_text(html: str, soup: BeautifulSoup, url: str) -> str:
    if trafilatura is not None:
        try:
            text = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=True,
                include_links=False,
                favor_recall=True,
            )
        except Exception:
            text = None
        if text and len(text.strip()) >= 200:
            return text

    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    for tag in soup.select("[hidden], [aria-hidden='true']"):
        tag.decompose()

    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"role": "main"})
        or soup.find(id=re.compile(r"(content|main|article)", re.I))
        or soup.body
        or soup
    )
    return main.get_text("\n")


def extract_page(html: str, url: str, status_code: int = 200) -> Source:
    """Extract readable text and metadata from an HTML document."""

    soup = BeautifulSoup(html or "", "html.parser")

    title = _title(soup)
    description = _meta(soup, _META_KEYS["description"])
    site_name = _site_name(soup, url)
    author = _meta(soup, _META_KEYS["author"])
    published = _published(soup)
    canonical = _canonical(soup, url)

    text = clean_text(_main_text(html or "", soup, url))
    if len(text) < 80 and description:
        text = description

    if not title:
        title = urlparse(canonical).hostname or canonical

    return Source(
        url=canonical or url,
        title=title,
        text=text,
        description=description,
        site_name=site_name,
        author=author,
        published=published,
        status_code=status_code,
    )


def truncate(text: str, max_chars: int, marker: str = "\n\n[… content truncated …]\n\n") -> str:
    """Keep the start and end of very long text within a character budget."""

    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head_chars = int(max_chars * 0.7)
    tail_chars = max_chars - head_chars
    return text[:head_chars].rstrip() + marker + text[-tail_chars:].lstrip()


def chunk_text(text: str, size: int = 12_000, overlap: int = 600) -> list[str]:
    """Split text into overlapping chunks, preferring paragraph boundaries."""

    if size <= 0:
        return [text]
    if len(text) <= size:
        return [text]

    overlap = max(0, min(overlap, size // 2))
    chunks: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + size, length)
        if end < length:
            boundary = text.rfind("\n\n", start + size // 2, end)
            if boundary != -1:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, start + 1)

    return chunks or [text]


def normalize_url(value: str) -> str:
    """Return a usable http(s) URL, or an empty string."""

    value = value.strip().strip("<>\"'")
    if not value or any(character.isspace() for character in value):
        return ""

    if value.startswith("//"):
        value = "https:" + value

    if value.lower().startswith(("http://", "https://")):
        parsed = urlparse(value)
        return value if parsed.netloc else ""

    if _DOMAIN_RE.match(value):
        return "https://" + value

    return ""


def extract_urls(text: str) -> list[str]:
    """Find http(s) URLs inside free-form input, preserving order."""

    found: list[str] = []
    for match in _URL_IN_TEXT_RE.finditer(text):
        url = match.group(0).rstrip(").,;:!?'\"]}>")
        if url and url not in found:
            found.append(url)
    return found
