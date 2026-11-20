"""Evidence classification, product identity matching, and report validation.

This module implements the credibility-verification layer the commercial product
needs:

  * Source classification into the eight required categories.
  * Exact product identity verification (reject unrelated products).
  * Claim-level evidence tracking with the four required statuses.
  * Pre-delivery report validation (citations, scores, limitations).

Everything here is deterministic: it never calls an LLM and never invents data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .models import SourceSummary
from .scoring import extract_scores

# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------

# Ordered most-reliable first. A host can match several; the earliest wins.
SOURCE_CLASSES: tuple[str, ...] = (
    "Independent laboratory testing",
    "Independent expert reviews",
    "Established technology publications",
    "Verified purchaser reviews",
    "Community discussions",
    "Manufacturer documentation",
    "Affiliate content",
    "Unverified content",
)

_LAB_HOSTS = (
    "consumerreports.org",
    "rtings.com",
    "anandtech.com",
    "tomshardware.com",
    "techpowerup.com",
    "notebookcheck.net",
    "wirecutter.com",
)

_EXPERT_HOSTS = (
    "cnet.com",
    "theverge.com",
    "engadget.com",
    "pcmag.com",
    "techradar.com",
    "whathifi.com",
    "trustedreviews.com",
    "reviewed.usatoday.com",
)

_TECH_PUB_HOSTS = (
    "arstechnica.com",
    "wired.com",
    "zdnet.com",
    "tomsguide.com",
    "digitaltrends.com",
    "androidcentral.com",
    "9to5mac.com",
    "xda-developers.com",
    "macrumors.com",
)

_PURCHASER_HOSTS = (
    "amazon.",
    "bestbuy.com",
    "walmart.com",
    "target.com",
    "bhphotovideo.com",
    "newegg.com",
    "etsy.com",
    "trustpilot.com",
    "reevoo.com",
    "which.co.uk",
)

_COMMUNITY_HOSTS = (
    "reddit.com",
    "quora.com",
    "stackexchange.com",
    "slickdeals.net",
    "forums.macrumors.com",
    "avforums.com",
    "head-fi.org",
)

_AFFILIATE_MARKERS = (
    "/aff/",
    "?tag=",
    "/ref=",
    "affiliate",
    "utm_source=affiliate",
    "awin1.com",
    "shareasale.com",
    "impact.com",
)


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _matches(host: str, hosts: tuple[str, ...]) -> bool:
    return any(marker in host for marker in hosts)


def classify_source(summary: SourceSummary, *, product_url: str = "") -> str:
    """Return one of SOURCE_CLASSES for a summarised source.

    Classification uses the URL host and a couple of cheap heuristics. It is
    intentionally conservative: anything unrecognised is "Unverified content",
    and a source on the product's own page is "Manufacturer documentation".
    """
    url = (summary.url or "").lower()
    host = _host(url)

    if product_url and _same_host(host, product_url):
        return "Manufacturer documentation"

    if any(marker in url for marker in _AFFILIATE_MARKERS):
        return "Affiliate content"

    if _matches(host, _LAB_HOSTS):
        return "Independent laboratory testing"
    if _matches(host, _EXPERT_HOSTS):
        return "Independent expert reviews"
    if _matches(host, _TECH_PUB_HOSTS):
        return "Established technology publications"
    if _matches(host, _PURCHASER_HOSTS):
        return "Verified purchaser reviews"
    if _matches(host, _COMMUNITY_HOSTS):
        return "Community discussions"

    # Anything we cannot identify is treated as unverified. In particular we do
    # NOT assume an unknown domain is the manufacturer: that would silently
    # promote marketing copy to a source class it has not earned.
    return "Unverified content"


def _same_host(host: str, product_url: str) -> bool:
    if not host or not product_url:
        return False
    product_host = _host(product_url)
    if not product_host:
        return False
    return host == product_host or host.endswith("." + product_host) or product_host.endswith("." + host)


# ---------------------------------------------------------------------------
# Product identity verification
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "plus", "pro", "max",
    "new", "series", "model", "edition", "pack", "set", "kit", "inch", "inches",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _model_numbers(text: str) -> set[str]:
    """Extract model-like tokens: e.g. A140A, B0GS5M96KD, X1000."""
    return {token.upper() for token in re.findall(r"\b[A-Z]{0,3}\d{2,}[A-Z0-9]*\b", text or "")}


@dataclass
class IdentityCheck:
    accepted: bool
    score: float
    reason: str
    matched_tokens: set[str] = field(default_factory=set)
    matched_models: set[str] = field(default_factory=set)


def verify_product_identity(
    product_name: str,
    *,
    source_title: str,
    source_summary: str = "",
    product_model: str = "",
    product_asin: str = "",
    threshold: float = 0.35,
) -> IdentityCheck:
    """Decide whether a source really discusses the product being researched.

    The product name tokens and any known model / ASIN are compared with the
    source title and summary. Unrelated products sharing a brand are rejected:
    e.g. an Anker charging-station review is not evidence about an Anker Nano
    charger.
    """
    text = f"{source_title} {source_summary}"
    source_tokens = _tokens(text)
    source_models = _model_numbers(f"{source_title} {source_summary}")
    product_tokens = _tokens(product_name)

    if product_asin and product_asin.upper() in text.upper():
        return IdentityCheck(True, 1.0, "ASIN matched in source", product_tokens, {product_asin.upper()})

    if product_model:
        wanted = _model_numbers(product_model)
        if wanted & source_models:
            return IdentityCheck(
                True, 1.0, "Model number matched in source",
                product_tokens, wanted & source_models,
            )

    if not product_tokens:
        return IdentityCheck(False, 0.0, "No identifiable product tokens")

    overlap = product_tokens & source_tokens
    score = len(overlap) / len(product_tokens) if product_tokens else 0.0

    if score >= threshold:
        return IdentityCheck(
            True, score,
            f"Product token overlap {score:.0%}",
            overlap, set(),
        )
    return IdentityCheck(
        False, score,
        f"Product token overlap only {score:.0%} (likely a different product)",
        overlap, set(),
    )


# ---------------------------------------------------------------------------
# Claim-level evidence tracking
# ---------------------------------------------------------------------------

CLAIM_VERIFIED = "VERIFIED"
CLAIM_MANUFACTURER = "MANUFACTURER CLAIM"
CLAIM_UNVERIFIED = "UNVERIFIED"
CLAIM_CONTRADICTED = "CONTRADICTED"


@dataclass
class ClaimEvidence:
    text: str
    source_url: str
    source_title: str
    source_type: str
    exact_product_match: bool
    status: str
    supporting_evidence: str = ""
    confidence: str = "medium"  # low | medium | high


# ---------------------------------------------------------------------------
# Report validation
# ---------------------------------------------------------------------------

_CITATION = re.compile(r"\[(\d{1,2})\]")


@dataclass
class ValidationResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    scores: dict[str, int | None] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"ok": self.ok, "problems": self.problems, "scores": self.scores}


def validate_report(
    markdown: str,
    summaries: list[SourceSummary],
    *,
    product_name: str = "",
    product_url: str = "",
    require_scores: bool = True,
) -> ValidationResult:
    """Run the automated pre-delivery checks from the spec.

    Checks that every citation points at a real collected source, that the
    three scores are present and internally consistent, and that limitations
    are disclosed when evidence is thin.
    """
    problems: list[str] = []
    scores = extract_scores(markdown)

    if not markdown or not markdown.strip():
        return ValidationResult(False, ["Report is empty"], {})

    # 1. Citations must refer to collected sources.
    cited = {int(value) for value in _CITATION.findall(markdown)}
    source_count = len(summaries)
    bad = {index for index in cited if index < 1 or index > source_count}
    if bad:
        problems.append(f"Citations out of range: {sorted(bad)} (only {source_count} sources)")

    # 2. The three component scores should be present.
    if require_scores:
        missing = [
            label
            for label, key in (
                ("Verdict Score", "verdict"),
                ("Product Credibility", "product_credibility"),
                ("Evidence Strength", "evidence_strength"),
                ("Purchasing Confidence", "purchasing_confidence"),
            )
            if scores.get(key) is None
        ]
        if missing:
            problems.append(f"Missing scores: {', '.join(missing)}")

    # 3. Overall verdict should not wildly outrun evidence strength.
    verdict = scores.get("verdict")
    evidence = scores.get("evidence_strength")
    if verdict is not None and evidence is not None and verdict > evidence + 45:
        problems.append(
            f"Verdict ({verdict}) is far above Evidence Strength ({evidence}); "
            "the conclusion is stronger than the evidence."
        )

    # 4. Limitations should be disclosed when evidence is thin.
    lowered = markdown.casefold()
    has_limitation_language = any(
        phrase in lowered
        for phrase in (
            "limited evidence",
            "insufficient evidence",
            "not enough evidence",
            "insufficient reliable",
            "evidence is thin",
            "limited information",
            "limited independent",
            "limited testing",
            "no independent",
            "unverified",
            "could not verify",
        )
    )
    if (evidence is not None and evidence < 55) and not has_limitation_language:
        problems.append("Evidence is weak but the report does not disclose the limitation.")

    # 5. Delivered report should not claim certainty with no customer evidence.
    if "no customer" not in lowered and "customer" in lowered:
        if re.search(r"customers (love|hate|overwhelmingly)", lowered) and not cited:
            problems.append("Customer sentiment claimed without cited evidence.")

    return ValidationResult(not problems, problems, scores)


def summarize_source_classes(summaries: list[SourceSummary], product_url: str = "") -> dict[str, int]:
    """Count sources per class, for the evidence-section breakdown."""
    counts: dict[str, int] = {name: 0 for name in SOURCE_CLASSES}
    for summary in summaries:
        counts[classify_source(summary, product_url=product_url)] += 1
    return counts