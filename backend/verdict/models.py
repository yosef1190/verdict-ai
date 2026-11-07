"""Small data containers shared across the pipeline."""

from __future__ import annotations

from dataclasses import field, dataclass


@dataclass
class Source:
    """A fetched page (or a search-result snippet standing in for one)."""

    url: str
    title: str
    text: str
    description: str = ""
    site_name: str = ""
    author: str = ""
    published: str = ""
    status_code: int = 200
    error: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.text.strip())


@dataclass
class SourceSummary:
    """AI summary of a single source."""

    title: str
    url: str
    summary: str
    model: str = ""
    snippet: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class ResearchPlan:
    """AI-generated research plan for a product page."""

    name: str = ""
    brand: str = ""
    model: str = ""
    category: str = ""
    claims: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """One organic search result."""

    title: str
    url: str
    snippet: str = ""
    engine: str = ""

    def as_source(self, error: str = "") -> Source:
        return Source(
            url=self.url,
            title=self.title or self.url,
            text=self.snippet,
            description=self.snippet,
            error=error,
        )
