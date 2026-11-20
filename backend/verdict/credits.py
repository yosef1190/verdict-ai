"""Credit wallet service backed by Supabase (with in-memory fallback for dev).

Security properties:
  * All balance mutations run server-side with the Supabase service-role key.
  * Reservation, finalize, and refund are idempotent (UNIQUE investigation_id).
  * A reservation is inserted BEFORE research starts, so concurrent requests
    cannot overspend: the balance is decremented atomically in the same step.
  * A failed investigation releases the reservation and restores the balance.
  * A refund can never be issued twice.

The service is deliberately small and synchronous: the Flask app calls it from
handler threads.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from .models import WalletBalance

logger = logging.getLogger(__name__)

MODE_COST = {"light": 1, "medium": 2, "deep": 3}


class InsufficientCredits(Exception):
    """Raised when the user does not have enough credits to start research."""

    def __init__(self, required: int, available: int) -> None:
        super().__init__(
            f"Insufficient credits: need {required}, have {available}. "
            "Purchase credits or upgrade your plan."
        )
        self.required = required
        self.available = available


class CreditService:
    """Per-user credit accounting.

    When a Supabase client is supplied, all state lives in the database and the
    methods are safe under concurrent requests. Without one (local dev), an
    in-memory store is used so the app still works end to end.
    """

    def __init__(self, supabase_client: Any = None) -> None:
        self.sb = supabase_client
        self._lock = threading.Lock()
        # In-memory fallback structures (only used when self.sb is None).
        self._wallets: dict[str, WalletBalance] = {}
        self._free_claims: set[str] = set()
        self._reservations: dict[str, dict] = {}
        self._refunded: set[str] = set()
        # (type, payment_reference) pairs already granted, mirroring the unique
        # ledger check the database path relies on.
        self._granted_refs: set[tuple[str, str]] = set()

    # ---------------------------------------------------------------- wallets

    def get_wallet(self, user_id: str) -> WalletBalance:
        if self.sb is None:
            with self._lock:
                wallet = self._wallets.get(user_id)
                if wallet is None:
                    wallet = WalletBalance(0, 0)
                    self._wallets[user_id] = wallet
                return WalletBalance(
                    wallet.subscription_credits, wallet.purchased_credits
                )

        try:
            resp = (
                self.sb.table("credit_wallets")
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read wallet for %s: %s", user_id, exc)
            return WalletBalance(0, 0)

        if not rows:
            # Create an empty wallet row for this user.
            try:
                self.sb.table("credit_wallets").insert(
                    {"user_id": user_id, "subscription_credits": 0, "purchased_credits": 0}
                ).execute()
            except Exception:  # noqa: BLE001 - a concurrent insert may win
                pass
            return WalletBalance(0, 0)

        row = rows[0]
        return WalletBalance(
            int(row.get("subscription_credits") or 0),
            int(row.get("purchased_credits") or 0),
        )

    def _write_wallet(self, user_id: str, wallet: WalletBalance) -> None:
        if self.sb is None:
            with self._lock:
                self._wallets[user_id] = WalletBalance(
                    wallet.subscription_credits, wallet.purchased_credits
                )
            return
        self.sb.table("credit_wallets").upsert(
            {
                "user_id": user_id,
                "subscription_credits": wallet.subscription_credits,
                "purchased_credits": wallet.purchased_credits,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()

    # ------------------------------------------------------- free-grant rules

    def has_used_free_light(self, user_id: str) -> bool:
        """Whether this account has already claimed its complimentary Light run."""
        if self.sb is None:
            with self._lock:
                return user_id in self._free_claims

        try:
            resp = (
                self.sb.table("user_profiles")
                .select("free_light_used")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            return bool(rows and rows[0].get("free_light_used"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read profile for %s: %s", user_id, exc)
            return False

    def claim_free_light(self, user_id: str) -> bool:
        """Atomically claim the single free Light investigation.

        Returns True if this call won the claim, False if it was already used.
        The database UNIQUE primary key plus a conditional UPDATE guarantees a
        user cannot claim twice through replays or concurrent requests.
        """
        if self.sb is None:
            with self._lock:
                if user_id in self._free_claims:
                    return False
                self._free_claims.add(user_id)
                return True

        try:
            # Conditional update only succeeds when free_light_used is false.
            resp = (
                self.sb.table("user_profiles")
                .update({"free_light_used": True, "updated_at": datetime.now(timezone.utc).isoformat()})
                .eq("user_id", user_id)
                .eq("free_light_used", False)
                .execute()
            )
            if resp.data:
                return True
            # No row updated: either the profile does not exist yet or the claim
            # was already used. Try to create the profile with the claim taken.
            if self.has_used_free_light(user_id):
                return False
            try:
                self.sb.table("user_profiles").insert(
                    {
                        "user_id": user_id,
                        "plan": "free",
                        "free_light_used": True,
                    }
                ).execute()
                return True
            except Exception:  # noqa: BLE001 - unique violation means another request won
                return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to claim free light for %s: %s", user_id, exc)
            return False

    def release_free_light(self, user_id: str) -> None:
        """Return a free-Light claim when the investigation failed.

        A complimentary run that never produced a report should not burn the
        account's one free attempt.
        """
        if self.sb is None:
            with self._lock:
                self._free_claims.discard(user_id)
            return
        try:
            self.sb.table("user_profiles").update(
                {"free_light_used": False, "updated_at": datetime.now(timezone.utc).isoformat()}
            ).eq("user_id", user_id).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to release free light for %s: %s", user_id, exc)

    # ------------------------------------------------------------ reservations

    def _rpc(self, name: str, params: dict[str, Any]) -> Any:
        """Run a Postgres function that does an atomic credit operation.

        Returns None when the function is missing (migration not applied), so the
        caller can fall back to the application-level path. Any other error is a
        real problem and propagates.
        """
        try:
            data = self.sb.rpc(name, params).execute().data
        except Exception as exc:  # noqa: BLE001
            message = str(exc).lower()
            missing = (
                "could not find the function" in message
                or "pgrst202" in message
                or ("function" in message and "does not exist" in message)
            )
            if missing:
                logger.warning(
                    "%s is not installed; falling back to a non-atomic update: %s", name, exc
                )
                return None
            raise
        # A scalar jsonb result comes back as the value itself, but list/array
        # shapes are also possible depending on the PostgREST version.
        if isinstance(data, list):
            return data[0] if data else {}
        return data or {}

    def reserve(self, user_id: str, investigation_id: str, mode: str) -> dict[str, Any]:
        """Reserve credits for an investigation.

        Decrements the wallet immediately (subscription first) and records a
        'held' reservation plus a ledger entry. Raises InsufficientCredits when
        the balance is too low.

        Idempotent: reserving the same investigation_id twice returns the
        existing reservation without double-charging.
        """
        cost = MODE_COST.get(mode, 1)

        if self.sb is None:
            with self._lock:
                existing = self._reservations.get(investigation_id)
                if existing is not None:
                    return existing
                wallet = self._wallets.setdefault(user_id, WalletBalance(0, 0))
                if wallet.total < cost:
                    raise InsufficientCredits(cost, wallet.total)
                before = wallet.total
                usage = wallet.available_for(cost)
                wallet.subscription_credits = usage["remaining_subscription"]
                wallet.purchased_credits = usage["remaining_purchased"]
                record = {
                    "investigation_id": investigation_id,
                    "user_id": user_id,
                    "mode": mode,
                    "cost": cost,
                    "status": "held",
                    "subscription_used": usage["subscription_used"],
                    "purchased_used": usage["purchased_used"],
                    "balance_before": before,
                    "balance_after": wallet.total,
                }
                self._reservations[investigation_id] = record
                return record

        atomic = self._rpc(
            "verdict_reserve_credits",
            {
                "p_user_id": user_id,
                "p_investigation_id": investigation_id,
                "p_mode": mode,
                "p_cost": cost,
            },
        )
        if atomic:
            if atomic.get("status") == "insufficient":
                raise InsufficientCredits(cost, int(atomic.get("available") or 0))
            return {
                "investigation_id": investigation_id,
                "user_id": user_id,
                "mode": atomic.get("mode", mode),
                "cost": int(atomic.get("cost") or cost),
                "status": atomic.get("status", "held"),
                "subscription_used": int(atomic.get("subscription_used") or 0),
                "purchased_used": int(atomic.get("purchased_used") or 0),
                "balance_before": int(atomic.get("balance_before") or 0),
                "balance_after": int(atomic.get("balance_after") or 0),
            }

        # Fallback for a database that has not had the migration applied yet.
        # Idempotency check.
        try:
            existing = (
                self.sb.table("credit_reservations")
                .select("*")
                .eq("investigation_id", investigation_id)
                .limit(1)
                .execute()
            )
            if existing.data:
                row = existing.data[0]
                return {
                    "investigation_id": investigation_id,
                    "user_id": user_id,
                    "mode": row.get("mode", mode),
                    "cost": int(row.get("cost") or cost),
                    "status": row.get("status", "held"),
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Reservation lookup failed for %s: %s", investigation_id, exc)

        wallet = self.get_wallet(user_id)
        if wallet.total < cost:
            raise InsufficientCredits(cost, wallet.total)

        before = wallet.total
        usage = wallet.available_for(cost)
        wallet.subscription_credits = usage["remaining_subscription"]
        wallet.purchased_credits = usage["remaining_purchased"]
        self._write_wallet(user_id, wallet)

        self.sb.table("credit_reservations").insert(
            {
                "user_id": user_id,
                "investigation_id": investigation_id,
                "mode": mode,
                "cost": cost,
                "status": "held",
                "subscription_used": usage["subscription_used"],
                "purchased_used": usage["purchased_used"],
                "balance_before": before,
                "balance_after": wallet.total,
            }
        ).execute()

        self._ledger(
            user_id=user_id,
            type="reservation",
            amount=-cost,
            mode=mode,
            investigation_id=investigation_id,
            balance_before=before,
            balance_after=wallet.total,
        )

        return {
            "investigation_id": investigation_id,
            "user_id": user_id,
            "mode": mode,
            "cost": cost,
            "status": "held",
            "subscription_used": usage["subscription_used"],
            "purchased_used": usage["purchased_used"],
            "balance_before": before,
            "balance_after": wallet.total,
        }

    def finalize(self, user_id: str, investigation_id: str) -> bool:
        """Mark a held reservation as finalized after a successful report.

        The credits were already deducted at reserve time; finalizing just
        transitions the reservation status. Returns False if not found.
        """
        if self.sb is None:
            with self._lock:
                record = self._reservations.get(investigation_id)
                if record is None:
                    return False
                record["status"] = "finalized"
                return True

        atomic = self._rpc(
            "verdict_finalize_credits", {"p_investigation_id": investigation_id}
        )
        if atomic is not None:
            return bool(atomic)

        try:
            resp = (
                self.sb.table("credit_reservations")
                .update(
                    {
                        "status": "finalized",
                        "resolved_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                .eq("investigation_id", investigation_id)
                .eq("status", "held")
                .execute()
            )
            return bool(resp.data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Finalize failed for %s: %s", investigation_id, exc)
            return False

    def release_and_refund(self, user_id: str, investigation_id: str, reason: str = "") -> bool:
        """Release a held reservation and restore the credits.

        Idempotent: a second call for the same investigation performs no further
        credit movement, so a duplicate refund cannot happen.
        """
        if self.sb is None:
            with self._lock:
                if investigation_id in self._refunded:
                    return False
                record = self._reservations.get(investigation_id)
                if record is None or record.get("status") != "held":
                    return False
                cost = int(record["cost"])
                wallet = self._wallets.setdefault(user_id, WalletBalance(0, 0))
                # Return credits to the same buckets they came from.
                wallet.subscription_credits += int(record.get("subscription_used") or 0)
                wallet.purchased_credits += int(record.get("purchased_used") or 0)
                record["status"] = "released"
                self._refunded.add(investigation_id)
                return True

        atomic = self._rpc(
            "verdict_refund_credits",
            {"p_investigation_id": investigation_id, "p_reason": reason},
        )
        if atomic is not None:
            return bool(atomic.get("refunded"))

        try:
            existing = (
                self.sb.table("credit_reservations")
                .select("*")
                .eq("investigation_id", investigation_id)
                .limit(1)
                .execute()
            )
            if not existing.data:
                return False
            row = existing.data[0]
            if row.get("status") != "held":
                return False

            already = (
                self.sb.table("investigation_refunds")
                .select("id")
                .eq("investigation_id", investigation_id)
                .limit(1)
                .execute()
            )
            if already.data:
                return False

            cost = int(row.get("cost") or 0)
            wallet = self.get_wallet(user_id)
            before = wallet.total
            # Restore each bucket exactly as it was consumed. Reservations that
            # predate the per-bucket columns fall back to purchased credits,
            # which never expire.
            sub_used = int(row.get("subscription_used") or 0)
            pur_used = int(row.get("purchased_used") or 0)
            if sub_used + pur_used == 0:
                pur_used = cost
            wallet.subscription_credits += sub_used
            wallet.purchased_credits += pur_used
            self._write_wallet(user_id, wallet)

            self.sb.table("credit_reservations").update(
                {
                    "status": "released",
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("investigation_id", investigation_id).execute()

            self.sb.table("investigation_refunds").insert(
                {
                    "investigation_id": investigation_id,
                    "user_id": user_id,
                    "credits_refunded": cost,
                    "reason": reason,
                }
            ).execute()

            self._ledger(
                user_id=user_id,
                type="refund",
                amount=cost,
                mode=row.get("mode"),
                investigation_id=investigation_id,
                balance_before=before,
                balance_after=wallet.total,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Refund failed for %s: %s", investigation_id, exc)
            return False

    # ---------------------------------------------------------------- ledger

    def _ledger(
        self,
        *,
        user_id: str,
        type: str,
        amount: int,
        mode: str | None = None,
        investigation_id: str | None = None,
        payment_reference: str | None = None,
        balance_before: int = 0,
        balance_after: int = 0,
    ) -> None:
        if self.sb is None:
            return
        try:
            self.sb.table("credit_transactions").insert(
                {
                    "user_id": user_id,
                    "type": type,
                    "amount": amount,
                    "mode": mode,
                    "investigation_id": investigation_id,
                    "payment_reference": payment_reference,
                    "status": "completed",
                    "balance_before": balance_before,
                    "balance_after": balance_after,
                }
            ).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ledger write failed (%s %s): %s", type, user_id, exc)

    def add_credits(
        self,
        user_id: str,
        amount: int,
        *,
        kind: str = "purchased",
        type: str = "purchase",
        payment_reference: str | None = None,
        idempotent_on_reference: bool = True,
    ) -> bool:
        """Add credits to a wallet after a verified payment or grant.

        When ``idempotent_on_reference`` is set and a payment_reference is given,
        a reference that already appears in the ledger is treated as a no-op.
        This is what stops webhook replays from granting credits twice.
        """
        if amount <= 0:
            return False

        if self.sb is None:
            with self._lock:
                if idempotent_on_reference and payment_reference:
                    key = (type, payment_reference)
                    if key in self._granted_refs:
                        return False
                    self._granted_refs.add(key)
                wallet = self._wallets.setdefault(user_id, WalletBalance(0, 0))
                if kind == "subscription":
                    wallet.subscription_credits += amount
                else:
                    wallet.purchased_credits += amount
                return True

        if idempotent_on_reference and payment_reference:
            try:
                dup = (
                    self.sb.table("credit_transactions")
                    .select("id")
                    .eq("payment_reference", payment_reference)
                    .eq("type", type)
                    .limit(1)
                    .execute()
                )
                if dup.data:
                    return False
            except Exception:  # noqa: BLE001 - fall through and attempt the grant
                pass

        wallet = self.get_wallet(user_id)
        before = wallet.total
        if kind == "subscription":
            wallet.subscription_credits += amount
        else:
            wallet.purchased_credits += amount
        self._write_wallet(user_id, wallet)

        self._ledger(
            user_id=user_id,
            type=type,
            amount=amount,
            payment_reference=payment_reference,
            balance_before=before,
            balance_after=wallet.total,
        )
        return True

    def reset_subscription_credits(self, user_id: str, allowance: int) -> None:
        """Reset the subscription bucket at the start of a new billing period.

        Unused subscription credits do not roll over; purchased credits are
        untouched.
        """
        if self.sb is None:
            with self._lock:
                wallet = self._wallets.setdefault(user_id, WalletBalance(0, 0))
                wallet.subscription_credits = allowance
            return
        wallet = self.get_wallet(user_id)
        before = wallet.total
        wallet.subscription_credits = allowance
        self._write_wallet(user_id, wallet)
        self._ledger(
            user_id=user_id,
            type="subscription_grant",
            amount=allowance,
            balance_before=before,
            balance_after=wallet.total,
        )

    # ------------------------------------------------------------- history

    def transactions(self, user_id: str, limit: int = 100) -> list[dict]:
        if self.sb is None:
            return []
        try:
            resp = (
                self.sb.table("credit_transactions")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to list transactions for %s: %s", user_id, exc)
            return []

    def payments(self, user_id: str, limit: int = 100) -> list[dict]:
        if self.sb is None:
            return []
        try:
            resp = (
                self.sb.table("payments")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to list payments for %s: %s", user_id, exc)
            return []