"""Research-quality tests: source classification, product identity, and report
validation, using the Anker Nano charger (model A140A) as the worked example
from the brief.
"""

from __future__ import annotations

from verdict.evidence import (
    CLAIM_MANUFACTURER,
    SOURCE_CLASSES,
    classify_source,
    summarize_source_classes,
    validate_report,
    verify_product_identity,
)
from verdict.models import SourceSummary


PRODUCT = "Anker Nano Universal Charger A140A"
MODEL = "A140A"
ASIN = "B0GS5M96KD"


def test_all_eight_source_classes_exist():
    assert len(SOURCE_CLASSES) == 8


def test_classification_of_known_sources():
    cases = [
        ("Review: Anker Nano A140A tested", "https://www.rtings.com/charger/anker", {"product_url": ""}, "Independent laboratory testing"),
        ("Anker Nano charger review", "https://www.cnet.com/tech/anker", {"product_url": ""}, "Independent expert reviews"),
        ("Anker Nano charger review", "https://www.theverge.com/anker", {"product_url": ""}, "Independent expert reviews"),
        ("Customer reviews: Anker Nano", "https://www.amazon.com/dp/B0GS5M96KD", {"product_url": ""}, "Verified purchaser reviews"),
        ("Anyone used the Anker Nano?", "https://www.reddit.com/r/chargers/xyz", {"product_url": ""}, "Community discussions"),
        ("Anker Nano A140A specifications", "https://www.anker.com/products/a140a", {"product_url": "https://www.anker.com/products/a140a"}, "Manufacturer documentation"),
        ("Random blog", "https://some-unknown-blog.example/post", {"product_url": ""}, "Unverified content"),
    ]
    for title, url, kwargs, expected in cases:
        got = classify_source(SourceSummary(title=title, url=url, summary=""), **kwargs)
        assert got == expected, f"{url} -> {got}, expected {expected}"


def test_unrelated_charging_station_rejected():
    check = verify_product_identity(
        PRODUCT,
        source_title="Anker Charging Station 737 review",
        source_summary="A large desktop charging station with six ports.",
        product_model=MODEL,
        product_asin=ASIN,
    )
    assert check.accepted is False


def test_matching_model_accepted():
    check = verify_product_identity(
        PRODUCT,
        source_title="Anker Nano charger A140A review",
        source_summary="Compact 30W USB-C charger tested over a month.",
        product_model=MODEL,
        product_asin=ASIN,
    )
    assert check.accepted is True
    assert "A140A" in check.matched_models


def test_asin_match_is_conclusive():
    check = verify_product_identity(
        PRODUCT,
        source_title="Some listing",
        source_summary="Reviewed by a buyer. ASIN B0GS5M96KD",
        product_model=MODEL,
        product_asin=ASIN,
    )
    assert check.accepted is True
    assert check.score == 1.0


def test_manufacturer_source_is_not_independent_proof():
    manufacturer = SourceSummary(
        title="Anker Nano specifications",
        url="https://www.anker.com/products/a140a",
        summary="Anker says this charger delivers 30W and is the smallest in its class.",
    )
    product_url = "https://www.anker.com/products/a140a"
    assert classify_source(manufacturer, product_url=product_url) == "Manufacturer documentation"
    classes = summarize_source_classes([manufacturer], product_url=product_url)
    # The manufacturer bucket is tracked, but the source is not counted as an
    # independent class for evidence strength.
    assert classes.get("Manufacturer documentation") == 1
    independent = (
        "Independent laboratory testing",
        "Independent expert reviews",
        "Established technology publications",
        "Verified purchaser reviews",
        "Community discussions",
    )
    assert sum(classes.get(name, 0) for name in independent) == 0


def test_validation_flags_missing_citations_and_scores():
    body = (
        "# Verdict\n\n"
        "## Overall Verdict\n\nThis is great. Buy it now.\n\n"
        "## Sources\n\n1. https://www.anker.com/products/a140a\n"
    )
    sources = [
        SourceSummary(
            title="Anker Nano specifications",
            url="https://www.anker.com/products/a140a",
            summary="Manufacturer specifications.",
        )
    ]
    result = validate_report(body, sources, product_name=PRODUCT)
    assert result.ok is False
    # Missing the three required scores must be one of the disclosed problems.
    assert any("credibility" in p.lower() or "score" in p.lower() for p in result.problems)


def test_validation_never_invents_evidence():
    """A well-formed report citing a collected source passes without fabricating."""
    body = (
        "# Verdict\n\n## Overall Verdict\n\nCareful recommendation [1].\n\n"
        "**Verdict Score: 72/100**\n\n"
        "**Product Credibility: 72/100**\n\n"
        "**Evidence Strength: 41/100** — limited independent testing.\n\n"
        "**Purchasing Confidence: 55/100**\n\n"
        "## Sources and Evidence\n\n1. https://www.rtings.com/charger/anker\n"
    )
    sources = [
        SourceSummary(
            title="Anker Nano A140A lab test",
            url="https://www.rtings.com/charger/anker",
            summary="Independent lab measured output and heat.",
        )
    ]
    result = validate_report(body, sources, product_name=PRODUCT)
    assert result.ok is True


def test_claim_status_constant():
    assert CLAIM_MANUFACTURER == "MANUFACTURER CLAIM"
