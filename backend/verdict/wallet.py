"""Credit wallet and reservation logic for the SaaS SaaS upgrade.

Handles:
- Subscription credit management (monthly/annual allowances, rollover rules)
- Purchased credit management (never expire, survive cancellation)
- Credit reservation for investigations (prevents double-spending)
- Credit consumption: subscription first, then purchased
- Failed investigation refunds
- Transaction ledger records
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .models import (
    CreditReservation,
    CreditTransaction,
    Subscription,
    Investigation,
)


def calculate_price(plan: str, quantity: int | None = None, **kwargs: Any) -> dict[str, Any]:
    """Calculate the price for a given plan and quantity.

    This is the server-side price calculator. The frontend must never
    determine prices; it must send the desired quantity and the backend
    returns the total.

    Args:
        plan: One of "free", "pay_as_you_go", "research_pro", "business"
        quantity: Number of credit bundles (for pay_as_you_go)
        **kwargs: Additional plan-specific params (e.g., months for pro/annual)

    Returns:
        dict with total_cents, breakdown, and applicable features
    """
    from .config import Settings

    settings = Settings()
    pricing = settings.PRICING[plan]

    if plan == "free":
        return {
            "total_cents": 0,
            "description": "Free plan — no charge",
            "features": pricing["features"],
        }

    if plan == "pay_as_you_go":
        if quantity is None or quantity < 1:
            raise ValueError("pay_as_you_go requires quantity >= 1")
        if quantity < pricing["min_purchase"]:
            raise ValueError(f"Minimum purchase is {pricing['min_purchase']} credits")

        # Map quantity to the correct tier; tiers are keyed by minimum quantity
        # (5, 10, 25, 50, 100) and the value is the per-credit price.
        tier_key = "100"
        for key in sorted(pricing["pricing_tiers"].keys(), key=int):
            if quantity >= int(key):
                tier_key = key
            else:
                break

        unit_price = pricing["pricing_tiers"][tier_key]
        total_cents = int(round(quantity * unit_price * 100))
        return {
            "total_cents": total_cents,
            "description": f"{quantity} credits at ${unit_price:.2f} per credit",
            "features": pricing["features"],
            "unit_price_cents": int(round(unit_price * 100)),
            "unit_price": unit_price,
            "quantity": quantity,
        }

    if plan == "research_pro":
        monthly = kwargs.get("monthly", True)
        if monthly:
            total_cents = int(round(pricing["monthly_cost"] * 100))
            return {
                "total_cents": total_cents,
                "description": f"Research Pro monthly subscription (${pricing['monthly_cost']:.2f}/month)",
                "features": pricing["features"],
                "monthly_cost": pricing["monthly_cost"],
                "credits_per_month": pricing["monthly_credits"],
                "interval": "monthly",
            }
        else:
            total_cents = int(round(pricing["annual_cost"] * 100))
            annual_monthly_credits = pricing["annual_credits_per_month"]
            return {
                "total_cents": total_cents,
                "description": f"Research Pro annual subscription (${pricing['annual_cost']/12:.2f}/month equivalent)",
                "features": pricing["features"],
                "annual_cost": pricing["annual_cost"],
                "monthly_equivalent": pricing["annual_cost"] / 12,
                "credits_per_month": annual_monthly_credits,
                "interval": "annual",
            }

    if plan == "business":
        monthly = kwargs.get("monthly", True)
        if monthly:
            total_cents = int(round(pricing["monthly_cost"] * 100))
            return {
                "total_cents": total_cents,
                "description": f"Business monthly subscription (${pricing['monthly_cost']:.2f}/month)",
                "features": pricing["features"],
                "monthly_cost": pricing["monthly_cost"],
                "credits_per_month": pricing["monthly_credits"],
                "interval": "monthly",
            }
        else:
            total_cents = int(round(pricing["annual_cost"] * 100))
            return {
                "total_cents": total_cents,
                "description": f"Business annual subscription (${pricing['annual_cost']/12:.2f}/month equivalent)",
                "features": pricing["features"],
                "annual_cost": pricing["annual_cost"],
                "monthly_equivalent": pricing["annual_cost"] / 12,
                "credits_per_month": pricing["annual_credits_per_month"],
                "interval": "annual",
            }

    raise ValueError(f"Unknown plan: {plan}")


def consume_credits(
    wallet: WalletBalance,
    cost: int,
    investigation_mode: str,
) -> dict[str, Any]:
    """Consume credits from a wallet, returning usage breakdown.

    Credits are always consumed: subscription first, then purchased.
    Returns a dict with subscription_used, purchased_used, and the remaining wallet.

    Raises ValueError if insufficient credits.
    """
    if wallet.total < cost:
        raise ValueError(
            f"Insufficient credits: have {wallet.total}, need {cost}"
        )

    result = wallet.available_for(cost, subscription_first=True)
    sub_used = result["subscription_used"]
    purchased_used = result["purchased_used"]

    # Check subscription credits are enough or we have purchased to cover
    if sub_used < cost and (wallet.subscription_credits + wallet.purchased_credits) < cost:
        raise ValueError("Insufficient credits")

    # Update wallet in-place
    wallet.subscription_credits = result["remaining_subscription"]
    wallet.purchased_credits = result["remaining_purchased"]

    return {
        "subscription_used": sub_used,
        "purchased_used": purchased_used,
        "remaining_subscription": wallet.subscription_credits,
        "remaining_purchased": wallet.purchased_credits,
        "total_remaining": wallet.total,
        "mode": investigation_mode,
    }


def release_reservation(reservation: CreditReservation) -> None:
    """Release a credit reservation (e.g., after investigation failure).

    This restores the original balances. In a real DB-backed system,
    this would update the user's wallet balance.
    """
    reservation.released = True


def finalize_reservation(
    reservation: CreditReservation,
    wallet: WalletBalance,
    cost: int,
) -> dict[str, Any]:
    """Finalize a credit reservation by deducting from the wallet.

    This should be called after a successful investigation report is delivered.
    The credits are consumed and a transaction record is created.
    """
    if reservation.finalized:
        return {"status": "already_finalized"}

    # Consume credits
    result = consume_credits(wallet, cost, reservation.mode)

    # Mark reservation as finalized
    reservation.finalized = True

    return {
        "status": "finalized",
        "subscription_used": result["subscription_used"],
        "purchased_used": result["purchased_used"],
        "remaining_subscription": result["remaining_subscription"],
        "remaining_purchased": result["remaining_purchased"],
    }


def create_transaction(
    user_id: str,
    type: str,
    amount: int,
    mode: str | None = None,
    investigation_id: str | None = None,
    payment_reference: str | None = None,
    balance_before: int = 0,
    balance_after: int = 0,
) -> CreditTransaction:
    """Create a credit transaction ledger entry.

    Args:
        user_id: The Supabase user ID
        type: Transaction type key
        amount: Credit amount
        mode: Research mode (light/medium/deep) when applicable
        investigation_id: Associated investigation ID
        payment_reference: Stripe charge/refund ID
        balance_before: Balance before this transaction
        balance_after: Balance after this transaction

    Returns:
        CreditTransaction instance
    """
    tx_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)
    return CreditTransaction(
        transaction_id=tx_id,
        user_id=user_id,
        type=type,
        amount=amount,
        mode=mode,
        investigation_id=investigation_id,
        payment_reference=payment_reference,
        timestamp=timestamp,
        status="completed",
        balance_before=balance_before,
        balance_after=balance_after,
    )


def get_mode_cost(mode: str) -> int:
    """Return the credit cost for a given research mode."""
    return {"light": 1, "medium": 2, "deep": 3}.get(mode, 1)