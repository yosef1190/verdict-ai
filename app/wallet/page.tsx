"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import Logo from "@/components/Logo";
import { authFetch } from "@/lib/auth-fetch";

type ModeCosts = { light: number; medium: number; deep: number };
type Summary = {
  purchased_total: number;
  subscription_total: number;
  free_total: number;
  consumed: number;
  refunded: number;
};
type Subscription = {
  id: string;
  plan: "research_pro" | "business" | string;
  plan_label: string;
  billing_interval: "monthly" | "annual";
  status: string;
  display_status: string;
  cancel_at_period_end: boolean;
  credits_per_period: number;
  price_cents: number | null;
  current_period_start: string | null;
  current_period_end: string | null;
  access_ends_at: string | null;
  days_remaining: number | null;
  canceled_at: string | null;
  started_at: string | null;
  last_credit_month: string | null;
  has_stripe_subscription: boolean;
  renews: boolean;
};
type WalletData = {
  subscription_credits: number;
  purchased_credits: number;
  total: number;
  mode_costs: ModeCosts;
  free_light_available: boolean;
  summary: Summary;
  subscription: Subscription | null;
  researches_completed: number;
};
type Tier = { quantity: number; unit_price: number; total: number };
type Quote = {
  quantity: number;
  unit_price: number;
  total_cents: number;
  description: string;
};
type Pricing = {
  pay_as_you_go: { min_purchase: number; tiers: Tier[] };
  research_pro: {
    monthly_cost: number;
    annual_cost: number;
    monthly_credits: number;
    annual_credits_per_month: number;
  };
  business: {
    monthly_cost: number;
    annual_cost: number;
    monthly_credits: number;
    annual_credits_per_month: number;
  };
  mode_costs: ModeCosts;
};
type Tx = {
  id: string;
  type: string;
  category: string;
  description: string;
  credits: number;
  amount_cents: number | null;
  currency: string;
  status: string;
  reference: string | null;
  investigation_id: string | null;
  balance_after: number | null;
  created_at: string;
};
type TxPage = { transactions: Tx[]; total: number; limit: number; offset: number };

const PAGE_SIZE = 10;
const TYPES = [
  ["credit_purchase", "Credit purchases"],
  ["subscription_renewal", "Subscription credits"],
  ["research_consumption", "Research usage"],
  ["refund", "Refunds"],
  ["free_grant", "Complimentary credits"],
  ["adjustment", "Adjustments"],
] as const;
const STATUSES = ["completed", "pending", "failed", "reversed"] as const;

async function api(path: string, init: RequestInit = {}) {
  const { res, body, error } = await authFetch(path, init);
  if (error) {
    throw new Error(body?.error || "Please log in to continue.");
  }
  return body;
}

const money = (cents: number | null | undefined, currency = "usd") =>
  cents == null
    ? "—"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: currency.toUpperCase(),
      }).format(cents / 100);
const date = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" })
    : "—";
const statusClass = (status: string) => {
  if (["active", "completed", "succeeded"].includes(status)) return "wl-status";
  if (["canceled", "cancelled", "past_due", "failed", "unpaid", "expired"].includes(status)) {
    return "wl-status bad";
  }
  return "wl-status warn";
};

function Skeleton() {
  return (
    <div className="wl-overview" aria-busy="true" aria-label="Loading wallet">
      <div className="wl-skeleton" />
      <div className="wl-skeleton" />
      <div className="wl-skeleton" />
    </div>
  );
}

export default function Wallet() {
  const { user, loading, signOut } = useAuth();
  const router = useRouter();

  const [wallet, setWallet] = useState<WalletData | null>(null);
  const [pricing, setPricing] = useState<Pricing | null>(null);
  const [txs, setTxs] = useState<TxPage | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [searchText, setSearchText] = useState("");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [qty, setQty] = useState(10);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [billingInterval, setBillingInterval] = useState<"monthly" | "annual">("monthly");
  const [confirmCancel, setConfirmCancel] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login?next=/wallet");
  }, [loading, user, router]);

  useEffect(() => {
    if (loading || !user) return;
    let alive = true;
    setError("");
    void (async () => {
      try {
        const [wRes, pRes] = await Promise.all([api("/api/wallet"), api("/api/pricing")]);
        if (!alive) return;
        setWallet(wRes);
        setPricing(pRes);
      } catch (err: any) {
        if (alive) setError(err.message);
      }
    })();
    return () => {
      alive = false;
    };
  }, [loading, user, refreshKey]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(searchText);
      setPage(1);
    }, 250);
    return () => clearTimeout(timer);
  }, [searchText]);

  useEffect(() => {
    if (loading || !user) return;
    let alive = true;
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String((page - 1) * PAGE_SIZE),
    });
    if (query) params.set("q", query);
    if (typeFilter) params.set("type", typeFilter);
    if (statusFilter) params.set("status", statusFilter);
    api(`/api/transactions?${params}`)
      .then((body: TxPage) => alive && setTxs(body))
      .catch((err: Error) => alive && setError(err.message));
    return () => {
      alive = false;
    };
  }, [loading, user, page, query, typeFilter, statusFilter, refreshKey]);

  useEffect(() => {
    if (!pricing) return;
    let alive = true;
    const quantity = Math.max(pricing.pay_as_you_go.min_purchase, qty);
    const timer = setTimeout(() => {
      api("/api/pricing/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan: "pay_as_you_go", quantity }),
      })
        .then((body: Quote) => alive && setQuote(body))
        .catch((err: Error) => alive && setError(err.message));
    }, 150);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [pricing, qty]);

  useEffect(() => {
    if (wallet?.subscription) setBillingInterval(wallet.subscription.billing_interval);
  }, [wallet?.subscription?.billing_interval]);

  async function buyCredits(quantity: number) {
    setBusy("credits");
    setError("");
    try {
      const body = await api("/api/checkout/credits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ quantity }),
      });
      if (body.url) window.location.href = body.url;
      else throw new Error(body.error || "Checkout did not return a URL.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function startPlan(plan: "research_pro" | "business", interval: "monthly" | "annual") {
    setBusy(`${plan}:${interval}`);
    setError("");
    try {
      const body = await api("/api/checkout/subscription", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan, interval }),
      });
      if (body.url) window.location.href = body.url;
      else throw new Error(body.error || "Checkout did not return a URL.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function openPortal() {
    setBusy("portal");
    setError("");
    try {
      const body = await api("/api/subscription/portal", { method: "POST" });
      if (body.url) window.location.href = body.url;
      else throw new Error(body.error || "The billing portal is unavailable.");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  async function cancelSubscription() {
    setBusy("cancel");
    setError("");
    try {
      await api("/api/subscription/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ at_period_end: true }),
      });
      setConfirmCancel(false);
      setRefreshKey((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy("");
    }
  }

  if (loading || !user) return <main className="wrap wl-main"><Skeleton /></main>;

  const sub = wallet?.subscription ?? null;
  const summary = wallet?.summary;
  const granted =
    (summary?.purchased_total ?? 0) + (summary?.subscription_total ?? 0) + (summary?.free_total ?? 0);
  const used = Math.max(0, (summary?.consumed ?? 0) - (summary?.refunded ?? 0));
  const remainingPct = granted > 0 ? Math.min(100, ((wallet?.total ?? 0) / granted) * 100) : 0;
  const usedPct = granted > 0 ? Math.min(100 - remainingPct, (used / granted) * 100) : 0;
  const tiers = pricing?.pay_as_you_go?.tiers ?? [];
  const maxUnit = tiers.length ? Math.max(...tiers.map((t) => t.unit_price)) : 1;
  const discount = quote ? Math.max(0, Math.round((1 - quote.unit_price / maxUnit) * 100)) : 0;
  const minCredits = pricing?.pay_as_you_go?.min_purchase ?? 5;
  const currentTier = sub
    ? sub.plan
    : (wallet?.purchased_credits ?? 0) > 0 || (summary?.purchased_total ?? 0) > 0
      ? "pay_as_you_go"
      : "free";
  const txTotal = txs?.total ?? 0;
  const pages = Math.max(1, Math.ceil(txTotal / PAGE_SIZE));

  return (
    <>
      <header className="nav">
        <div className="wrap nav-in">
          <Logo />
          <div className="auth">
            <a className="btn ghost sm" href="/dashboard">Dashboard</a>
            <a className="btn ghost sm" href="/pricing">Pricing</a>
            <button className="btn ghost sm" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </header>

      <main className="wrap wl-main">
        <div className="wl-head">
          <div>
            <p className="label mono"><b>Billing</b><i />Wallet</p>
            <h1 className="serif">Your credits, <em>your way.</em></h1>
            <p className="lede">Manage your research credits, subscription and billing history.</p>
          </div>
          <button className="btn dark" onClick={() => buyCredits(Math.max(minCredits, qty))} disabled={busy === "credits"}>
            {busy === "credits" ? "Opening…" : "Buy credits"}
          </button>
        </div>

        {error && (
          <div className="rs-banner err" role="alert">
            {error}{" "}
            <button className="link-btn" onClick={() => setRefreshKey((n) => n + 1)}>Try again</button>
          </div>
        )}

        {!wallet ? (
          <Skeleton />
        ) : (
          <>
            <section className="wl-overview" aria-label="Wallet overview">
              <div className="wl-hero">
                <span className="kicker mono">Available balance</span>
                <span className="figure">
                  {wallet.total}<small>credits</small>
                </span>
                <div className="wl-track" role="img" aria-label={`${used} credits used, ${wallet.total} credits remaining`}>
                  <i className="sub" style={{ width: `${remainingPct}%` }} />
                  <i className="pur" style={{ width: `${usedPct}%` }} />
                </div>
                <span className="hint mono">
                  {granted > 0 ? `${used} used of ${granted} granted` : "No credits granted yet"}
                </span>
              </div>
              <div className="wl-metric">
                <span className="kicker mono">Current subscription</span>
                <span className="value sm">{sub ? sub.plan_label : "Free"}</span>
                {sub ? (
                  <span className={statusClass(sub.display_status)}>{sub.display_status}</span>
                ) : (
                  <span className="wl-status neutral">No subscription</span>
                )}
                <span className="foot">
                  {sub
                    ? `${sub.credits_per_period} credits each billing month`
                    : "Buy credits or choose a plan below"}
                </span>
              </div>
              <div className="wl-metric">
                <span className="kicker mono">
                  {sub?.cancel_at_period_end ? "Access ends in" : "Days until renewal"}
                </span>
                <span className="value serif">{sub?.days_remaining ?? "—"}</span>
                <span className="foot">{sub ? date(sub.access_ends_at ?? sub.current_period_end) : "No renewal scheduled"}</span>
              </div>
            </section>

            <div className="wl-grid">
              <section className="wl-card" aria-labelledby="credits-heading">
                <div className="wl-card-head">
                  <div>
                    <h2 id="credits-heading">Credit breakdown</h2>
                    <p className="intro">Where your available credits come from.</p>
                  </div>
                  <span className="pill">
                    <i />{wallet.free_light_available ? "Free Light available" : "Free Light used"}
                  </span>
                </div>
                <div className="wl-split"><span>Subscription credits</span><b>{wallet.subscription_credits}</b></div>
                <div className="wl-split"><span>Pay-as-you-go credits</span><b>{wallet.purchased_credits}</b></div>
                <div className="wl-split"><span>Credits used</span><b>{used}</b></div>
                <div className="wl-split total"><span>Available total</span><b>{wallet.total}</b></div>
                <p className="muted" style={{ fontSize: 12, marginTop: 14, marginBottom: 0 }}>
                  Lifetime: {summary?.purchased_total ?? 0} purchased · {summary?.subscription_total ?? 0} from subscriptions · {summary?.free_total ?? 0} complimentary · {wallet.researches_completed} investigations completed
                </p>
                {wallet.total === 0 && (
                  <div className="wl-banner">
                    You have no credits available. Buy a bundle below or choose a subscription to keep researching.
                  </div>
                )}
                <div className="wl-costs">
                  {(["light", "medium", "deep"] as const).map((mode) => (
                    <div key={mode}>
                      <b>{wallet.mode_costs[mode] ?? (mode === "light" ? 1 : mode === "medium" ? 2 : 3)} cr</b>
                      <span>{mode[0].toUpperCase() + mode.slice(1)} research</span>
                    </div>
                  ))}
                </div>
                <p className="intro" style={{ marginTop: 14, marginBottom: 0 }}>
                  Credits are reserved when an investigation starts and finalized when a report is delivered. Failed investigations are refunded automatically.
                </p>
              </section>

              <section className="wl-card" aria-labelledby="buy-heading">
                <div className="wl-card-head">
                  <div>
                    <h2 id="buy-heading">Buy research credits</h2>
                    <p className="intro">One-time purchase. Credits never expire.</p>
                  </div>
                </div>
                <div className="qty">
                  <button type="button" aria-label="Decrease credits" onClick={() => setQty((n) => Math.max(minCredits, n - 5))}>−</button>
                  <input
                    type="number"
                    min={minCredits}
                    max={200}
                    value={qty}
                    aria-label="Credit quantity"
                    onChange={(e) => setQty(Math.max(0, Math.min(200, Number(e.target.value) || 0)))}
                  />
                  <button type="button" aria-label="Increase credits" onClick={() => setQty((n) => Math.min(200, n + 5))}>+</button>
                </div>
                <div className="tiers">
                  {tiers.map((tier) => (
                    <button
                      key={tier.quantity}
                      type="button"
                      className={qty === tier.quantity ? "on" : ""}
                      onClick={() => setQty(tier.quantity)}
                    >
                      {tier.quantity} · ${tier.total.toFixed(2)}
                    </button>
                  ))}
                </div>
                <div className="wl-kv">
                  <dt>You pay</dt><dd>{money(quote?.total_cents)}</dd>
                  <dt>Credits received</dt><dd>{quote?.quantity ?? qty}</dd>
                  <dt>Rate</dt><dd>{quote ? `$${quote.unit_price.toFixed(2)} / credit` : "—"}</dd>
                  <dt>Discount</dt><dd>{discount > 0 ? `${discount}% off` : "—"}</dd>
                </div>
                <button
                  className="btn dark"
                  style={{ width: "100%" }}
                  disabled={busy === "credits" || qty < minCredits}
                  onClick={() => buyCredits(Math.max(minCredits, qty))}
                >
                  {busy === "credits" ? "Opening Stripe…" : `Buy ${Math.max(minCredits, qty)} credits`}
                </button>
                <p className="intro" style={{ marginTop: 12, marginBottom: 0 }}>
                  Pricing is calculated and verified by the server. Payment is handled securely by Stripe.
                </p>
              </section>
            </div>

            <section className="wl-card" style={{ marginTop: 20 }} aria-labelledby="subscription-heading">
              <div className="wl-card-head">
                <div>
                  <h2 id="subscription-heading">Subscription</h2>
                  <p className="intro">Plans, billing and renewal details.</p>
                </div>
                {sub && <span className={statusClass(sub.display_status)}>{sub.display_status}</span>}
              </div>

              {sub ? (
                <>
                  <dl className="wl-kv">
                    <dt>Plan</dt><dd>{sub.plan_label}</dd>
                    <dt>Billing</dt><dd>{sub.billing_interval}</dd>
                    <dt>Price</dt>
                    <dd>{sub.price_cents ? `${money(sub.price_cents)} / ${sub.billing_interval === "annual" ? "year" : "month"}` : "—"}</dd>
                    <dt>Started</dt><dd>{date(sub.started_at)}</dd>
                    <dt>Current period</dt><dd>{date(sub.current_period_start)} – {date(sub.current_period_end)}</dd>
                    <dt>{sub.cancel_at_period_end ? "Access ends" : "Next renewal"}</dt>
                    <dd>{date(sub.access_ends_at ?? sub.current_period_end)}</dd>
                    <dt>Monthly credits</dt><dd>{sub.credits_per_period}</dd>
                  </dl>
                  {sub.renews && (
                    <div className="wl-banner info">
                      {sub.billing_interval === "annual"
                        ? `Annual plan: ${sub.credits_per_period} credits are added at the start of each billing month, not all at once.`
                        : `${sub.credits_per_period} credits are added at each renewal. Unused subscription credits do not roll over.`}
                    </div>
                  )}
                  {sub.cancel_at_period_end && (
                    <div className="wl-banner">
                      Cancellation scheduled. Your subscription is still active until {date(sub.current_period_end)}; access ends on that date. Purchased credits are unaffected.
                    </div>
                  )}
                  {["past_due", "unpaid", "expired"].includes(sub.status) && (
                    <div className="wl-banner error">
                      Your latest payment was not completed. Update your payment method in Stripe to restore renewals.
                    </div>
                  )}
                  <div className="wl-actions">
                    <button className="btn dark sm" onClick={openPortal} disabled={busy === "portal"}>
                      {busy === "portal" ? "Opening…" : "Manage in Stripe"}
                    </button>
                    <button
                      className="btn ghost sm"
                      onClick={() => startPlan(sub.plan as "research_pro" | "business", sub.billing_interval === "annual" ? "monthly" : "annual")}
                      disabled={busy.startsWith("research_pro:") || busy.startsWith("business:")}
                    >
                      Switch to {sub.billing_interval === "annual" ? "monthly" : "annual"}
                    </button>
                    {sub.plan === "research_pro" && (
                      <button
                        className="btn ghost sm"
                        onClick={() => startPlan("business", billingInterval)}
                        disabled={busy !== ""}
                      >
                        Upgrade to Business
                      </button>
                    )}
                    {!sub.cancel_at_period_end && (
                      <button className="btn ghost sm" onClick={() => setConfirmCancel(true)}>Cancel subscription</button>
                    )}
                  </div>
                  {confirmCancel && (
                    <div className="wl-confirm" role="alert">
                      <p>
                        Cancel {sub.plan_label} at the end of the paid period? You keep access and subscription credits until {date(sub.current_period_end)}. Purchased credits are never removed.
                      </p>
                      <div className="wl-actions">
                        <button className="btn dark sm" onClick={cancelSubscription} disabled={busy === "cancel"}>
                          {busy === "cancel" ? "Cancelling…" : "Confirm cancellation"}
                        </button>
                        <button className="btn ghost sm" onClick={() => setConfirmCancel(false)}>Keep subscription</button>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <div className="wl-banner info">
                    No active subscription. Choose a plan below, or simply buy credits as you need them.
                  </div>
                  <div className="toggle" role="group" aria-label="Billing period">
                    <button type="button" className={billingInterval === "monthly" ? "on" : ""} onClick={() => setBillingInterval("monthly")}>Monthly</button>
                    <button type="button" className={billingInterval === "annual" ? "on" : ""} onClick={() => setBillingInterval("annual")}>Annual</button>
                  </div>
                  <div className="wl-plans">
                    {(["research_pro", "business"] as const).map((plan) => {
                      const info = plan === "research_pro" ? pricing?.research_pro : pricing?.business;
                      const cost = info ? (billingInterval === "annual" ? info.annual_cost : info.monthly_cost) : null;
                      return (
                        <article className="wl-plan" key={plan}>
                          <span className="name">{plan === "research_pro" ? "Research Pro" : "Business"}</span>
                          <span className="price">
                            {cost == null ? "—" : `$${cost.toFixed(2)}`}
                            <small> / {billingInterval === "annual" ? "year" : "month"}</small>
                          </span>
                          <p>
                            {info
                              ? billingInterval === "annual"
                                ? info.annual_credits_per_month
                                : info.monthly_credits
                              : "—"}{" "}
                            credits added every billing month.
                          </p>
                          <button className="btn dark sm" disabled={!cost || busy !== ""} onClick={() => startPlan(plan, billingInterval)}>
                            {busy === `${plan}:${billingInterval}` ? "Opening…" : `Choose ${plan === "research_pro" ? "Pro" : "Business"}`}
                          </button>
                        </article>
                      );
                    })}
                  </div>
                </>
              )}
            </section>

            <section className="wl-compare" aria-label="Plan comparison">
              <article className={`wl-tier ${currentTier === "free" ? "current" : ""}`}>
                <span className="kicker mono">01 / Free</span>
                <span className="name">Explore</span>
                <span className="price">$0<small> / forever</small></span>
                <p>One complimentary Light investigation, then pay as you go.</p>
                {currentTier === "free" ? (
                  <span className="now">Current plan</span>
                ) : (
                  <a className="btn ghost sm" href="/dashboard">Use free tier</a>
                )}
              </article>
              <article className={`wl-tier ${currentTier === "pay_as_you_go" ? "current" : ""}`}>
                <span className="kicker mono">02 / Credits</span>
                <span className="name">Pay as you go</span>
                <span className="price">From $5<small> / bundle</small></span>
                <p>Credits never expire. Larger bundles are discounted.</p>
                {currentTier === "pay_as_you_go" ? (
                  <span className="now">Current plan</span>
                ) : (
                  <button className="btn ghost sm" onClick={() => buyCredits(Math.max(minCredits, qty))} disabled={busy === "credits"}>
                    Buy credits
                  </button>
                )}
              </article>
              {(["research_pro", "business"] as const).map((plan, index) => {
                const info = plan === "research_pro" ? pricing?.research_pro : pricing?.business;
                const cost = info?.monthly_cost;
                const label = plan === "research_pro" ? "Research Pro" : "Business";
                return (
                  <article className={`wl-tier ${currentTier === plan ? "current" : ""}`} key={plan}>
                    <span className="kicker mono">0{index + 3} / Subscription</span>
                    <span className="name">{label}</span>
                    <span className="price">{cost == null ? "—" : `$${cost.toFixed(2)}`}<small> / month</small></span>
                    <p>{info?.monthly_credits ?? "—"} credits added every billing month.</p>
                    {currentTier === plan ? (
                      <span className="now">Current plan</span>
                    ) : (
                      <button className="btn ghost sm" onClick={() => startPlan(plan, "monthly")} disabled={!cost || busy !== ""}>
                        Choose {plan === "research_pro" ? "Pro" : "Business"}
                      </button>
                    )}
                  </article>
                );
              })}
            </section>

            <section className="wl-card" style={{ marginTop: 20 }} aria-labelledby="history-heading">
              <div className="wl-card-head">
                <div>
                  <h2 id="history-heading">Transaction history</h2>
                  <p className="intro">Credits and payments recorded on your account.</p>
                </div>
              </div>
              <div className="wl-tools">
                <input
                  type="search"
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  placeholder="Search description or reference"
                  aria-label="Search transactions"
                />
                <select
                  value={typeFilter}
                  onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
                  aria-label="Filter by type"
                >
                  <option value="">All types</option>
                  {TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
                <select
                  value={statusFilter}
                  onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
                  aria-label="Filter by status"
                >
                  <option value="">All statuses</option>
                  {STATUSES.map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
              </div>
              {!txs ? (
                <div className="wl-skeleton" style={{ minHeight: 160 }} aria-busy="true" />
              ) : txs.transactions.length === 0 ? (
                <div className="wl-empty">
                  {query || typeFilter || statusFilter
                    ? "No transactions match these filters."
                    : "No transactions yet. Your first investigation or purchase will appear here."}
                </div>
              ) : (
                <>
                  <div style={{ overflowX: "auto" }}>
                    <table className="wl-ledger">
                      <thead>
                        <tr>
                          <th>Date</th><th>Type</th><th>Description</th><th>Credits</th><th>Amount</th><th>Status</th><th>Reference</th>
                        </tr>
                      </thead>
                      <tbody>
                        {txs.transactions.map((tx) => (
                          <tr key={tx.id}>
                            <td className="mono">{date(tx.created_at)}</td>
                            <td>{tx.category.replaceAll("_", " ")}</td>
                            <td>
                              {tx.description}
                              {tx.investigation_id && <div className="sub mono">{tx.investigation_id.slice(0, 12)}…</div>}
                            </td>
                            <td className={`mono ${tx.credits > 0 ? "pos" : "neg"}`}>
                              {tx.credits > 0 ? `+${tx.credits}` : tx.credits}
                            </td>
                            <td className="mono">{money(tx.amount_cents, tx.currency)}</td>
                            <td className="mono">{tx.status}</td>
                            <td className="mono sub">{tx.reference ? tx.reference.slice(0, 16) : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="wl-pager">
                    <span>{txs.offset + 1}–{txs.offset + txs.transactions.length} of {txTotal}</span>
                    <div className="btns">
                      <button type="button" onClick={() => setPage((n) => Math.max(1, n - 1))} disabled={page <= 1} aria-label="Previous page">←</button>
                      <button type="button" onClick={() => setPage((n) => Math.min(pages, n + 1))} disabled={page >= pages} aria-label="Next page">→</button>
                    </div>
                  </div>
                </>
              )}
            </section>

            <div className="wl-footer">
              <span>Need help with a charge or your plan? See <a href="/pricing" className="link-btn">plans &amp; billing</a>.</span>
              <a href="/dashboard" className="btn ghost sm">Back to dashboard</a>
            </div>
          </>
        )}
      </main>
    </>
  );
}
