import time

import pytest

import web as web_module
from verdict.config import Settings
from verdict.errors import VerdictError
from verdict.pipeline import ResearchResult


@pytest.fixture()
def client():
    # The credit service is module-level; clear its in-memory state so each test
    # starts with an unused free Light grant and an empty wallet.
    svc = web_module.credit_service
    svc._wallets.clear()
    svc._free_claims.clear()
    svc._reservations.clear()
    svc._refunded.clear()
    svc._granted_refs.clear()
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


def _credit_purchase_event(session_id="cs_test_1", quantity=25, user="wh-user"):
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "client_reference_id": user,
                "metadata": {"kind": "credits", "user_id": user, "quantity": str(quantity)},
            }
        },
    }


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


def test_subscription_checkout_accepts_annual_boolean(client):
    res = client.post(
        "/api/checkout/subscription",
        json={"plan": "research_pro", "annual": True},
        headers=AUTH,
    )
    # Stripe is not configured in tests, so this is the expected clean refusal.
    assert res.status_code == 503
