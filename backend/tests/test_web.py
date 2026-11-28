import logging
import time
from types import SimpleNamespace

import pytest

import web as web_module
from verdict.config import Settings
from verdict.errors import VerdictError
from verdict.pipeline import ResearchResult


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(web_module, "DEV_AUTH", True)
    # The credit service is module-level; clear its in-memory state so each test
    # starts with an unused free Light grant and an empty wallet.
    svc = web_module.credit_service
    svc._wallets.clear()
    svc._free_claims.clear()
    svc._reservations.clear()
    svc._refunded.clear()
    svc._granted_refs.clear()
    svc._ledger_rows.clear()
    web_module._webhook_events.clear()
    app = web_module.create_app(Settings(oxylabs_api_key="x", openrouter_api_key="y"))
    app.config["TESTING"] = True
    return app.test_client()


def wait_for(client, job_id, timeout=5, headers=None):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/jobs/{job_id}", headers=headers or AUTH).get_json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.02)
    raise AssertionError("job did not finish")


# Research now requires an authenticated user; the id is forwarded from the
# Next.js relay as X-User-Id.
AUTH = {"X-User-Id": "test-user"}


def test_index_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    body = res.get_json()
    assert body["name"] == "Verdict research API"
    assert "light" in body["modes"]


def test_research_requires_login(client):
    res = client.post("/api/research", json={"text": "https://a.com"})
    assert res.status_code == 401
    assert res.get_json()["error"] == "Please log in to run research."


def test_rejects_empty_input(client):
    res = client.post("/api/research", json={"text": "  "}, headers=AUTH)
    assert res.status_code == 400


def test_job_success_reports_progress_and_sanitizes_html(client, monkeypatch):
    def fake(req, settings, progress):
        progress("step one")
        progress("step two")
        return ResearchResult(
            "Widget review",
            "# Widget\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1)) [ok](https://example.com)",
            [{"title": "t", "url": "https://example.com", "partial": False}],
            ["m"],
        )

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post(
        "/api/research", json={"text": "https://shop.example/p"}, headers=AUTH
    ).get_json()["id"]
    data = wait_for(client, job_id)

    assert data["status"] == "done"
    assert data["steps"] == ["step one", "step two"]
    assert data["title"] == "Widget review"
    assert "<script>" not in data["html"]
    assert "href=\"javascript" not in data["html"]
    assert 'href="https://example.com"' in data["html"]


def test_client_cannot_force_js_rendering(client, monkeypatch):
    captured = {}

    def fake(req, settings, progress):
        captured["render"] = req.render
        return ResearchResult("Widget review", "# Widget")

    monkeypatch.setattr(web_module, "run_research", fake)
    res = client.post(
        "/api/research",
        json={"text": "https://shop.example/p", "render": True},
        headers=AUTH,
    )
    assert res.status_code == 202
    wait_for(client, res.get_json()["id"])
    assert captured["render"] is False


def test_queue_failure_refunds_reservation(client, monkeypatch):
    svc = web_module.credit_service
    svc.grant_credits("test-user", 5, type="purchase")

    def boom(*args, **kwargs):
        raise RuntimeError("queue down")

    monkeypatch.setattr(client.application.config["POOL"], "submit", boom)
    res = client.post(
        "/api/research",
        json={"text": "https://shop.example/p", "mode": "medium"},
        headers=AUTH,
    )
    assert res.status_code == 500
    assert svc.get_wallet("test-user").total == 5
    assert not any(r.get("status") == "held" for r in svc._reservations.values())


def test_stale_reservation_sweep_refunds_after_timeout(client, monkeypatch):
    svc = web_module.credit_service
    svc.grant_credits("test-user", 5, type="purchase")
    monkeypatch.setattr(
        client.application.config["POOL"], "submit", lambda *args, **kwargs: None
    )

    res = client.post(
        "/api/research",
        json={"text": "https://shop.example/p", "mode": "medium"},
        headers=AUTH,
    )
    assert res.status_code == 202
    job_id = res.get_json()["id"]
    assert svc.get_wallet("test-user").total == 3

    svc._reservations[job_id]["created_at"] = time.time() - 1000
    monkeypatch.delenv("VERDICT_CRON_SECRET", raising=False)
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    assert client.post("/api/admin/sweep-reservations").status_code == 401
    res = client.post(
        "/api/admin/sweep-reservations", headers={"X-Cron-Secret": "cron-secret"}
    )
    assert res.get_json()["released"] == 1
    assert svc.get_wallet("test-user").total == 5


def test_poll_since_returns_only_new_steps(client, monkeypatch):
    def fake(req, settings, progress):
        for i in range(3):
            progress(f"s{i}")
        return ResearchResult("t", "# t")

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post("/api/research", json={"text": "https://shop.example/p"}, headers=AUTH).get_json()["id"]
    wait_for(client, job_id)
    data = client.get(f"/api/jobs/{job_id}?since=2", headers=AUTH).get_json()
    assert data["steps"] == ["s2"]
    assert data["step_count"] == 3


def test_verdict_error_is_shown_to_user(client, monkeypatch):
    def fake(req, settings, progress):
        raise VerdictError("Every page failed")

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post("/api/research", json={"text": "https://a.com"}, headers=AUTH).get_json()["id"]
    data = wait_for(client, job_id)
    assert data["status"] == "error"
    assert data["error"] == "Every page failed"


def test_unexpected_error_hides_internals(client, monkeypatch):
    def fake(req, settings, progress):
        raise RuntimeError("secret internal detail with key sk-123")

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post("/api/research", json={"text": "https://a.com"}, headers=AUTH).get_json()["id"]
    data = wait_for(client, job_id)
    assert data["status"] == "error"
    assert "sk-123" not in data["error"]


def test_unknown_job_404(client):
    assert client.get("/api/jobs/doesnotexist", headers=AUTH).status_code == 404


def test_jobs_require_login(client):
    assert client.get("/api/jobs/anything").status_code == 401


def test_forwarded_user_requires_relay_secret(client, monkeypatch):
    monkeypatch.setattr(web_module, "RELAY_SECRET", "s3cret")
    # Claiming an id without the shared secret must be rejected.
    assert client.get("/api/wallet", headers={"X-User-Id": "victim"}).status_code == 401
    # With the secret, the relay's claim is trusted.
    res = client.get(
        "/api/wallet", headers={"X-User-Id": "victim", "X-Relay-Secret": "s3cret"}
    )
    assert res.status_code == 200


def test_supabase_user_is_converted_to_dict(client, monkeypatch):
    class FakeAuth:
        def get_user(self, token):
            return SimpleNamespace(user=SimpleNamespace(id="sb-user", email="user@example.com"))

    monkeypatch.setattr(web_module, "sb", SimpleNamespace(auth=FakeAuth()))
    with client.application.test_request_context(headers={"Authorization": "Bearer any-token"}):
        assert web_module._user_from_request() == {"id": "sb-user", "email": "user@example.com"}


def test_auth_failures_log_reason_without_token(client, monkeypatch, caplog):
    monkeypatch.setattr(web_module, "sb", SimpleNamespace(auth=SimpleNamespace(get_user=lambda token: None)))
    monkeypatch.setattr(web_module, "RELAY_SECRET", "expected")

    with caplog.at_level(logging.WARNING):
        with client.application.test_request_context(headers={"Authorization": "Bearer secret-token"}):
            assert web_module._user_from_request() is None
    assert "token rejected" in caplog.text.lower()
    assert "secret-token" not in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        with client.application.test_request_context(headers={"X-User-Id": "someone", "X-Relay-Secret": "wrong"}):
            assert web_module._user_from_request() is None
    assert "relay secret mismatch" in caplog.text.lower()
    assert "wrong" not in caplog.text

    monkeypatch.setattr(web_module, "RELAY_SECRET", "")
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        with client.application.test_request_context(headers={"X-User-Id": "someone"}):
            assert web_module._user_from_request() is None
    assert "relay secret missing" in caplog.text.lower()


def test_header_auth_fails_closed_without_dev_flag(client, monkeypatch):
    monkeypatch.setattr(web_module, "sb", None)
    monkeypatch.setattr(web_module, "RELAY_SECRET", "")
    monkeypatch.setattr(web_module, "DEV_AUTH", False)
    with client.application.test_request_context(headers={"X-User-Id": "someone"}):
        assert web_module._user_from_request() is None


def test_header_auth_allowed_with_dev_flag(client, monkeypatch):
    monkeypatch.setattr(web_module, "sb", None)
    monkeypatch.setattr(web_module, "RELAY_SECRET", "")
    monkeypatch.setattr(web_module, "DEV_AUTH", True)
    with client.application.test_request_context(headers={"X-User-Id": "dev-user"}):
        assert web_module._user_from_request() == {"id": "dev-user"}


def test_job_is_private_to_its_owner(client, monkeypatch):
    def fake(req, settings, progress):
        return ResearchResult("t", "# t")

    monkeypatch.setattr(web_module, "run_research", fake)
    job_id = client.post(
        "/api/research", json={"text": "https://a.com"}, headers={"X-User-Id": "owner"}
    ).get_json()["id"]
    wait_for(client, job_id, headers={"X-User-Id": "owner"})
    # A different account must not be able to read it.
    res = client.get(f"/api/jobs/{job_id}", headers={"X-User-Id": "intruder"})
    assert res.status_code == 404


def test_failed_free_investigation_returns_the_grant(client, monkeypatch):
    def boom(req, settings, progress):
        raise VerdictError("scrape failed")

    monkeypatch.setattr(web_module, "run_research", boom)
    headers = {"X-User-Id": "free-user"}
    job_id = client.post("/api/research", json={"text": "https://a.com"}, headers=headers).get_json()["id"]
    wait_for(client, job_id, headers=headers)
    wallet = client.get("/api/wallet", headers=headers).get_json()
    assert wallet["free_light_available"] is True


def test_checkout_reports_missing_configuration_cleanly(client):
    res = client.post(
        "/api/checkout/credits", json={"quantity": 10}, headers=AUTH
    )
    assert res.status_code == 503
    assert "not configured" in res.get_json()["error"].lower()


def test_checkout_validates_quantity_before_payment(client):
    res = client.post("/api/checkout/credits", json={"quantity": 1}, headers=AUTH)
    assert res.status_code == 400


def _post_event(client, monkeypatch, event):
    monkeypatch.setattr(
        web_module.payment_service, "verify_webhook", lambda payload, signature: event
    )
    return client.post(
        "/api/webhooks/stripe", json=event, headers={"Stripe-Signature": "test"}
    )


def _credit_purchase_event(session_id="cs_test_1", quantity=25, user="wh-user", total_cents="2000"):
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "client_reference_id": user,
                "metadata": {
                    "kind": "credits",
                    "user_id": user,
                    "quantity": str(quantity),
                    "total_cents": total_cents,
                },
            }
        },
    }


def test_webhook_claim_missing_rpc_fails_closed(monkeypatch):
    class MissingRPC:
        def __call__(self, name, params):
            class Call:
                def execute(self):
                    raise RuntimeError(
                        "Could not find the function public.verdict_claim_webhook_event"
                    )

            return Call()

    monkeypatch.setattr(web_module, "sb", SimpleNamespace(rpc=MissingRPC()))
    with pytest.raises(RuntimeError, match="Could not find the function"):
        web_module._claim_webhook_event("evt-missing-rpc", "checkout.session.completed")


def test_webhook_grants_credits_once_and_ignores_replays(client, monkeypatch):
    event = _credit_purchase_event()
    headers = {"X-User-Id": "wh-user"}

    assert _post_event(client, monkeypatch, event).status_code == 200
    wallet = client.get("/api/wallet", headers=headers).get_json()
    assert wallet["purchased_credits"] == 25

    # Replaying the same session must not grant again.
    assert _post_event(client, monkeypatch, event).status_code == 200
    wallet = client.get("/api/wallet", headers=headers).get_json()
    assert wallet["purchased_credits"] == 25


def test_webhook_failure_releases_claim_and_asks_stripe_to_retry(client, monkeypatch):
    event = _credit_purchase_event()
    event["id"] = "evt_fail_1"
    original_grant = web_module.credit_service.grant_credits

    def boom(*args, **kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(web_module.credit_service, "grant_credits", boom)
    assert _post_event(client, monkeypatch, event).status_code == 500

    monkeypatch.setattr(web_module.credit_service, "grant_credits", original_grant)
    assert _post_event(client, monkeypatch, event).status_code == 200
    wallet = client.get("/api/wallet", headers={"X-User-Id": "wh-user"}).get_json()
    assert wallet["purchased_credits"] == 25


def test_reconcile_grants_paid_pending_payment(client, monkeypatch):
    rows = [{
        "id": "pay-1",
        "user_id": "recon-user",
        "kind": "credits",
        "credit_amount": 10,
        "amount_cents": 900,
        "provider_session_id": "cs_recon_1",
        "status": "pending",
    }]

    class FakePayments:
        def __init__(self):
            self._updating = False

        def select(self, *args):
            self._updating = False
            return self

        def update(self, payload):
            self._updating = True
            return self

        def eq(self, *args):
            return self

        def execute(self):
            return SimpleNamespace(data=[] if self._updating else rows)

    monkeypatch.setattr(web_module, "sb", SimpleNamespace(table=lambda name: FakePayments()))
    monkeypatch.delenv("VERDICT_CRON_SECRET", raising=False)
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    monkeypatch.setattr(
        web_module.payment_service,
        "retrieve_checkout_session",
        lambda session_id: {
            "id": session_id,
            "payment_status": "paid",
            "client_reference_id": "recon-user",
            "metadata": {"kind": "credits", "user_id": "recon-user", "quantity": "10"},
        },
    )

    assert client.post("/api/admin/reconcile-payments").status_code == 401
    res = client.post("/api/admin/reconcile-payments", headers={"X-Cron-Secret": "cron-secret"})
    assert res.status_code == 200
    assert res.get_json() == {"checked": 1, "granted": 1}
    wallet = web_module.credit_service.get_wallet("recon-user")
    assert wallet.purchased_credits == 10


def test_webhook_subscription_grants_monthly_allowance(client, monkeypatch):
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_sub_1",
                "client_reference_id": "sub-user",
                "metadata": {
                    "kind": "subscription",
                    "user_id": "sub-user",
                    "plan": "business",
                    "interval": "annual",
                },
            }
        },
    }
    _post_event(client, monkeypatch, event)
    wallet = client.get("/api/wallet", headers={"X-User-Id": "sub-user"}).get_json()
    # Annual Business still grants 150 for the month, not 1,800 upfront.
    assert wallet["subscription_credits"] == 150


def test_webhook_renewal_resets_without_rollover(client, monkeypatch):
    headers = {"X-User-Id": "renew-user"}
    web_module.credit_service.add_credits("renew-user", 10, kind="subscription")
    web_module.credit_service.add_credits("renew-user", 4, kind="purchased")

    event = {
        "type": "invoice.paid",
        "data": {
            "object": {
                "id": "in_test_1",
                "subscription": "sub_x",
                "subscription_details": {
                    "metadata": {"user_id": "renew-user", "plan": "research_pro"}
                },
            }
        },
    }
    _post_event(client, monkeypatch, event)
    wallet = client.get("/api/wallet", headers=headers).get_json()
    assert wallet["subscription_credits"] == 50  # reset, not 60
    assert wallet["purchased_credits"] == 4


def test_webhook_cancellation_keeps_purchased_credits(client, monkeypatch):
    headers = {"X-User-Id": "cancel-user"}
    web_module.credit_service.add_credits("cancel-user", 50, kind="subscription")
    web_module.credit_service.add_credits("cancel-user", 12, kind="purchased")

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"metadata": {"user_id": "cancel-user"}}},
    }
    _post_event(client, monkeypatch, event)
    # Cancellation stops future grants; credits already bought remain.
    wallet = client.get("/api/wallet", headers=headers).get_json()
    assert wallet["purchased_credits"] == 12
    assert wallet["subscription_credits"] == 0


def test_wallet_exposes_real_ledger_summary(client, monkeypatch):
    headers = {"X-User-Id": "overview-user"}
    _post_event(
        client,
        monkeypatch,
        _credit_purchase_event(session_id="cs_overview", quantity=12, user="overview-user"),
    )
    body = client.get("/api/wallet", headers=headers).get_json()
    assert body["total"] == 12
    assert body["summary"]["purchased_total"] == 12
    assert body["subscription"] is None
    assert body["researches_completed"] == 0


def test_transactions_are_filterable_and_paginated(client, monkeypatch):
    headers = {"X-User-Id": "tx-user"}
    _post_event(client, monkeypatch, _credit_purchase_event(user="tx-user"))
    page = client.get("/api/transactions?limit=1", headers=headers).get_json()
    assert page["total"] == 1
    assert len(page["transactions"]) == 1
    assert page["transactions"][0]["category"] == "credit_purchase"
    assert page["transactions"][0]["amount_cents"] == 2000
    filtered = client.get("/api/transactions?type=refund", headers=headers).get_json()
    assert filtered["total"] == 0
    searched = client.get("/api/transactions?q=credit", headers=headers).get_json()
    assert searched["total"] == 1


def test_cancel_at_period_end_keeps_credits_until_deletion(client, monkeypatch):
    headers = {"X-User-Id": "later-user"}
    _post_event(
        client,
        monkeypatch,
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_later",
                    "client_reference_id": "later-user",
                    "metadata": {
                        "kind": "subscription",
                        "user_id": "later-user",
                        "plan": "research_pro",
                        "interval": "monthly",
                    },
                }
            },
        },
    )
    assert client.get("/api/wallet", headers=headers).get_json()["subscription_credits"] == 50

    _post_event(
        client,
        monkeypatch,
        {
            "id": "evt_update",
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": "sub_later",
                    "status": "active",
                    "cancel_at_period_end": True,
                    "current_period_end": 4102444800,
                    "metadata": {"user_id": "later-user"},
                }
            },
        },
    )
    wallet = client.get("/api/wallet", headers=headers).get_json()
    assert wallet["subscription_credits"] == 50


def test_subscription_management_requires_a_linked_subscription(client):
    assert client.post("/api/subscription/portal", headers=AUTH).status_code == 400
    assert client.post("/api/subscription/cancel", headers=AUTH).status_code == 400


def test_credit_allocation_cron_requires_secret(client, monkeypatch):
    monkeypatch.delenv("VERDICT_CRON_SECRET", raising=False)
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    assert client.post("/api/subscriptions/allocate").status_code == 401
    assert client.post(
        "/api/subscriptions/allocate", headers={"X-Cron-Secret": "cron-secret"}
    ).status_code == 200


def test_cron_secret_accepts_vercel_name_and_prefers_render_name(monkeypatch, caplog):
    monkeypatch.delenv("VERDICT_CRON_SECRET", raising=False)
    monkeypatch.setenv("CRON_SECRET", "vercel-secret")
    monkeypatch.setattr(web_module, "_CRON_FALLBACK_WARNED", False)
    with caplog.at_level(logging.WARNING):
        assert web_module._cron_secret() == "vercel-secret"
    assert "VERDICT_CRON_SECRET is not set" in caplog.text

    monkeypatch.setenv("VERDICT_CRON_SECRET", "render-secret")
    assert web_module._cron_secret() == "render-secret"


def test_subscription_checkout_accepts_annual_boolean(client):
    res = client.post(
        "/api/checkout/subscription",
        json={"plan": "research_pro", "annual": True},
        headers=AUTH,
    )
    # Stripe is not configured in tests, so this is the expected clean refusal.
    assert res.status_code == 503
