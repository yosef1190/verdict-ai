#!/usr/bin/env python3
"""Verdict Research website (Flask).

    python web.py                 # http://127.0.0.1:5000
    flask --app web run --debug

Jobs run in background threads. The browser starts one with POST /api/research
and polls GET /api/jobs/<id> for progress and the finished report.
Supabase is used for job persistence so jobs survive Render free-tier sleeping.

SaaS monetization: every user has a credit wallet (subscription + purchased
balances). Starting an investigation reserves credits first; a successful report
finalizes the reservation, a failed one releases and refunds it.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

from flask import Flask, jsonify, request
from markdown_it import MarkdownIt

try:
    import sentry_sdk  # optional; only used if configured
except Exception:  # pragma: no cover
    sentry_sdk = None

from verdict import __version__
from verdict.config import Settings
from verdict.credits import CreditService, InsufficientCredits, MODE_COST
from verdict.errors import VerdictError
from verdict.payments import PaymentNotConfigured, PaymentService
from verdict.pipeline import RESEARCH_MODES, ResearchRequest, run_research

# "js-default" keeps raw HTML disabled, so scraped or AI text can never inject
# markup, and it refuses javascript: links.
_md = MarkdownIt("js-default", {"linkify": False})

JOB_TTL_SECONDS = 60 * 60  # finished jobs are forgotten after an hour
MAX_STEPS = 200

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supabase client (service role: server-only, never exposed to the browser)
# ---------------------------------------------------------------------------
try:
    from supabase import Client, create_client
except Exception:  # pragma: no cover
    Client = None  # type: ignore
    create_client = None  # type: ignore

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

if create_client and SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    sb: Client | None = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
else:
    sb = None

credit_service = CreditService(sb)
payment_service = PaymentService()


RELAY_SECRET = os.getenv("VERDICT_RELAY_SECRET", "").strip()
CRON_SECRET = os.getenv("VERDICT_CRON_SECRET", "").strip()

PLAN_ALLOWANCE = {"research_pro": 50, "business": 150}
PLAN_PRICES = {
    "research_pro": {"monthly": 1499, "annual": 14999},
    "business": {"monthly": 2999, "annual": 29999},
}

_webhook_events: set[str] = set()
_webhook_lock = threading.Lock()


def _iso(value: object) -> str | None:
    """Stripe timestamps are unix seconds; Supabase expects ISO timestamps."""
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _days_left(value: str | None) -> int | None:
    if not value:
        return None
    try:
        end = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, (end - datetime.now(timezone.utc)).days)


def _user_from_request():
    """Return the authenticated user for the request, or None.

    A bearer token is always verified with Supabase when Supabase is
    configured, so a caller cannot simply claim another account.

    The Next.js relay forwards the already-verified user id in ``X-User-Id``.
    That header is trusted only when a shared relay secret is configured and
    matches, which stops anyone who can reach this service directly from
    impersonating an account.
    """
    token = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    if token and sb is not None:
        try:
            resp = sb.auth.get_user(token)
            if resp and resp.user:
                return resp.user
        except Exception:  # noqa: BLE001 - fall through to the relay check
            pass

    forwarded = (request.headers.get("X-User-Id") or "").strip()
    relay_secret = (request.headers.get("X-Relay-Secret") or "").strip()
    secret_ok = bool(RELAY_SECRET) and secrets.compare_digest(relay_secret, RELAY_SECRET)

    # Without a configured relay secret we only trust the header when Supabase
    # is absent entirely (local development with no real data).
    if forwarded and (secret_ok or (not RELAY_SECRET and sb is None)):
        return {"id": forwarded}

    return None


class Job:
    def __init__(self, req: ResearchRequest, user_id: str | None = None) -> None:
        self.id = uuid.uuid4().hex
        self.req = req
        self.user_id = user_id
        self.status = "queued"  # queued | running | done | error
        self.steps: list[str] = []
        self.error = ""
        self.title = ""
        self.markdown = ""
        self.html = ""
        self.sources: list[dict] = []
        self.models: list[str] = []
        self.stage_timings: dict = {}
        self.metrics: dict = {}
        self.reserved = False
        self.free_grant = False
        self.created = time.time()
        self.finished: float | None = None
        self.lock = threading.Lock()

    def progress(self, message: str) -> None:
        with self.lock:
            if len(self.steps) < MAX_STEPS:
                self.steps.append(message)

    def snapshot(self, since: int = 0) -> dict:
        with self.lock:
            data = {
                "id": self.id,
                "status": self.status,
                "steps": self.steps[since:],
                "step_count": len(self.steps),
                "mode": self.req.mode,
                "cost": MODE_COST.get(self.req.mode, 1),
                "stage_timings": self.stage_timings,
                "metrics": self.metrics,
            }
            if self.status == "error":
                data["error"] = self.error
            if self.status == "done":
                data.update(
                    title=self.title,
                    markdown=self.markdown,
                    html=self.html,
                    sources=self.sources,
                    models=self.models,
                )
            return data


# ---------------------------------------------------------------------------
# Supabase job persistence helpers
# ---------------------------------------------------------------------------
def _supabase_update_job(job_id: str, data: dict) -> None:
    if sb is None:
        return
    try:
        sb.table("research_jobs").update(data).eq("id", job_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to update job %s: %s", job_id, exc)


def _supabase_get_job(job_id: str) -> dict | None:
    if sb is None:
        return None
    try:
        resp = sb.table("research_jobs").select("*").eq("id", job_id).single().execute()
        return resp.data if resp.data else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to get job %s: %s", job_id, exc)
        return None


def _supabase_create_job(
    job_id: str,
    user_id: str | None,
    status: str,
    progress: list,
    mode: str = "light",
    cost: int = 1,
) -> None:
    if sb is None:
        return
    try:
        sb.table("research_jobs").insert(
            {
                "id": job_id,
                "user_id": user_id,
                "status": status,
                "progress": progress,
                "error": "",
                "mode": mode,
                "cost": cost,
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to create job %s: %s", job_id, exc)


def _supabase_record_investigation(job: Job) -> None:
    """Keep a durable record of delivered reports for wallet statistics."""
    if sb is None or not job.user_id:
        return
    try:
        sb.table("investigations").upsert(
            {
                "id": job.id,
                "user_id": job.user_id,
                "mode": job.req.mode,
                "cost": MODE_COST.get(job.req.mode, 1),
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "report_title": job.title,
                "report_markdown": job.markdown,
                "report_html": job.html,
                "sources": job.sources,
                "stage_timings": job.stage_timings,
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record investigation %s: %s", job.id, exc)


def _subscription_for_user(user_id: str) -> dict | None:
    if sb is None:
        return None
    try:
        resp = (
            sb.table("subscriptions")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(10)
            .execute()
        )
        rows = resp.data or []
        for row in rows:
            if row.get("status") in ("active", "trialing", "past_due", "unpaid"):
                return row
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read subscription for %s: %s", user_id, exc)
        return None


def _subscription_by_stripe_id(subscription_id: str) -> dict | None:
    if sb is None or not subscription_id:
        return None
    try:
        resp = (
            sb.table("subscriptions")
            .select("*")
            .eq("stripe_subscription_id", subscription_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception:  # noqa: BLE001
        return None


def _public_subscription(row: dict | None) -> dict | None:
    if not row:
        return None
    end = row.get("current_period_end")
    canceled = bool(row.get("cancel_at_period_end"))
    status = row.get("status") or "active"
    if canceled and status in ("active", "trialing"):
        display = "cancelled"
    else:
        display = str(status).replace("_", " ")
    plan = row.get("plan")
    interval = row.get("billing_interval")
    return {
        "id": row.get("id"),
        "plan": plan,
        "plan_label": "Research Pro" if plan == "research_pro" else "Business",
        "billing_interval": interval,
        "status": status,
        "display_status": display,
        "cancel_at_period_end": canceled,
        "credits_per_period": row.get("credits_per_period") or 0,
        "price_cents": PLAN_PRICES.get(plan, {}).get(interval),
        "current_period_start": row.get("current_period_start"),
        "current_period_end": end,
        "access_ends_at": end if (canceled or status in ("canceled", "expired", "unpaid")) else None,
        "days_remaining": _days_left(end),
        "canceled_at": row.get("canceled_at"),
        "started_at": row.get("created_at"),
        "last_credit_month": row.get("last_credit_month"),
        "stripe_subscription_id": row.get("stripe_subscription_id"),
        "has_stripe_subscription": bool(row.get("stripe_subscription_id")),
        "renews": not canceled and status in ("active", "trialing"),
    }


def _claim_webhook_event(event_id: str, event_type: str) -> bool:
    """True when this event has not been processed before."""
    if not event_id:
        return True
    if sb is None:
        with _webhook_lock:
            if event_id in _webhook_events:
                return False
            _webhook_events.add(event_id)
            return True
    try:
        result = sb.rpc(
            "verdict_claim_webhook_event",
            {"p_event_id": event_id, "p_type": event_type},
        ).execute().data
        if isinstance(result, list):
            return bool(result[0]) if result else False
        return bool(result)
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if "could not find the function" in message or "pgrst202" in message:
            logger.warning("Webhook dedupe function missing; using local marker")
            with _webhook_lock:
                key = f"{event_type}:{event_id}"
                if key in _webhook_events:
                    return False
                _webhook_events.add(key)
                return True
        logger.exception("Could not claim webhook event %s", event_id)
        raise


def _plan_from_price(price_id: str) -> tuple[str | None, str | None]:
    for key, configured in payment_service.price_ids.items():
        if configured and configured == price_id:
            plan, interval = key.split(":", 1)
            return plan, interval
    return None, None


def _allowance_for(plan: str | None) -> int:
    return PLAN_ALLOWANCE.get(plan or "", 0) or PLAN_ALLOWANCE["research_pro"]


def _grant_subscription(
    user_id: str,
    plan: str | None,
    reference: str,
    *,
    reset: bool = True,
    amount_cents: int | None = None,
    subscription_id: str | None = None,
) -> bool:
    """Allocate monthly credits once per Stripe reference."""
    allowance = _allowance_for(plan)
    if not allowance or not user_id:
        return False
    granted = credit_service.grant_credits(
        user_id,
        allowance,
        kind="subscription",
        type="subscription_grant",
        reference=reference,
        reset=reset,
        amount_cents=amount_cents,
        description=f"Monthly {PLAN_ALLOWANCE.get(plan or '', allowance)} credits",
    )
    if granted and sb is not None and subscription_id:
        try:
            sb.table("subscriptions").update(
                {"last_credit_month": datetime.now(timezone.utc).strftime("%Y-%m")}
            ).eq("stripe_subscription_id", subscription_id).execute()
        except Exception:  # noqa: BLE001
            pass
    return granted


def _apply_stripe_subscription(state: dict, user_id: str | None = None) -> None:
    """Persist the authoritative Stripe subscription state."""
    if sb is None:
        return
    sub_id = state.get("id") or ""
    if not sub_id:
        return
    plan, interval = _plan_from_price(state.get("price_id") or "")
    meta = state.get("metadata") or {}
    plan = plan or meta.get("plan")
    interval = interval or meta.get("interval")
    data = {
        "status": state.get("status") or "active",
        "cancel_at_period_end": bool(state.get("cancel_at_period_end")),
        "current_period_start": _iso(state.get("current_period_start")),
        "current_period_end": _iso(state.get("current_period_end")),
        "stripe_customer_id": state.get("customer") or None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if state.get("canceled_at"):
        data["canceled_at"] = _iso(state["canceled_at"])
    if plan in PLAN_ALLOWANCE:
        data["plan"] = plan
        data["credits_per_period"] = PLAN_ALLOWANCE[plan]
    if interval in ("monthly", "annual"):
        data["billing_interval"] = interval

    existing = _subscription_by_stripe_id(sub_id)
    try:
        if existing:
            sb.table("subscriptions").update(data).eq("id", existing["id"]).execute()
        elif user_id:
            sb.table("subscriptions").insert(
                {
                    **data,
                    "user_id": user_id,
                    "plan": plan or "research_pro",
                    "billing_interval": interval or "monthly",
                    "credits_per_period": PLAN_ALLOWANCE.get(plan or "research_pro", 50),
                    "stripe_subscription_id": sub_id,
                    "last_credit_month": datetime.now(timezone.utc).strftime("%Y-%m"),
                }
            ).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to persist Stripe subscription %s: %s", sub_id, exc)
        return

    if sb is not None and user_id and state.get("status") in ("active", "trialing"):
        try:
            sb.table("subscriptions").update({"status": "canceled"}).eq(
                "user_id", user_id
            ).neq("stripe_subscription_id", sub_id).in_(
                "status", ["active", "trialing"]
            ).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not retire old subscriptions for %s: %s", user_id, exc)


def _public_transaction(row: dict) -> dict:
    """Map an immutable ledger row to the wallet's display fields."""
    kind = row.get("type") or "adjustment"
    labels = {
        "free_grant": "Complimentary Light investigation",
        "subscription_grant": "Subscription credits",
        "purchase": "Credit purchase",
        "reservation": "Research credit used",
        "consumption": "Research credit used",
        "refund": "Investigation refund",
        "adjustment": "Credit adjustment",
    }
    categories = {
        "free_grant": "free_grant",
        "subscription_grant": "subscription_renewal",
        "purchase": "credit_purchase",
        "reservation": "research_consumption",
        "consumption": "research_consumption",
        "refund": "refund",
        "adjustment": "adjustment",
    }
    mode = row.get("mode")
    description = row.get("description") or labels.get(kind, "Credit adjustment")
    if mode and kind in ("reservation", "consumption"):
        description = f"{mode.capitalize()} research"
    return {
        "id": row.get("id"),
        "type": kind,
        "category": categories.get(kind, "adjustment"),
        "description": description,
        "credits": int(row.get("amount") or 0),
        "amount_cents": row.get("amount_cents"),
        "currency": row.get("currency") or "usd",
        "status": row.get("status") or "completed",
        "reference": row.get("payment_reference"),
        "investigation_id": row.get("investigation_id"),
        "balance_after": row.get("balance_after"),
        "created_at": row.get("created_at"),
    }


def _researches_completed(user_id: str) -> int:
    if sb is None:
        return 0
    for table in ("investigations", "credit_reservations"):
        try:
            query = sb.table(table).select("id", count="exact").eq("user_id", user_id)
            if table == "investigations":
                query = query.eq("status", "completed")
            else:
                query = query.eq("status", "finalized")
            resp = query.limit(1).execute()
            return int(resp.count or 0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not count completed research from %s: %s", table, exc)
    return 0


def create_app(settings: Settings | None = None) -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    app.config["SETTINGS"] = settings or Settings.from_env()

    jobs: dict[str, Job] = {}
    jobs_lock = threading.Lock()
    max_concurrent = int(os.getenv("VERDICT_WEB_CONCURRENCY", "3") or 3)
    pool = ThreadPoolExecutor(
        max_workers=max(1, max_concurrent), thread_name_prefix="verdict-job"
    )
    app.config["JOBS"] = jobs
    app.config["POOL"] = pool

    def prune() -> None:
        now = time.time()
        with jobs_lock:
            stale = [
                job_id
                for job_id, job in jobs.items()
                if job.finished and now - job.finished > JOB_TTL_SECONDS
            ]
            for job_id in stale:
                del jobs[job_id]
                if sb is not None:
                    try:
                        sb.table("research_jobs").delete().eq("id", job_id).execute()
                    except Exception:  # noqa: BLE001
                        pass

    def work(job: Job) -> None:
        job.status = "running"
        try:
            result = run_research(job.req, app.config["SETTINGS"], job.progress)
            html = _md.render(result.markdown)
            with job.lock:
                job.title = result.title
                job.markdown = result.markdown
                job.html = html
                job.sources = result.sources
                job.models = result.models
                job.stage_timings = getattr(result, "stage_timings", {}) or {}
                job.metrics = {
                    key: getattr(result, key, None)
                    for key in (
                        "search_queries",
                        "sources_found",
                        "sources_accepted",
                        "sources_rejected",
                        "retry_count",
                        "api_failures",
                    )
                }
                job.status = "done"

            # Finalize credits only after a report was actually delivered.
            if job.reserved and job.user_id:
                credit_service.finalize(job.user_id, job.id)
        except VerdictError as exc:
            with job.lock:
                job.error = str(exc)
                job.status = "error"
            # Refund the reserved credits: no report was delivered.
            if job.reserved and job.user_id:
                credit_service.release_and_refund(
                    job.user_id, job.id, reason="investigation failed"
                )
            elif job.free_grant and job.user_id:
                credit_service.release_free_light(job.user_id)
        except Exception:  # never leak internals to the browser
            logger.exception("Research job %s crashed", job.id)
            with job.lock:
                job.error = "Something went wrong while researching. Please try again."
                job.status = "error"
            if job.reserved and job.user_id:
                credit_service.release_and_refund(
                    job.user_id, job.id, reason="investigation crashed"
                )
            elif job.free_grant and job.user_id:
                credit_service.release_free_light(job.user_id)
        finally:
            job.finished = time.time()
            if job.status == "done":
                _supabase_record_investigation(job)
            if sb is not None:
                try:
                    _supabase_update_job(
                        job.id,
                        {
                            "status": job.status,
                            "error": job.error,
                            "title": job.title,
                            "markdown": job.markdown,
                            "html": job.html,
                            "sources": job.sources,
                            "models": job.models,
                            "stage_timings": job.stage_timings,
                            "metrics": job.metrics,
                            "updated_at": "now()",
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass

    # ------------------------------------------------------------------ pages

    @app.get("/")
    def index():
        return jsonify(
            name="Verdict research API",
            version=__version__,
            modes=list(RESEARCH_MODES.keys()),
        )

    # ------------------------------------------------------------------ status

    @app.get("/api/status")
    def status():
        from verdict.llm import ai_available

        cfg = app.config["SETTINGS"]
        return jsonify(
            version=__version__,
            engines=["yahoo", "brave", "duckduckgo", "bing", "google"],
            ai_ready=ai_available(cfg),
            scrape_ready=bool(cfg.oxylabs_api_key),
            modes={
                name: {
                    "credits": meta["credits"],
                    "target_seconds": meta["target_seconds"],
                }
                for name, meta in RESEARCH_MODES.items()
            },
            payments=payment_service.config_status(),
        )

    @app.get("/healthz")
    def health():
        return jsonify(ok=True)

    # ----------------------------------------------------------------- pricing

    @app.get("/api/pricing")
    def pricing():
        """Public pricing (server-side source of truth)."""
        from verdict.wallet import calculate_price

        cfg = app.config["SETTINGS"]
        payg = cfg.PRICING["pay_as_you_go"]
        tiers = [
            {"quantity": int(qty), "unit_price": price, "total": round(int(qty) * price, 2)}
            for qty, price in sorted(payg["pricing_tiers"].items(), key=lambda i: int(i[0]))
        ]
        return jsonify(
            free=cfg.PRICING["free"],
            pay_as_you_go={**payg, "tiers": tiers},
            research_pro=cfg.PRICING["research_pro"],
            business=cfg.PRICING["business"],
            mode_costs=MODE_COST,
        )

    @app.post("/api/pricing/quote")
    def pricing_quote():
        """Server-calculated quote. The client never sets the total."""
        from verdict.wallet import calculate_price

        payload = request.get_json(silent=True) or {}
        plan = str(payload.get("plan") or "").strip()
        quantity = payload.get("quantity")
        try:
            quantity = int(quantity) if quantity is not None else None
        except (TypeError, ValueError):
            return jsonify(error="quantity must be an integer"), 400
        try:
            quote = calculate_price(
                plan,
                quantity=quantity,
                monthly=bool(payload.get("monthly", True)),
            )
        except (KeyError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(quote)

    # ------------------------------------------------------------------ wallet

    @app.get("/api/wallet")
    def wallet():
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in."), 401
        user_id = user["id"]
        balance = credit_service.get_wallet(user_id)
        return jsonify(
            subscription_credits=balance.subscription_credits,
            purchased_credits=balance.purchased_credits,
            total=balance.total,
            mode_costs=MODE_COST,
            free_light_available=not credit_service.has_used_free_light(user_id),
            summary=credit_service.wallet_summary(user_id),
            subscription=_public_subscription(_subscription_for_user(user_id)),
            researches_completed=_researches_completed(user_id),
        )

    @app.get("/api/transactions")
    def transactions():
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in."), 401
        try:
            limit = max(1, min(int(request.args.get("limit", 20)), 100))
            offset = max(0, int(request.args.get("offset", 0)))
        except ValueError:
            limit, offset = 20, 0
        rows, total = credit_service.search_transactions(
            user["id"],
            query=request.args.get("q", ""),
            type=request.args.get("type", ""),
            status=request.args.get("status", ""),
            limit=limit,
            offset=offset,
        )
        return jsonify(
            transactions=[_public_transaction(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    @app.get("/api/payments")
    def payments():
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in."), 401
        return jsonify(payments=credit_service.payments(user["id"]))

    # ------------------------------------------------------------- research

    @app.post("/api/research")
    def start():
        prune()
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in to run research."), 401

        payload = request.get_json(silent=True) or {}
        mode = str(payload.get("mode") or "light").strip().lower()
        if mode not in RESEARCH_MODES:
            return jsonify(error=f"Unknown mode '{mode}'."), 400

        req = ResearchRequest(
            text=str(payload.get("text") or ""),
            keywords=str(payload.get("keywords") or ""),
            focus=str(payload.get("focus") or ""),
            engine=str(payload.get("engine") or "yahoo"),
            render=bool(payload.get("render", False)),
            no_ai=bool(payload.get("no_ai", False)),
            mode=mode,
        )
        if not req.text.strip():
            return jsonify(error="Paste a product URL."), 400

        user_id = user["id"]
        cost = MODE_COST[mode]
        job_id = uuid4().hex

        # FREE plan: one complimentary Light investigation per account.
        free_grant = False
        if mode == "light" and not credit_service.has_used_free_light(user_id):
            wallet_balance = credit_service.get_wallet(user_id)
            if wallet_balance.total < cost:
                if not credit_service.claim_free_light(user_id):
                    return jsonify(
                        error="Your complimentary investigation has already been used."
                    ), 403
                free_grant = True

        job = Job(req, user_id=user_id)
        job.id = job_id
        job.free_grant = free_grant

        if not free_grant:
            try:
                reservation = credit_service.reserve(user_id, job_id, mode)
                job.reserved = True
            except InsufficientCredits as exc:
                return jsonify(
                    error=str(exc),
                    required=exc.required,
                    available=exc.available,
                    mode=mode,
                ), 402

        with jobs_lock:
            jobs[job_id] = job
        _supabase_create_job(job_id, user_id, "queued", [], mode=mode, cost=cost)

        pool.submit(work, job)
        return (
            jsonify(
                id=job_id,
                mode=mode,
                cost=cost,
                free_grant=free_grant,
            ),
            202,
        )

    @app.get("/api/jobs/<job_id>")
    def poll(job_id: str):
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in."), 401

        with jobs_lock:
            job = jobs.get(job_id)

        # A job is private to the account that started it.
        if job is not None and job.user_id and job.user_id != user["id"]:
            return jsonify(error="That job expired or doesn't exist."), 404

        if job is not None:
            try:
                since = max(0, int(request.args.get("since", 0)))
            except ValueError:
                since = 0
            return jsonify(job.snapshot(since))

        job_data = _supabase_get_job(job_id)
        if job_data is not None and job_data.get("user_id") not in (None, user["id"]):
            job_data = None
        if job_data is not None:
            return jsonify(
                id=job_data["id"],
                status=job_data.get("status", "queued"),
                steps=job_data.get("progress", []),
                step_count=len(job_data.get("progress", []) or []),
                mode=job_data.get("mode", "light"),
                cost=job_data.get("cost", 1),
                title=job_data.get("title") or "",
                markdown=job_data.get("markdown") or "",
                html=job_data.get("html") or "",
                sources=job_data.get("sources") or [],
                models=job_data.get("models") or [],
                stage_timings=job_data.get("stage_timings") or {},
                error=job_data.get("error", ""),
            )

        return jsonify(error="That job expired or doesn't exist."), 404

    # --------------------------------------------------------------- checkout

    @app.post("/api/checkout/credits")
    def checkout_credits():
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in."), 401

        payload = request.get_json(silent=True) or {}
        try:
            quantity = int(payload.get("quantity"))
        except (TypeError, ValueError):
            return jsonify(error="Choose a credit quantity."), 400

        from verdict.wallet import calculate_price

        try:
            quote = calculate_price("pay_as_you_go", quantity=quantity)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

        # Record a pending payment so the webhook can be matched idempotently.
        payment_id = None
        if sb is not None:
            try:
                resp = (
                    sb.table("payments")
                    .insert(
                        {
                            "user_id": user["id"],
                            "kind": "credits",
                            "plan": "pay_as_you_go",
                            "credit_amount": quantity,
                            "amount_cents": quote["total_cents"],
                            "currency": "usd",
                            "status": "pending",
                            "provider": "stripe",
                        }
                    )
                    .execute()
                )
                payment_id = (resp.data or [{}])[0].get("id")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not record pending payment: %s", exc)

        try:
            checkout = payment_service.create_credit_checkout(
                user_id=user["id"],
                email=(user.get("email") or "") if isinstance(user, dict) else "",
                quantity=quantity,
                unit_price_cents=quote["unit_price_cents"],
                total_cents=quote["total_cents"],
            )
        except PaymentNotConfigured as exc:
            return jsonify(error=str(exc), quote=quote, payment_id=payment_id), 503

        if sb is not None and payment_id:
            try:
                sb.table("payments").update(
                    {"provider_session_id": checkout.session_id}
                ).eq("id", payment_id).execute()
            except Exception:  # noqa: BLE001
                pass

        return jsonify(url=checkout.url, session_id=checkout.session_id, quote=quote)

    @app.post("/api/checkout/subscription")
    def checkout_subscription():
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in."), 401

        payload = request.get_json(silent=True) or {}
        plan = str(payload.get("plan") or "").strip()
        # Accept either an explicit interval or the UI's `annual` boolean.
        if payload.get("interval"):
            interval = str(payload.get("interval")).strip()
        else:
            interval = "annual" if payload.get("annual") else "monthly"
        if plan not in ("research_pro", "business") or interval not in ("monthly", "annual"):
            return jsonify(error="Invalid plan or interval."), 400

        try:
            checkout = payment_service.create_subscription_checkout(
                user_id=user["id"],
                email=(user.get("email") or "") if isinstance(user, dict) else "",
                plan=plan,
                interval=interval,
            )
        except PaymentNotConfigured as exc:
            return jsonify(error=str(exc)), 503
        return jsonify(url=checkout.url, session_id=checkout.session_id)


    def _owned_subscription(user_id: str, response):
        row = _subscription_for_user(user_id)
        if not row:
            response["error"] = "You do not have a subscription to manage."
            return None
        if not row.get("stripe_subscription_id"):
            response["error"] = "This subscription is not linked to Stripe yet."
            return None
        return row

    @app.post("/api/subscription/portal")
    def subscription_portal():
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in."), 401
        error: dict = {}
        row = _owned_subscription(user["id"], error)
        if row is None:
            return jsonify(error), 400

        customer_id = row.get("stripe_customer_id")
        if not customer_id:
            try:
                state = payment_service.retrieve_subscription(row["stripe_subscription_id"])
                customer_id = state.get("customer")
                if customer_id and sb is not None:
                    sb.table("subscriptions").update(
                        {"stripe_customer_id": customer_id}
                    ).eq("id", row["id"]).execute()
            except PaymentNotConfigured as exc:
                return jsonify(error=str(exc)), 503
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not resolve Stripe customer: %s", exc)
        if not customer_id:
            return jsonify(
                error="Billing details are not ready yet. Please try again after your next invoice."
            ), 400

        try:
            portal = payment_service.create_billing_portal(
                customer_id, f"{payment_service.app_url}/wallet"
            )
        except PaymentNotConfigured as exc:
            return jsonify(error=str(exc)), 503
        return jsonify(url=portal.url)

    @app.post("/api/subscription/cancel")
    def subscription_cancel():
        user = _user_from_request()
        if user is None:
            return jsonify(error="Please log in."), 401
        error: dict = {}
        row = _owned_subscription(user["id"], error)
        if row is None:
            return jsonify(error), 400
        if row.get("status") in ("canceled", "expired", "incomplete_expired"):
            return jsonify(error="This subscription has already ended."), 400
        if row.get("cancel_at_period_end"):
            return jsonify(
                error="This subscription is already scheduled to cancel.",
                subscription=_public_subscription(row),
            ), 400

        try:
            state = payment_service.cancel_subscription(row["stripe_subscription_id"])
        except PaymentNotConfigured as exc:
            return jsonify(error=str(exc)), 503
        except Exception as exc:  # noqa: BLE001
            logger.warning("Stripe cancellation failed: %s", exc)
            return jsonify(error="Stripe could not cancel the subscription. Please try again."), 502

        _apply_stripe_subscription(state, user_id=user["id"])
        updated = _subscription_by_stripe_id(row["stripe_subscription_id"]) or row
        return jsonify(subscription=_public_subscription(updated))

    @app.post("/api/subscriptions/allocate")
    def allocate_credits():
        """Monthly allocation job for annual plans (and missed monthly invoices).

        Protected by VERDICT_CRON_SECRET. Credits are granted once per
        subscription and calendar month; the ledger reference is the idempotency
        key, so duplicate runs never allocate twice.
        """
        supplied = request.headers.get("X-Cron-Secret", "").strip()
        if not CRON_SECRET or not secrets.compare_digest(supplied, CRON_SECRET):
            return jsonify(error="Unauthorized"), 401
        if sb is None:
            return jsonify(allocated=0, skipped=0)

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        now = datetime.now(timezone.utc)
        try:
            rows = (
                sb.table("subscriptions")
                .select("*")
                .in_("status", ["active", "trialing"])
                .execute()
                .data
                or []
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Credit allocation could not list subscriptions: %s", exc)
            return jsonify(error="Could not read subscriptions"), 502

        allocated, skipped = 0, 0
        for row in rows:
            if row.get("last_credit_month") == month:
                skipped += 1
                continue
            start, end = row.get("current_period_start"), row.get("current_period_end")
            if start and str(start) > now.isoformat():
                skipped += 1
                continue
            if end and str(end)[:10] < now.date().isoformat():
                skipped += 1
                continue
            reference = f"monthly:{row.get('id')}:{month}"
            if _grant_subscription(
                row["user_id"],
                row.get("plan"),
                reference,
                subscription_id=row.get("stripe_subscription_id"),
                description=f"Monthly credits for {month}",
            ):
                allocated += 1
            else:
                skipped += 1
        return jsonify(allocated=allocated, skipped=skipped, month=month)

    # --------------------------------------------------------------- webhooks

    @app.post("/api/webhooks/stripe")
    def stripe_webhook():
        payload = request.get_data()
        signature = request.headers.get("Stripe-Signature", "")
        event = payment_service.verify_webhook(payload, signature)
        if event is None:
            return jsonify(error="Invalid signature"), 400

        event_type = event.get("type", "")
        data = (event.get("data") or {}).get("object") or {}
        metadata = data.get("metadata") or {}
        event_id = event.get("id") or ""

        try:
            claimed = _claim_webhook_event(event_id, event_type)
        except Exception:  # noqa: BLE001
            return jsonify(error="Could not record webhook event"), 500
        if not claimed:
            return jsonify(ok=True)

        try:
            if event_type == "checkout.session.completed":
                user_id = metadata.get("user_id") or data.get("client_reference_id")
                kind = metadata.get("kind")
                session_id = data.get("id")

                if not user_id:
                    logger.warning("Webhook missing user_id: %s", event_type)
                    return jsonify(ok=True)

                if kind == "credits":
                    quantity = int(metadata.get("quantity") or 0)
                    if quantity <= 0:
                        return jsonify(ok=True)
                    amount_cents = int(metadata.get("total_cents") or 0) or None
                    credit_service.grant_credits(
                        user_id,
                        quantity,
                        kind="purchased",
                        type="purchase",
                        reference=session_id,
                        amount_cents=amount_cents,
                        description=f"{quantity} research credits purchased",
                    )
                    if sb is not None:
                        try:
                            sb.table("payments").update(
                                {"status": "succeeded"}
                            ).eq("provider_session_id", session_id).execute()
                        except Exception:  # noqa: BLE001
                            pass

                elif kind == "subscription":
                    plan = metadata.get("plan")
                    interval = metadata.get("interval")
                    subscription_id = data.get("subscription")
                    credit_service.grant_credits(
                        user_id,
                        _allowance_for(plan),
                        kind="subscription",
                        type="subscription_grant",
                        reference=session_id,
                        reset=True,
                        amount_cents=int(metadata.get("total_cents") or 0) or None,
                        description=f"First month of {plan or 'subscription'} credits",
                    )
                    if sb is not None and subscription_id:
                        existing = _subscription_by_stripe_id(subscription_id)
                        record = {
                            "user_id": user_id,
                            "plan": plan,
                            "billing_interval": interval,
                            "status": "active",
                            "credits_per_period": _allowance_for(plan),
                            "stripe_subscription_id": subscription_id,
                            "stripe_customer_id": data.get("customer") or None,
                            "last_invoice_id": data.get("invoice") or None,
                            "last_credit_month": datetime.now(timezone.utc).strftime("%Y-%m"),
                        }
                        try:
                            if existing:
                                sb.table("subscriptions").update(record).eq(
                                    "id", existing["id"]
                                ).execute()
                            else:
                                sb.table("subscriptions").insert(record).execute()
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Could not store subscription: %s", exc)
                        try:
                            state = payment_service.retrieve_subscription(subscription_id)
                            _apply_stripe_subscription(state, user_id=user_id)
                        except Exception as exc:  # noqa: BLE001
                            logger.warning("Could not refresh subscription state: %s", exc)

            elif event_type == "invoice.paid":
                sub_details = data.get("subscription_details") or {}
                inv_meta = sub_details.get("metadata") or metadata or {}
                user_id = inv_meta.get("user_id")
                plan = inv_meta.get("plan")
                invoice_id = data.get("id")
                subscription_id = data.get("subscription") or sub_details.get("subscription")

                row = _subscription_by_stripe_id(subscription_id or "")
                if row:
                    user_id = user_id or row.get("user_id")
                    plan = plan or row.get("plan")
                    if invoice_id and row.get("last_invoice_id") == invoice_id:
                        return jsonify(ok=True)
                    month = datetime.now(timezone.utc).strftime("%Y-%m")
                    if row.get("last_credit_month") == month:
                        if sb is not None and invoice_id:
                            sb.table("subscriptions").update(
                                {"last_invoice_id": invoice_id}
                            ).eq("id", row["id"]).execute()
                        return jsonify(ok=True)

                if not user_id:
                    logger.warning("Invoice without a user: %s", invoice_id)
                    return jsonify(ok=True)

                amount_cents = data.get("amount_paid")
                _grant_subscription(
                    user_id,
                    plan,
                    invoice_id or event_id,
                    amount_cents=int(amount_cents) if amount_cents is not None else None,
                    subscription_id=subscription_id,
                )
                if sb is not None and subscription_id:
                    try:
                        sb.table("subscriptions").update(
                            {
                                "status": "active",
                                "last_invoice_id": invoice_id,
                                "current_period_start": _iso(data.get("period_start")),
                                "current_period_end": _iso(data.get("period_end")),
                            }
                        ).eq("stripe_subscription_id", subscription_id).execute()
                    except Exception:  # noqa: BLE001
                        pass

            elif event_type == "invoice.payment_failed":
                sub_details = data.get("subscription_details") or {}
                subscription_id = data.get("subscription") or sub_details.get("subscription")
                row = _subscription_by_stripe_id(subscription_id or "")
                user_id = metadata.get("user_id") or (row or {}).get("user_id")
                if sb is not None:
                    try:
                        query = sb.table("subscriptions").update({"status": "past_due"})
                        if subscription_id:
                            query = query.eq("stripe_subscription_id", subscription_id)
                        elif user_id:
                            query = query.eq("user_id", user_id)
                        else:
                            query = None
                        if query is not None:
                            query.execute()
                    except Exception:  # noqa: BLE001
                        pass

            elif event_type == "customer.subscription.updated":
                subscription_id = data.get("id")
                row = _subscription_by_stripe_id(subscription_id or "")
                user_id = metadata.get("user_id") or (row or {}).get("user_id")
                state = payment_service.subscription_state(data)
                _apply_stripe_subscription(state, user_id=user_id)
                if state.get("status") in ("canceled", "expired", "incomplete_expired"):
                    if user_id:
                        credit_service.clear_subscription_credits(
                            user_id, reference=f"cancel:{subscription_id}"
                        )

            elif event_type == "customer.subscription.deleted":
                subscription_id = data.get("id")
                row = _subscription_by_stripe_id(subscription_id or "")
                user_id = metadata.get("user_id") or (row or {}).get("user_id")
                if sb is not None:
                    try:
                        query = sb.table("subscriptions").update(
                            {
                                "status": "canceled",
                                "canceled_at": _iso(data.get("canceled_at"))
                                or datetime.now(timezone.utc).isoformat(),
                                "cancel_at_period_end": False,
                            }
                        )
                        if subscription_id:
                            query = query.eq("stripe_subscription_id", subscription_id)
                        elif user_id:
                            query = query.eq("user_id", user_id)
                        else:
                            query = None
                        if query is not None:
                            query.execute()
                    except Exception:  # noqa: BLE001
                        pass
                if user_id:
                    credit_service.clear_subscription_credits(
                        user_id, reference=f"deleted:{subscription_id or event_id}"
                    )

        except Exception:  # noqa: BLE001
            logger.exception("Webhook handling failed for %s", event_type)
            # Return 200 so Stripe does not retry a handler bug forever; the
            # payment row remains pending and can be reconciled.

        return jsonify(ok=True)

    return app


app = create_app()

if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "5000"))
    app.run(host=host, port=port, debug=os.getenv("FLASK_DEBUG") == "1", threaded=True)
