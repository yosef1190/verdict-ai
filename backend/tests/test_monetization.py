"""End-to-end tests for pricing, the credit wallet, subscriptions and the API.

These run against the in-memory CreditService fallback (no Supabase required),
which exercises the same reservation/refund/idempotency logic the database path
implements.
"""

from __future__ import annotations

import threading

import pytest

from verdict.credits import CreditService, InsufficientCredits
from verdict.wallet import calculate_price


# --------------------------------------------------------------------- pricing


@pytest.mark.parametrize(
    "quantity,expected_total,expected_unit",
    [(5, 500, 1.00), (10, 850, 0.85), (25, 1750, 0.70), (50, 3000, 0.60), (100, 5000, 0.50)],
)
def test_pay_as_you_go_tiers(quantity, expected_total, expected_unit):
    quote = calculate_price("pay_as_you_go", quantity=quantity)
    assert quote["total_cents"] == expected_total
    assert quote["unit_price"] == pytest.approx(expected_unit)


def test_pay_as_you_go_minimum():
    with pytest.raises(ValueError):
        calculate_price("pay_as_you_go", quantity=1)


def test_subscription_prices():
    assert calculate_price("research_pro", monthly=True)["total_cents"] == 1499
    assert calculate_price("research_pro", monthly=False)["total_cents"] == 14999
    assert calculate_price("business", monthly=True)["total_cents"] == 2999
    assert calculate_price("business", monthly=False)["total_cents"] == 29999


def test_subscription_credits_are_monthly_not_upfront():
    pro = calculate_price("research_pro", monthly=False)
    biz = calculate_price("business", monthly=False)
    assert pro["credits_per_month"] == 50
    assert biz["credits_per_month"] == 150


# ---------------------------------------------------------------------- wallet


def test_mode_costs():
    svc = CreditService()
    svc.add_credits("u1", 10)
    assert svc.reserve("u1", "inv-light", "light")["cost"] == 1
    assert svc.reserve("u1", "inv-medium", "medium")["cost"] == 2
    assert svc.reserve("u1", "inv-deep", "deep")["cost"] == 3


def test_subscription_credits_consumed_first():
    svc = CreditService()
    svc.add_credits("u2", 5, kind="subscription")
    svc.add_credits("u2", 5, kind="purchased")
    rec = svc.reserve("u2", "inv-1", "deep")
    assert rec["subscription_used"] == 3
    assert rec["purchased_used"] == 0
    wallet = svc.get_wallet("u2")
    assert wallet.subscription_credits == 2
    assert wallet.purchased_credits == 5


def test_purchased_credits_used_after_subscription_runs_out():
    svc = CreditService()
    svc.add_credits("u3", 1, kind="subscription")
    svc.add_credits("u3", 5, kind="purchased")
    rec = svc.reserve("u3", "inv-1", "deep")
    assert rec["subscription_used"] == 1
    assert rec["purchased_used"] == 2
    wallet = svc.get_wallet("u3")
    assert wallet.subscription_credits == 0
    assert wallet.purchased_credits == 3


def test_insufficient_balance_blocks_research():
    svc = CreditService()
    svc.add_credits("u4", 1)
    with pytest.raises(InsufficientCredits):
        svc.reserve("u4", "inv-x", "medium")


def test_duplicate_reservation_is_idempotent():
    svc = CreditService()
    svc.add_credits("u5", 10)
    first = svc.reserve("u5", "inv-dup", "medium")
    second = svc.reserve("u5", "inv-dup", "medium")
    assert first["cost"] == second["cost"]
    # Only 2 credits should have been spent, not 4.
    assert svc.get_wallet("u5").total == 8


def test_failed_investigation_refunds_exactly_once():
    svc = CreditService()
    svc.add_credits("u6", 5)
    svc.reserve("u6", "inv-fail", "deep")
    assert svc.get_wallet("u6").total == 2
    assert svc.release_and_refund("u6", "inv-fail") is True
    assert svc.get_wallet("u6").total == 5
    # A second refund must not add credits again.
    assert svc.release_and_refund("u6", "inv-fail") is False
    assert svc.get_wallet("u6").total == 5


def test_refund_restores_original_buckets():
    svc = CreditService()
    svc.add_credits("u7", 2, kind="subscription")
    svc.add_credits("u7", 3, kind="purchased")
    svc.reserve("u7", "inv-b", "deep")
    svc.release_and_refund("u7", "inv-b")
    wallet = svc.get_wallet("u7")
    assert wallet.subscription_credits == 2
    assert wallet.purchased_credits == 3


def test_finalize_does_not_move_credits():
    svc = CreditService()
    svc.add_credits("u8", 5)
    svc.reserve("u8", "inv-ok", "medium")
    before = svc.get_wallet("u8").total
    assert svc.finalize("u8", "inv-ok") is True
    assert svc.get_wallet("u8").total == before


def test_free_light_only_once():
    svc = CreditService()
    assert svc.has_used_free_light("u9") is False
    assert svc.claim_free_light("u9") is True
    assert svc.has_used_free_light("u9") is True
    assert svc.claim_free_light("u9") is False


def test_subscription_reset_does_not_roll_over():
    svc = CreditService()
    svc.add_credits("u10", 50, kind="subscription")
    svc.add_credits("u10", 7, kind="purchased")
    svc.reserve("u10", "inv-a", "light")  # spends 1 subscription credit
    svc.reset_subscription_credits("u10", 50)
    wallet = svc.get_wallet("u10")
    assert wallet.subscription_credits == 50  # reset, not 99
    assert wallet.purchased_credits == 7  # untouched


def test_purchased_credits_survive_cancellation():
    svc = CreditService()
    svc.add_credits("u11", 10, kind="subscription")
    svc.add_credits("u11", 6, kind="purchased")
    # Cancellation is modelled as the subscription bucket being cleared.
    svc.reset_subscription_credits("u11", 0)
    assert svc.get_wallet("u11").purchased_credits == 6


def test_concurrent_requests_cannot_double_spend():
    svc = CreditService()
    svc.add_credits("u12", 3)
    results: list[str] = []

    def attempt(n: int) -> None:
        try:
            svc.reserve("u12", f"inv-c{n}", "deep")
            results.append("ok")
        except InsufficientCredits:
            results.append("blocked")

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Only three 3-credit runs can fit in a 3-credit wallet: exactly one.
    assert results.count("ok") == 1
    assert svc.get_wallet("u12").total == 0


# --------------------------------------------------------------------- web API


@pytest.fixture()
def client():
    from web import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_pricing_endpoint_is_public(client):
    res = client.get("/api/pricing")
    assert res.status_code == 200
    body = res.get_json()
    assert body["mode_costs"] == {"light": 1, "medium": 2, "deep": 3}
    assert body["pay_as_you_go"]["min_purchase"] == 5


def test_quote_endpoint_ignores_frontend_price(client):
    res = client.post("/api/pricing/quote", json={"plan": "pay_as_you_go", "quantity": 50, "total_cents": 1})
    assert res.status_code == 200
    assert res.get_json()["total_cents"] == 3000


def test_wallet_requires_login(client):
    assert client.get("/api/wallet").status_code == 401


def test_research_requires_login(client):
    res = client.post("/api/research", json={"text": "https://example.com", "mode": "light"})
    assert res.status_code == 401


def test_research_rejects_invalid_mode(client):
    res = client.post(
        "/api/research", json={"text": "https://example.com", "mode": "ultra"},
        headers={"X-User-Id": "api-user"},
    )
    assert res.status_code == 400


def test_webhook_rejects_bad_signature(client):
    res = client.post("/api/webhooks/stripe", json={"type": "checkout.session.completed"}, headers={"Stripe-Signature": "nope"})
    assert res.status_code in (400, 503)


# ------------------------------------------------- atomic RPC (database) path


class _FakeRpc:
    def __init__(self, result, error=None):
        self._result = result
        self._error = error
        self.calls = []

    def __call__(self, name, params):
        self.calls.append((name, params))
        return self

    def execute(self):
        if self._error is not None:
            raise self._error
        return type("Resp", (), {"data": self._result})()


class _FakeSupabase:
    """Just enough of the Supabase client for the RPC code path."""

    def __init__(self, result, error=None):
        self.rpc = _FakeRpc(result, error)


def test_reserve_uses_atomic_function_and_maps_insufficient():
    client = _FakeSupabase(
        {"status": "insufficient", "available": 1, "required": 3, "cost": 3}
    )
    service = CreditService(client)
    with pytest.raises(InsufficientCredits):
        service.reserve("u1", "job-1", "deep")
    assert client.rpc.calls[0][0] == "verdict_reserve_credits"
    assert client.rpc.calls[0][1]["p_cost"] == 3


def test_reserve_reports_buckets_from_atomic_function():
    client = _FakeSupabase(
        {
            "status": "held",
            "cost": 2,
            "mode": "medium",
            "subscription_used": 2,
            "purchased_used": 0,
            "balance_before": 5,
            "balance_after": 3,
        }
    )
    record = CreditService(client).reserve("u1", "job-2", "medium")
    assert record["status"] == "held"
    assert record["subscription_used"] == 2
    assert record["balance_after"] == 3


def test_refund_is_not_repeated_when_the_function_says_no():
    client = _FakeSupabase({"refunded": False, "reason": "released"})
    assert CreditService(client).release_and_refund("u1", "job-3") is False


def test_missing_function_falls_back_to_table_updates():
    """An un-migrated database must not crash; it uses the older code path."""
    error = RuntimeError(
        "Could not find the function public.verdict_reserve_credits in the schema cache"
    )
    client = _FakeSupabase(None, error=error)
    # No tables either, so the fallback path ends in InsufficientCredits (0 credits)
    # rather than raising the missing-function error.
    with pytest.raises(InsufficientCredits):
        CreditService(client).reserve("u1", "job-4", "light")
