"""The Verdict 0-100 rubric, bands, and deterministic score post-processing.

The model supplies one integer per rubric category. Code computes the three
component totals and the overall Verdict Score, and the band label always comes
from this table, so a model can never print a recommendation that disagrees with
the number.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Band:
    low: int
    high: int
    emoji: str
    label: str
    meaning: str

    @property
    def title(self) -> str:
        return f"{self.emoji} {self.label}"

    @property
    def range(self) -> str:
        return f"{self.low}–{self.high}"


BANDS: tuple[Band, ...] = (
    Band(0, 10, "🚨", "Avoid Completely",
         "Extremely high risk; strong warning signs outweigh any positives."),
    Band(11, 20, "🔴", "Strongly Not Recommended",
         "Too many serious concerns to justify buying."),
    Band(21, 30, "🔴", "Not Recommended",
         "Significant negative evidence and reliability concerns."),
    Band(31, 40, "🟠", "Proceed with Extreme Caution",
         "Major concerns make this a risky choice."),
    Band(41, 50, "🟠", "Questionable Choice",
         "Mixed evidence, with risks that deserve careful consideration."),
    Band(51, 60, "🟡", "Proceed with Caution",
         "Acceptable in some areas, but important concerns remain."),
    Band(61, 70, "🟡", "Generally Decent",
         "Mostly positive, though there are notable drawbacks."),
    Band(71, 80, "🟢", "Recommended",
         "Strong overall choice with relatively few concerns."),
    Band(81, 90, "🟢", "Highly Recommended",
         "Very positive evidence and strong overall reliability."),
    Band(91, 100, "🏆", "Top Recommendation",
         "Exceptional overall credibility with minimal concerns."),
)

SCORE_WEIGHTS: dict[str, dict[str, int]] = {
    "product_credibility": {
        "product_legitimacy": 20,
        "specification_consistency": 15,
        "independent_performance_evidence": 20,
        "customer_experiences": 15,
        "reliability_and_durability": 10,
        "safety": 5,
        "brand_credibility": 10,
        "seller_authenticity": 5,
    },
    "evidence_strength": {
        "source_reliability": 25,
        "independent_source_coverage": 20,
        "exact_product_matching": 15,
        "claim_verification": 15,
        "source_recency": 10,
        "source_diversity": 10,
        "evidence_consistency": 5,
    },
    "purchasing_confidence": {
        "available_evidence": 35,
        "unresolved_risks": 25,
        "source_contradictions": 15,
        "missing_critical_information": 15,
        "confidence_in_the_recommendation": 10,
    },
}


def band_for(score: int) -> Band:
    score = max(0, min(100, int(score)))
    for band in BANDS:
        if band.low <= score <= band.high:
            return band
    return BANDS[-1]  # unreachable; keeps type checkers happy


def interpretation_markdown() -> str:
    """The table shown to the AI in its system prompt."""

    return "\n".join(
        f"- **{band.range}: {band.title}** — {band.meaning}" for band in BANDS
    )


def recommendation_labels() -> str:
    return " / ".join(band.title for band in BANDS)


def score_schema_markdown() -> str:
    lines = ["```json", "{"]
    entries = list(SCORE_WEIGHTS.items())
    for index, (score, categories) in enumerate(entries):
        suffix = "," if index < len(entries) - 1 else ""
        lines.append(f'  "{score}": {{')
        categories_list = list(categories.items())
        for cat_index, (category, maximum) in enumerate(categories_list):
            cat_suffix = "," if cat_index < len(categories_list) - 1 else ""
            lines.append(f'    "{category}": "0-{maximum}"{cat_suffix}')
        lines.append(f"  }}{suffix}")
    lines.append("}")
    lines.append("```")
    return "\n".join(lines)


def _normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _as_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def normalize_score_json(payload: object) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    if not isinstance(payload, Mapping):
        return normalized
    for score, categories in payload.items():
        key = _normalize_key(score)
        if key not in SCORE_WEIGHTS or not isinstance(categories, Mapping):
            continue
        values: dict[str, float] = {}
        for category, value in categories.items():
            number = _as_number(value)
            if number is not None:
                values[_normalize_key(category)] = number
        normalized[key] = values
    return normalized


def parse_score_json(markdown: str) -> dict[str, dict[str, float]]:
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", markdown, re.I | re.S)
    decoder = json.JSONDecoder()
    payloads: list[object] = []
    for block in blocks:
        try:
            payloads.append(json.loads(block))
        except json.JSONDecodeError:
            continue
    for match in re.finditer(r"\{", markdown):
        try:
            payload, _ = decoder.raw_decode(markdown[match.start() :])
        except json.JSONDecodeError:
            continue
        payloads.append(payload)
    for payload in reversed(payloads):
        normalized = normalize_score_json(payload)
        if normalized:
            return normalized
    return {}


def compute_score_totals(
    category_scores: Mapping[str, Mapping[str, object]],
) -> dict[str, int]:
    normalized = normalize_score_json(category_scores)
    totals: dict[str, int] = {}
    for score, weights in SCORE_WEIGHTS.items():
        values = normalized.get(score, {})
        total = 0.0
        for category, maximum in weights.items():
            value = values.get(category)
            if value is None:
                continue
            total += max(0.0, min(float(maximum), float(value)))
        totals[score] = int(total + 0.5)
    totals["verdict"] = int(
        sum(totals.values()) / len(totals) + 0.5
    )
    return totals


_SCORE = re.compile(r"Verdict\s+Score\s*:?\s*\**\s*(\d{1,3})(?:\.\d+)?\s*\**\s*/\s*100", re.I)
_CREDIBILITY = re.compile(r"Product\s+Credibility\s*:?\s*\**\s*(\d{1,3})(?:\.\d+)?\s*\**\s*/\s*100", re.I)
_EVIDENCE = re.compile(r"Evidence\s+Strength\s*:?\s*\**\s*(\d{1,3})(?:\.\d+)?\s*\**\s*/\s*100", re.I)
_PURCHASE_CONFIDENCE = re.compile(
    r"Purchasing\s+Confidence\s*:?\s*\**\s*(\d{1,3})(?:\.\d+)?\s*\**\s*/\s*100", re.I
)
_RECOMMENDATION_LINE = re.compile(r"^[ \t]*\**[ \t]*Recommendation\s*:.*$", re.I | re.M)
_FINAL_VERDICT = re.compile(
    r"(\*\*Verdict:\s*)[^\n—–-]*?(\s*[—–-]\s*)(\d{1,3})(\s*/\s*100\*\*)", re.I
)


def find_score(markdown: str) -> int | None:
    match = _SCORE.search(markdown)
    if not match:
        return None
    return max(0, min(100, int(match.group(1))))


def find_product_credibility(markdown: str) -> int | None:
    match = _CREDIBILITY.search(markdown)
    if not match:
        return None
    return max(0, min(100, int(match.group(1))))


def find_evidence_strength(markdown: str) -> int | None:
    match = _EVIDENCE.search(markdown)
    if not match:
        return None
    return max(0, min(100, int(match.group(1))))


def find_purchasing_confidence(markdown: str) -> int | None:
    match = _PURCHASE_CONFIDENCE.search(markdown)
    if not match:
        return None
    return max(0, min(100, int(match.group(1))))


def extract_scores(markdown: str) -> dict[str, int | None]:
    """Return the four scores found in a report (None when absent)."""

    return {
        "verdict": find_score(markdown),
        "product_credibility": find_product_credibility(markdown),
        "evidence_strength": find_evidence_strength(markdown),
        "purchasing_confidence": find_purchasing_confidence(markdown),
    }


def apply_score_bands(markdown: str) -> str:
    """Rewrite the Recommendation line (and the Final Recommendation verdict line)
    so the label always matches the score."""

    score = find_score(markdown)
    if score is None:
        return markdown

    band = band_for(score)
    replacement = f"**Recommendation: {band.title}** — {band.meaning}"

    if _RECOMMENDATION_LINE.search(markdown):
        markdown = _RECOMMENDATION_LINE.sub(replacement, markdown, count=1)
    else:
        # No recommendation line written: insert one right after the score line.
        lines = markdown.split("\n")
        for index, line in enumerate(lines):
            if _SCORE.search(line):
                lines[index + 1 : index + 1] = ["", replacement]
                break
        markdown = "\n".join(lines)

    def fix_final(match: re.Match[str]) -> str:
        return f"{match.group(1)}{band.title}{match.group(2)}{score}{match.group(4)}"

    return _FINAL_VERDICT.sub(fix_final, markdown)


_SCORE_LINES: dict[str, re.Pattern[str]] = {
    label: re.compile(
        rf"({re.escape(label)}\s*:?\s*\**\s*)(\d{{1,3}})(?:\.\d+)?(\s*\**\s*/\s*100)",
        re.I,
    )
    for label in (
        "Verdict Score",
        "Product Credibility",
        "Evidence Strength",
        "Purchasing Confidence",
    )
}
_JSON_BLOCK = re.compile(r"\n?```(?:json)?\s*\{.*?\}\s*```\s*\n?", re.I | re.S)


def _rewrite_score_line(markdown: str, label: str, value: int) -> str:
    pattern = _SCORE_LINES[label]
    replacement = rf"\g<1>{value}\g<3>"
    rewritten, count = pattern.subn(replacement, markdown, count=1)
    if count:
        return rewritten
    lines = markdown.split("\n")
    for index, line in enumerate(lines):
        if re.search(r"Overall Verdict", line, re.I):
            lines[index + 1 : index + 1] = ["", f"**{label}: {value}/100**"]
            return "\n".join(lines)
    return f"**{label}: {value}/100**\n\n" + markdown


def apply_structured_scores(
    markdown: str, category_scores: Mapping[str, Mapping[str, object]]
) -> tuple[str, dict[str, int]]:
    totals = compute_score_totals(category_scores)
    markdown = _JSON_BLOCK.sub("\n", markdown)
    for label, key in (
        ("Verdict Score", "verdict"),
        ("Product Credibility", "product_credibility"),
        ("Evidence Strength", "evidence_strength"),
        ("Purchasing Confidence", "purchasing_confidence"),
    ):
        markdown = _rewrite_score_line(markdown, label, totals[key])
    return apply_score_bands(markdown), totals
