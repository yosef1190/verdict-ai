"""Payment provider abstraction (Stripe-ready).

Design goals:
  * Never trust a frontend "payment succeeded" signal.
  * Credits are granted only after a verified webhook, using the service role.
  * Idempotent: the unique provider session id means a webhook replay cannot
    grant credits twice.
  * Cleanly degrades when Stripe is not configured, so the rest of the app
    (research, wallet, pricing) keeps working while payments are disabled.

Configuration (all in the backend env):
  STRIPE_SECRET_KEY        sk_test_... (test) or sk_live_... (production)
  STRIPE_WEBHOOK_SECRET    whsec_... from the Stripe dashboard
  STRIPE_PRICE_PRO_MONTHLY price_... for Research Pro monthly
  STRIPE_PRICE_PRO_ANNUAL  price_... for Research Pro annual
  STRIPE_PRICE_BIZ_MONTHLY price_... for Business monthly
  STRIPE_PRICE_BIZ_ANNUAL  price_... for Business annual
  APP_URL                  public URL of the frontend, for redirects

One-time credit purchases use Checkout in "payment" mode with a dynamic
price_data line item; subscription plans use "subscription" mode with a
configured Stripe Price id.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

try:  # Stripe is optional so the app runs without it.
    import stripe as _stripe
except Exception:  # pragma: no cover - absent in local dev unless installed
    _stripe = None


@dataclass
class CheckoutResult:
    url: str
    session_id: str


class PaymentNotConfigured(Exception):
    """Raised when a checkout is requested but Stripe is not set up."""


def _field(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from a Stripe object or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class PaymentService:
    """Thin wrapper around Stripe with explicit configuration checks."""

    def __init__(self) -> None:
        self.secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
        self.webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
        self.app_url = os.getenv("APP_URL", "").strip().rstrip("/") or "http://localhost:3000"
        self.price_ids = {
            "research_pro:monthly": os.getenv("STRIPE_PRICE_PRO_MONTHLY", "").strip(),
            "research_pro:annual": os.getenv("STRIPE_PRICE_PRO_ANNUAL", "").strip(),
            "business:monthly": os.getenv("STRIPE_PRICE_BIZ_MONTHLY", "").strip(),
            "business:annual": os.getenv("STRIPE_PRICE_BIZ_ANNUAL", "").strip(),
        }
        self._configured = bool(_stripe and self.secret_key)
        if self._configured:
            _stripe.api_key = self.secret_key
            _stripe.max_network_retries = 2

    @property
    def configured(self) -> bool:
        return self._configured

    def config_status(self) -> dict[str, Any]:
        """What remains to be configured, for the implementation report."""
        missing = []
        if not _stripe:
            missing.append("stripe python package (add 'stripe' to requirements.txt)")
        if not self.secret_key:
            missing.append("STRIPE_SECRET_KEY")
        if not self.webhook_secret:
            missing.append("STRIPE_WEBHOOK_SECRET")
        for key, value in self.price_ids.items():
            if not value:
                missing.append(f"STRIPE price id for {key}")
        return {
            "configured": self._configured and not missing,
            "missing": missing,
            "mode": "test" if self.secret_key.startswith("sk_test_") else (
                "live" if self.secret_key.startswith("sk_live_") else "unset"
            ),
        }

    # ---------------------------------------------------------- one-time credits

    def create_credit_checkout(
        self,
        *,
        user_id: str,
        email: str,
        quantity: int,
        unit_price_cents: int,
        total_cents: int,
    ) -> CheckoutResult:
        """Create a Stripe Checkout session for a one-time credit purchase."""
        if not self._configured:
            raise PaymentNotConfigured(
                "Payments are not configured yet. Add STRIPE_SECRET_KEY to the backend env."
            )

        session = _stripe.checkout.Session.create(
            mode="payment",
            customer_email=email or None,
            client_reference_id=user_id,
            line_items=[
                {
                    "quantity": quantity,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": unit_price_cents,
                        "product_data": {
                            "name": f"Verdict research credits ({quantity})",
                        },
                    },
                }
            ],
            metadata={
                "kind": "credits",
                "user_id": user_id,
                "quantity": str(quantity),
                "total_cents": str(total_cents),
            },
            success_url=f"{self.app_url}/dashboard?checkout=success",
            cancel_url=f"{self.app_url}/pricing?checkout=canceled",
        )
        return CheckoutResult(url=session.url, session_id=session.id)

    # ------------------------------------------------------------- subscriptions

    def create_subscription_checkout(
        self,
        *,
        user_id: str,
        email: str,
        plan: str,
        interval: str,
    ) -> CheckoutResult:
        """Create a Stripe Checkout session for a subscription plan."""
        if not self._configured:
            raise PaymentNotConfigured(
                "Payments are not configured yet. Add STRIPE_SECRET_KEY to the backend env."
            )
        price_id = self.price_ids.get(f"{plan}:{interval}")
        if not price_id:
            raise PaymentNotConfigured(
                f"Missing Stripe price id for {plan} {interval}. "
                f"Set STRIPE_PRICE_{'PRO' if plan == 'research_pro' else 'BIZ'}_"
                f"{'MONTHLY' if interval == 'monthly' else 'ANNUAL'}."
            )

        meta = {
            "kind": "subscription",
            "user_id": user_id,
            "plan": plan,
            "interval": interval,
        }
        session = _stripe.checkout.Session.create(
            mode="subscription",
            customer_email=email or None,
            client_reference_id=user_id,
            line_items=[{"price": price_id, "quantity": 1}],
            metadata=meta,
            # Copied onto the subscription (and its invoices), so renewal events
            # can be tied back to the account without trusting frontend data.
            subscription_data={"metadata": meta},
            success_url=f"{self.app_url}/dashboard?checkout=success",
            cancel_url=f"{self.app_url}/pricing?checkout=canceled",
        )
        return CheckoutResult(url=session.url, session_id=session.id)


    def subscription_state(self, subscription: Any) -> dict[str, Any]:
        """The small, safe subset of a Stripe subscription the backend needs."""
        items = _field(subscription, "items")
        price_id = ""
        try:
            data = _field(items, "data") or []
            if data:
                price = _field(data[0], "price") or {}
                price_id = str(_field(price, "id") or "")
        except Exception:  # noqa: BLE001 - defensive: subscription shapes vary
            price_id = ""
        return {
            "id": str(_field(subscription, "id") or ""),
            "customer": str(_field(subscription, "customer") or ""),
            "status": str(_field(subscription, "status") or ""),
            "cancel_at_period_end": bool(_field(subscription, "cancel_at_period_end", False)),
            "current_period_start": _field(subscription, "current_period_start"),
            "current_period_end": _field(subscription, "current_period_end"),
            "canceled_at": _field(subscription, "canceled_at"),
            "price_id": price_id,
            "metadata": _field(subscription, "metadata") or {},
        }

    def retrieve_subscription(self, subscription_id: str) -> dict[str, Any]:
        if not self._configured:
            raise PaymentNotConfigured("Payments are not configured yet.")
        return self.subscription_state(_stripe.Subscription.retrieve(subscription_id))

    def create_billing_portal(self, customer_id: str, return_url: str) -> CheckoutResult:
        """Stripe-hosted portal for changing card, plan and billing details."""
        if not self._configured or not customer_id:
            raise PaymentNotConfigured(
                "Billing management is not available for this account yet."
            )
        session = _stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url or f"{self.app_url}/wallet",
        )
        return CheckoutResult(url=session.url, session_id=session.id)

    def cancel_subscription(self, subscription_id: str) -> dict[str, Any]:
        """Cancel at period end. Access and credits stay until the period ends."""
        if not self._configured:
            raise PaymentNotConfigured("Payments are not configured yet.")
        if not subscription_id:
            raise PaymentNotConfigured("No Stripe subscription is linked to this account.")
        return self.subscription_state(
            _stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
        )

    # ------------------------------------------------------------------ webhooks

    def verify_webhook(self, payload: bytes, signature: str) -> dict[str, Any] | None:
        """Verify a webhook signature. Returns the event, or None if invalid."""
        if not self._configured or not self.webhook_secret:
            logger.warning("Webhook received but Stripe is not configured")
            return None
        try:
            return _stripe.Webhook.construct_event(
                payload, signature, self.webhook_secret
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Webhook signature verification failed: %s", exc)
            return None
