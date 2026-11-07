import pytest

from verdict.scoring import BANDS, apply_score_bands, band_for, find_score
from verdict.verdict_prompt import VERDICT_SYSTEM_PROMPT


@pytest.mark.parametrize(
    "score,label",
    [
        (0, "Avoid Completely"), (10, "Avoid Completely"),
        (11, "Strongly Not Recommended"), (20, "Strongly Not Recommended"),
        (21, "Not Recommended"), (30, "Not Recommended"),
        (31, "Proceed with Extreme Caution"), (40, "Proceed with Extreme Caution"),
        (41, "Questionable Choice"), (50, "Questionable Choice"),
        (51, "Proceed with Caution"), (60, "Proceed with Caution"),
        (61, "Generally Decent"), (70, "Generally Decent"),
        (71, "Recommended"), (80, "Recommended"),
        (81, "Highly Recommended"), (90, "Highly Recommended"),
        (91, "Top Recommendation"), (100, "Top Recommendation"),
    ],
)
def test_band_boundaries(score, label):
    assert band_for(score).label == label


def test_bands_cover_0_to_100_without_gaps():
    covered = [n for b in BANDS for n in range(b.low, b.high + 1)]
    assert covered == list(range(0, 101))


def test_band_clamps_out_of_range():
    assert band_for(-5).label == "Avoid Completely"
    assert band_for(250).label == "Top Recommendation"


def test_prompt_contains_every_band():
    for band in BANDS:
        assert band.title in VERDICT_SYSTEM_PROMPT
    assert "@@BANDS@@" not in VERDICT_SYSTEM_PROMPT


def test_find_score_variants():
    assert find_score("**Verdict Score: 78/100**") == 78
    assert find_score("Verdict Score: **64** / 100") == 64
    assert find_score("no score here") is None


def test_wrong_ai_label_is_corrected():
    md = (
        "# 🏆 Overall Verdict\n\n**Verdict Score: 34/100**\n\n"
        "**Recommendation: Highly Recommended**\n\n**Confidence: Low**\n\nSummary.\n\n"
        "## 🧠 Final Recommendation\n\n**Verdict: Worth Considering — 34/100**\n"
    )
    out = apply_score_bands(md)
    assert "**Recommendation: 🟠 Proceed with Extreme Caution**" in out
    assert "Highly Recommended" not in out
    assert "**Verdict: 🟠 Proceed with Extreme Caution — 34/100**" in out


def test_missing_recommendation_line_is_inserted():
    md = "# 🏆 Overall Verdict\n\n**Verdict Score: 95/100**\n\n**Confidence: High**\n"
    out = apply_score_bands(md)
    assert "**Recommendation: 🏆 Top Recommendation**" in out
    assert out.index("Recommendation") < out.index("Confidence")


def test_no_score_leaves_text_untouched():
    md = "# Overall Verdict\n\nNothing numeric."
    assert apply_score_bands(md) == md


def test_build_product_report_enforces_band(monkeypatch):
    from verdict.config import Settings
    from verdict.models import SourceSummary
    from verdict.openrouter_client import Completion
    from verdict.summarizer import Summarizer

    sections = [
        "Overall Verdict", "Product Overview", "What Looks Good", "Problems and Red Flags",
        "What Real Customers Are Saying", "Claims vs Reality", "Value for Money",
        "Brand and Seller Trustworthiness", "Alternatives", "Who Should Buy It",
        "Who Should Avoid It", "Final Recommendation",
    ]
    body = (
        "# 🏆 Overall Verdict\n\n**Verdict Score: 12/100**\n\n"
        "**Recommendation: Worth Considering**\n\n"
        + "\n\n".join(f"## {name}\n\ntext" for name in sections[1:])
        + "\n\nAvoid this product because the evidence of serious problems is strong and consistent."
    )

    class FakeClient:
        def complete(self, messages, *, temperature=0.2, max_tokens=1600):
            return Completion(body, "fake")

    report = Summarizer(FakeClient(), Settings()).build_product_report(
        "Widget", "widget review",
        [SourceSummary(title="t", url="https://a.example", summary="s")],
    )
    assert "**Recommendation: 🔴 Strongly Not Recommended**" in report
    assert "Worth Considering" not in report
