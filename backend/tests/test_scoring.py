import pytest

from verdict.scoring import (
    BANDS,
    SCORE_WEIGHTS,
    apply_score_bands,
    apply_structured_scores,
    band_for,
    compute_score_totals,
    find_score,
    parse_score_json,
)
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


def test_rubric_weights_sum_to_100():
    assert {name: sum(weights.values()) for name, weights in SCORE_WEIGHTS.items()} == {
        "product_credibility": 100,
        "evidence_strength": 100,
        "purchasing_confidence": 100,
    }


def test_prompt_contains_structured_schema():
    for name, categories in SCORE_WEIGHTS.items():
        assert f'"{name}"' in VERDICT_SYSTEM_PROMPT
        for category, maximum in categories.items():
            assert f'"{category}": "0-{maximum}"' in VERDICT_SYSTEM_PROMPT
    assert "STRUCTURED SCORE OUTPUT" in VERDICT_SYSTEM_PROMPT


def test_missing_category_scores_are_zero_instead_of_crashing():
    totals = compute_score_totals({"product_credibility": {"product_legitimacy": 999}})
    assert totals["product_credibility"] == 20
    assert totals["evidence_strength"] == 0
    assert totals["purchasing_confidence"] == 0
    assert totals["verdict"] == 7


def test_identical_inputs_give_identical_total():
    payload = {
        "product_credibility": {"product_legitimacy": 18, "safety": 4},
        "evidence_strength": {"source_reliability": 22},
        "purchasing_confidence": {"available_evidence": 27},
    }
    first = compute_score_totals(payload)
    assert first == compute_score_totals(payload)
    assert first == {
        "product_credibility": 22,
        "evidence_strength": 22,
        "purchasing_confidence": 27,
        "verdict": 24,
    }


def test_structured_scores_override_prose_and_strip_json():
    md = (
        "# 🏆 Overall Verdict\n\n**Verdict Score: 99/100**\n\n"
        "**Product Credibility: 99/100**\n\n"
        "**Evidence Strength: 99/100**\n\n"
        "**Purchasing Confidence: 99/100**\n\n"
        "```json\n{\"product_credibility\":{\"product_legitimacy\":20}}\n```\n"
    )
    out, totals = apply_structured_scores(md, parse_score_json(md))
    assert totals["product_credibility"] == 20
    assert "Verdict Score: 7/100" in out
    assert "Product Credibility: 20/100" in out
    assert "```json" not in out


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
        + "\n\n```json\n"
        + '{"product_credibility":{"product_legitimacy":12},'
        + '"evidence_strength":{"source_reliability":12},'
        + '"purchasing_confidence":{"available_evidence":12}}\n```'
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
