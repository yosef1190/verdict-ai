"""Small data containers shared across the pipeline.

Containers for sources, search results, research plans, and — new for this SaaS upgrade —
the credit wallet, subscriptions, reservations, and transaction ledger.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Source:
    """A fetched page (or a search-result snippet standing in for one)."""

    url: str
    title: str
    text: str
    description: str = ""
    site_name: str = ""
    author: str = ""
    published: str = ""
    status_code: int = 200
    error: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.text.strip())


@dataclass
class SourceSummary:
    """AI summary of a single source."""

    title: str
    url: str
    summary: str
    model: str = ""
    snippet: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class ResearchPlan:
    """AI-generated research plan for a product page."""

    name: str = ""
    brand: str = ""
    model: str = ""
    category: str = ""
    claims: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """One organic search result."""

    title: str
    url: str
    snippet: str = ""
    engine: str = ""

    def as_source(self, error: str = "") -> Source:
        return Source(
            url=self.url,
            title=self.title or self.url,
            text=self.snippet,
            description=self.snippet,
            error=error,
        )


# ============================================================================
# Credit Wallet and Subscription Models (SaaS upgrade)
# ============================================================================


class WalletBalance:
    """Represents a user's credit balances.

    Two independent balances are tracked:
    1. subscription_credits: resets every billing cycle, does not roll over
    2. purchased_credits: never expire, survive subscription cancellation
    """

    def __init__(
        self,
        subscription_credits: int = 0,
        purchased_credits: int = 0,
    ) -> None:
        self.subscription_credits = subscription_credits
        self.purchased_credits = purchased_credits

    @property
    def total(self) -> int:
        return self.subscription_credits + self.purchased_credits

    def available_for(self, cost: int, subscription_first: bool = True) -> dict[str, int]:
        """Return how many subscription and purchased credits are available for a given cost.

        Credits are consumed: subscription first, then purchased.
        Returns a dict with 'subscription_used' and 'purchased_used'.
        """
        sub_used = min(self.subscription_credits, cost)
        remaining = cost - sub_used
        purchased_used = min(self.purchased_credits, remaining)
        return {
            "subscription_used": sub_used,
            "purchased_used": purchased_used,
            "remaining_subscription": self.subscription_credits - sub_used,
            "remaining_purchased": self.purchased_credits - purchased_used,
        }


@dataclass
class CreditReservation:
    """A reservation of credits for an investigation.

    When an investigation starts, the required credits are reserved.
    If the investigation fails, the reservation is released.
    If the investigation succeeds, the reservation is finalized (deducted).

    This prevents double-spending even with concurrent requests.
    """

    investigation_id: str
    mode: str  # "light" | "medium" | "deep"
    cost: int
    reserved_at: datetime
    released: bool = False
    finalized: bool = False


@dataclass
class CreditTransaction:
    """A record in the credit transaction ledger.

    Every credit movement is immutable except for status transitions.
    Users can view their full transaction history.
    """

    transaction_id: str
    user_id: str
    type: str  # "subscription_grant", "purchase", "reservation", "refund", "consumption"
    amount: int
    mode: str | None = None  # light/medium/deep when applicable
    investigation_id: str | None = None
    payment_reference: str | None = None  # Stripe charge/refund ID
    timestamp: datetime = field(default_factory=datetime.now)
    status: str = "completed"  # completed | pending | failed | refunded
    balance_before: int = 0
    balance_after: int = 0


@dataclass
class Subscription:
    """A user's active subscription."""

    id: str
    user_id: str
    plan: str  # "research_pro" | "business"
    kind: str  # "monthly" | "annual"
    status: str  # "active" | "canceled" | "past_due"
    started_at: datetime
    credits_this_period: int  # monthly_credits or annual_credits_per_month
    period_end: datetime
    canceled_at: datetime | None = None


@dataclass
class Investigation:
    """Metadata about a research investigation."""

    id: str
    user_id: str
    mode: str  # "light" | "medium" | "deep"
    cost: int
    status: str  # "starting" | "running" | "completed" | "failed" | "refunded"
    started_at: datetime
    completed_at: datetime | None = None
    report_path: str | None = None
    refunded: bool = False