# Verdict — SaaS monetization & research engine: implementation report

Scope: turning the existing Verdict research tool into a paid product with a
credit wallet, subscriptions, three research modes, and evidence-graded reports.
The stack is unchanged: Next.js 15 on Vercel, Flask on Render, Supabase for auth
and data, Serper + Oxylabs for search and scraping, Gemini / NVIDIA / OpenRouter
for writing.

---

## 1. Architecture

```
browser ──► Next.js (Vercel) ──► Flask research engine (Render) ──► Serper / Oxylabs
              │  auth relay                       │                    └► LLM providers
              │  server-side pricing              └── Supabase (service role): wallets,
              └  Stripe webhook                     subscriptions, ledger, reservations
```

* **All money and credit state lives server-side.** The Next.js layer verifies the
  Supabase session and relays the request; it never computes a price or a balance
  the backend then trusts. `lib/research.ts` forwards the caller's bearer token and
  a signed user id, and the Flask layer re-verifies it (§8).
* **The Flask service owns the pipeline.** Job creation, credit reservation, mode
  configuration, scoring, validation and refunds all happen in `backend/verdict/`.
  The browser polls `GET /api/research/jobs/<id>` (relayed to `GET /api/jobs/<id>`).
* **Supabase is used with the service-role key from the backend only.** The browser
  never sees it; RLS policies allow users to read only their own wallet, ledger and
  subscription rows.
* **Stripe is behind `backend/verdict/payments.py`.** Nothing outside that module
  imports the Stripe SDK, so the rest of the app runs whether or not keys exist.

## 2. Files

Backend (`backend/`):

| File | Role |
|---|---|
| `verdict/config.py` | `Settings.PRICING` — the single source of truth for prices, credit allowances and mode costs |
| `verdict/wallet.py` | Pure functions: `calculate_price()`, tier selection, credit arithmetic |
| `verdict/credits.py` | `CreditService` — wallet reads/writes, reservations, finalize, refunds, ledger, free-Light grant |
| `verdict/payments.py` | Stripe wrapper: checkout sessions, webhook verification, `config_status()` |
| `verdict/pipeline.py` | Mode config, parallel search and scraping, stage timings, metrics, pre-delivery validation, scrape cache |
| `verdict/evidence.py` | Source classification (8 kinds), product identity checks, claim statuses, limitation detection |
| `verdict/scoring.py` | Authoritative category weights, structured JSON parsing, code-computed totals, band labels |
| `verdict/verdict_prompt.py` | 12-section report prompt with the three-score rubric and structured JSON score output |
| `verdict/models.py` | Wallet / subscription / reservation / mechanism models |
| `web.py` | The HTTP surface (§3) and background job runner |
| `database/migrations/20261120_saas_monetization.sql` | All new tables, columns, indexes and RLS policies |

Frontend:

| File | Role |
|---|---|
| `app/pricing/page.tsx` | Four plans, monthly/annual toggle, credit calculator, current-plan and credit indicators, purchase history |
| `components/Research.tsx` | Start screen with mode picker, per-mode cost, live balances, insufficient-credit blocking, 402 handling |
| `lib/research.ts` | Session verification + authenticated relay to the Flask service |
| `app/api/pricing/route.ts`, `app/api/pricing/quote/route.ts` | Pricing read + server-side quote |
| `app/api/wallet/route.ts`, `app/api/transactions/route.ts` | Balances and ledger |
| `app/api/checkout/credits/route.ts`, `app/api/checkout/subscription/route.ts` | Checkout session creation |
| `app/api/webhooks/stripe/route.ts` | Raw-body webhook pass-through |
| `app/globals.css` | Pricing and mode-selection styles in the existing visual language |

## 3. HTTP surface (Flask)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/status` | Whether search + LLM keys are configured (no secrets returned) |
| GET | `/api/pricing` | Plans, tiers, mode costs — read from `Settings.PRICING` |
| POST | `/api/pricing/quote` | Server-computed total for a plan/quantity; rejects client-supplied prices |
| GET | `/api/wallet` | `subscription_credits`, `purchased_credits`, `total`, `mode_costs`, `free_light_available` |
| GET | `/api/transactions` | The caller's ledger |
| GET | `/api/payments` | The caller's payment records |
| POST | `/api/research` | Reserves credits, starts the job; `402` when short, `409` on duplicate idempotency key |
| GET | `/api/jobs/<id>` | Progress + report; scoped to the owning user |
| POST | `/api/checkout/credits` | Stripe checkout for a credit pack (`503` if unconfigured) |
| POST | `/api/checkout/subscription` | Stripe checkout for Pro / Business |
| POST | `/api/webhooks/stripe` | Signature-verified; grants credits, activates subscriptions |

## 4. Migration

`backend/database/migrations/20261120_saas_monetization.sql` creates:

* `wallets` (subscription + purchased buckets, one row per user),
* `credit_transactions` (the immutable ledger),
* `credit_reservations` (per-bucket amounts, balances at reservation, status),
* `subscriptions` (plan, interval, status, period end, `last_invoice_id`),
* `payments`,
* adds `research_jobs.mode / cost / stage_timings / metrics`,
* and installs three atomic credit functions: `verdict_reserve_credits`,
  `verdict_finalize_credits`, `verdict_refund_credits` (§5).

RLS is enabled with select-own policies on the user-facing tables; writes go
through the service role.

**Status: not applied to the live project yet.** Apply with the Supabase SQL
editor or `supabase db push`; the file is idempotent (`create table if not exists`,
`add column if not exists`).

## 5. Credit wallet

Two independent buckets per user:

* **Subscription credits** — topped up to the plan allowance at each period start,
  reset (not added) on renewal, so there is no rollover.
* **Purchased credits** — never expire, are not touched by a reset, and survive
  cancellation.

Order of consumption is fixed: subscription first, then purchased. Deduction is
**reservation-based**:

1. `POST /api/research` calls `CreditService.reserve(user, job_id, mode)`. In
   production this is one Postgres call — `verdict_reserve_credits(user,
   investigation, mode, cost)` — which locks the wallet row (`FOR UPDATE`), returns
   the existing reservation if this investigation was already reserved, refuses
   with `insufficient` when the total is short, and otherwise deducts the cost
   (subscription first), inserts the reservation with the per-bucket split and the
   balances, and writes the ledger row, all in one transaction. There is no
   read-modify-write window in application code, so two concurrent investigations
   cannot overdraw a wallet.
2. On delivery, `finalize()` calls `verdict_finalize_credits`, which flips the
   reservation from `held` to `finalized` only if it is still held. No further
   arithmetic happens, so a retried finalize cannot double-charge.
3. On failure — crash, timeout, pipeline error, or validation that leaves nothing
   usable — `verdict_refund_credits` locks the reservation, refuses unless it is
   still `held`, restores **exactly the buckets that were consumed**, marks it
   `released`, records the refund (unique per investigation) and writes the ledger
   row. A replay is a no-op.
4. A failed **free** Light run also restores `free_light_used`, so a user does not
   lose their one complimentary run to an outage.
5. If the migration has not been applied yet, `CreditService` logs a warning and
   falls back to the older table-level code path instead of crashing — so a
   half-deployed database still serves requests, just without the atomic
   guarantee.

Every movement writes a ledger row: `type`, `amount`, `mode`, `investigation_id`,
`payment_reference`, `status`, `balance_before`, `balance_after`, `created_at`.
Because it stores balances before and after, the ledger can be replayed to audit
any wallet.

Free tier: exactly one Light investigation per account, enforced server-side by
`claim_free_light()`, which is idempotent per user (`_granted_refs` in memory, a
unique reference in Postgres). It is only offered when the wallet total is below
the Light cost, so it cannot be farmed alongside a paid balance.

## 6. Subscriptions

* **Research Pro** — $14.99/month or $149.99/year, 50 credits per month.
* **Business** — $29.99/month or $299.99/year, 150 credits per month.

Annual plans are billed yearly but **grant credits monthly**; there is no upfront
annual dump. Checkout passes `metadata` (user id, plan, interval) onto both the
session and `subscription_data`, so the invoice events that arrive later still know
who to credit.

The webhook handles `checkout.session.completed`,
`customer.subscription.created/updated/deleted` and `invoice.paid`. Idempotency
uses `subscriptions.last_invoice_id`: an invoice that has already been credited is
ignored, so Stripe's at-least-once retries cannot grant twice. A cancellation
marks the subscription `canceled` and leaves purchased credits untouched.

## 7. Pay-as-you-go

| Credits | Price | Per credit |
|---|---|---|
| 5 | $5.00 | $1.00 |
| 10 | $8.50 | $0.85 |
| 25 | $17.50 | $0.70 |
| 50 | $30.00 | $0.60 |
| 100 | $50.00 | $0.50 |

One-time purchase, minimum 5. The backend re-derives the amount from
`Settings.PRICING` and, in production, compares it against the Stripe price object
before creating the session, so a tampered request cannot buy 100 credits for $5.
Credits never expire and failed runs are refunded (see §5).

## 8. Payment provider status

Stripe is integrated but **not live in this environment** — no secret key, no
webhook secret, and no price IDs are configured. `PaymentService.config_status()`
reports exactly which are missing, and both checkout routes return `503` with a
human-readable message instead of pretending to work.

Required to go live (all listed in `.env.example`):

| Variable | Where |
|---|---|
| `STRIPE_SECRET_KEY` | Flask (Render) |
| `STRIPE_WEBHOOK_SECRET` | Flask (Render) — from the webhook endpoint you create |
| `STRIPE_PRICE_PRO_MONTHLY`, `STRIPE_PRICE_PRO_ANNUAL` | Flask (Render) |
| `STRIPE_PRICE_BIZ_MONTHLY`, `STRIPE_PRICE_BIZ_ANNUAL` | Flask (Render) |
| `APP_URL` | Flask (Render) — success/cancel URLs |
| `VERDICT_RELAY_SECRET` | **both** Vercel and Render, same value (strongly recommended; calls also work through the forwarded bearer token) |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Flask (Render) |
| `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `RESEARCH_API_URL` | Vercel |

Webhook endpoint to register: `https://<render-service>/api/webhooks/stripe`
(the Next.js route forwards the raw body untouched, which signature verification
requires).

## 9. Research modes

| Mode | Credits | Budget | Search queries | Sources read |
|---|---|---|---|---|
| Light | 1 | < 5 min | 3 | 4 |
| Medium | 2 | < 10 min | 4 | 6 |
| Deep | 3 | < 15 min | 5 | 8 |

Query count is a *depth* setting, not a cap on evidence: the source count is
configured separately (and can exceed the query count), and results are merged and
deduplicated across queries before scraping. Each mode carries a deadline that is
checked between stages; work already gathered is written up rather than discarded
when the budget runs out.

## 10. Performance

Measured in this repo with a fake client (no network), so the numbers isolate
orchestration rather than provider latency:

| Change | Measured |
|---|---|
| Parallel search vs sequential (5 queries × 0.2 s) | **0.21 s vs 1.00 s** (≈4.8×) |
| Concurrent scraping (4 workers) | Sources are fetched in parallel; wall clock is bounded by the slowest page, not the sum |
| Duplicate URL removal across queries | Repeated results are dropped before scraping |
| Scrape cache (30 min TTL, 250 entries) | A second investigation of the same product re-uses pages instead of re-scraping |

Reproduce the search number:

```bash
cd backend && python3 -m pytest tests/test_pipeline.py -q -k parallel
```

**Not measured:** real end-to-end completion time per mode. That needs live
Serper/Oxylabs/LLM keys, which are not present here, so the < 5 / < 10 / < 15
minute targets are *design budgets with enforced deadlines*, not verified results.
`stage_timings` and `metrics` are recorded on every job precisely so the first real
runs can be compared against the budgets.

## 11. Output quality

* Three **independent** scores, 0–100: Product Credibility, Evidence Strength,
  Purchasing Confidence. The model returns one integer per category in a JSON
  block; `scoring.py` clamps each category to its maximum and computes the totals
  in code. Weights: Product Credibility 20/15/20/15/10/5/10/5, Evidence Strength
  25/20/15/15/10/10/5, Purchasing Confidence 35/25/15/15/10. Missing reviews lower
  Evidence Strength and Purchasing Confidence, never Product Credibility.
* Manufacturer material is labelled `MANUFACTURER CLAIM` and is never counted as
  independent proof.
* Eight source classifications; unknown domains are labelled "Unverified content"
  rather than being credited as documentation (this was a real bug: a catch-all
  branch mislabelled arbitrary domains as manufacturer docs).
* Claim statuses: `VERIFIED`, `MANUFACTURER CLAIM`, `UNVERIFIED`, `CONTRADICTED`.
* Product identity is checked before scoring, so a same-named but different product
  does not contribute evidence.
* 12-section report template; a pre-delivery validation pass checks that the
  sections and all four score labels exist and that the evidence basis is disclosed.
  When validation fails the report is still delivered, with a "Validation notes"
  block listing what was thin — the user paid for the investigation, so it is
  better to ship it with an honest caveat than to fail it. Genuine pipeline
  failures are refunded.
* Thin evidence is disclosed in an "Evidence basis" block (counts per
  classification) and in the limitations section, using broadened phrase matching
  so "limited independent coverage" and "limited testing" are both recognised.

## 12. Security

* Prices, credit costs and totals are computed server-side only. The quote endpoint
  recomputes from `Settings.PRICING`; client-supplied prices are ignored.
* Stripe webhooks are signature-verified against the raw body; the Next.js route
  passes bytes through unmodified. Unverified events are rejected.
* Webhook side effects are idempotent (`last_invoice_id`, reservation status,
  free-grant reference), so replays grant nothing twice.
* Job polling is ownership-scoped: a job id from another account returns `404`, not
  someone else's report.
* Credit operations are serialised per user; refunds restore the exact buckets and
  cannot run twice.
* **Relay hardening (this change):** the backend now verifies the caller's bearer
  token with Supabase when Supabase is configured. The forwarded `X-User-Id` header
  is trusted only when `VERDICT_RELAY_SECRET` is set on both services and matches
  (constant-time compare via `secrets.compare_digest`). Previously the header was
  trusted outright, which let anyone who could reach the Render URL act as any user
  — including spending their credits. Covered by
  `test_forwarded_user_requires_relay_secret`.

## 13. Tests and results

```
cd backend && python3 -m pytest -q     →  154 passed
npx tsc --noEmit                       →  clean
npx next build                         →  success (routes /pricing, /api/wallet,
                                           /api/transactions, /api/checkout/*,
                                           /api/webhooks/stripe all present)
```

Coverage highlights: pricing arithmetic and tier boundaries, server-side quote
rejection, subscription-first consumption, no-rollover reset, purchased credits
surviving cancellation, reservation idempotency, refund-exactly-once with bucket
restoration, free-Light single use and restoration after failure, ledger balance
chain, webhook signature rejection, invoice idempotency, job ownership, relay
secret gating, parallel-search timing, scrape-cache hit/miss, mode validation and
clamping, source classification, limitation detection, the rubric totals and
  band enforcement, and the atomic-RPC path (insufficient mapping, bucket
  pass-through, no-op refund, and fail-closed behavior when a function is missing).

## 14. Not verified (and why)

These are **not** claims of success — each needs credentials or a live environment:

1. **Real research runs.** No `SERPER_API_KEY`, `OXYLABS_API_KEY`, `GEMINI_API_KEY`,
   `NVIDIA_API_KEY` or `OPENROUTER_API_KEY` in this environment. No end-to-end
   report was generated, so mode completion times, token costs and report quality on
   real products are unmeasured.
2. **Payments.** No Stripe keys, so no checkout session, no webhook delivery and no
   credit grant has been exercised against Stripe. The logic is unit-tested with
   fakes; the round trip is not.
3. **Database.** The migration has not been applied to the live Supabase project,
   and no Postgres instance was available here, so the SQL (including the three
   `verdict_*` functions) has not been parsed or executed by Postgres. Tests use
   the in-memory `CreditService` fallback plus a fake client for the RPC calls;
   row-lock behaviour under real concurrency is untested. Apply the migration to a
   Supabase branch first and run the two concurrent-investigation check in §15.
4. **Browsewise scanner.** Untouched — no files in that path were modified.
5. **Platform performance.** The numbers in §10 are orchestration measurements, not
   production latency.

## 15. Remaining deployment steps

1. Apply `backend/database/migrations/20261120_saas_monetization.sql` to Supabase.
2. Set `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and `VERDICT_RELAY_SECRET` on
   Render; set `VERDICT_RELAY_SECRET` (same value), `RESEARCH_API_URL` and the
   Supabase public keys on Vercel.
3. Create the four Stripe prices (Pro monthly/annual, Business monthly/annual) and
   set the IDs plus `STRIPE_SECRET_KEY`, `APP_URL` on Render.
4. Register the webhook at `<render-url>/api/webhooks/stripe` for the checkout,
   subscription and `invoice.paid` events; set `STRIPE_WEBHOOK_SECRET`.
5. Verify atomicity after migrating: give a test user 1 credit and fire two
   concurrent Light requests; exactly one must succeed and the wallet must not go
   negative.
6. Run one real Light investigation per account type and compare `stage_timings`
   against the 5/10/15-minute budgets; run one Stripe test-mode purchase and one
   subscription renewal (with a test clock) to confirm grants and no double-credit.
7. Verify a cancellation keeps purchased credits and clears the subscription
   bucket at period end.
