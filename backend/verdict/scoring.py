"""The Verdict 0-100 score bands, and a post-processor that enforces them.

The AI writes the score; the label for that score always comes from this table,
so a model can never print a recommendation that disagrees with the number.
"""

from __future__ import annotations

import re
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


_SCORE = re.compile(r"Verdict\s+Score\s*:?\s*\**\s*(\d{1,3})(?:\.\d+)?\s*\**\s*/\s*100", re.I)
_RECOMMENDATION_LINE = re.compile(r"^[ \t]*\**[ \t]*Recommendation\s*:.*$", re.I | re.M)
_FINAL_VERDICT = re.compile(
    r"(\*\*Verdict:\s*)[^\n—–-]*?(\s*[—–-]\s*)(\d{1,3})(\s*/\s*100\*\*)", re.I
)


def find_score(markdown: str) -> int | None:
    match = _SCORE.search(markdown)
    if not match:
        return None
    return max(0, min(100, int(match.group(1))))


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
