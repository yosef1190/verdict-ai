"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@/components/AuthProvider";
import { authFetch } from "@/lib/auth-fetch";
import Logo from "@/components/Logo";
import { NavAuth } from "@/components/AuthButtons";

type Tier = { quantity: number; unit_price: number; total_cents: number; total: number };
type Plan = {
  monthly_cost: number;
  annual_cost?: number;
  monthly_credits?: number;
  annual_credits_per_month?: number;
  min_purchase?: number;
  features?: string[];
  tiers?: Tier[];
  pricing_tiers?: Record<string, number>;
};
type Pricing = { free: Plan; pay_as_you_go: Plan; research_pro: Plan; business: Plan; mode_costs: Record<string, number> };
type Wallet = { subscription_credits: number; purchased_credits: number; total: number; free_light_available: boolean };
type Tx = {
  id: string; type: string; amount: number; mode?: string | null; status: string; created_at: string;
  balance_after?: number | null; payment_reference?: string | null;
};
type PendingCheckout =
  | { kind: "credits"; quantity: number }
  | { kind: "plan"; plan: "research_pro" | "business"; annual: boolean };

const PENDING_CHECKOUT_KEY = "verdict:pending-checkout";

function savePendingCheckout(action: PendingCheckout) {
  try { sessionStorage.setItem(PENDING_CHECKOUT_KEY, JSON.stringify(action)); } catch {}
}

function readPendingCheckout(): PendingCheckout | null {
  try {
    const raw = sessionStorage.getItem(PENDING_CHECKOUT_KEY);
    if (!raw) return null;
    const action = JSON.parse(raw) as PendingCheckout;
    if (action.kind === "credits" && Number.isFinite(action.quantity)) return action;
    if (action.kind === "plan" && (action.plan === "research_pro" || action.plan === "business")) return action;
  } catch {}
  return null;
}

function clearPendingCheckout() {
  try { sessionStorage.removeItem(PENDING_CHECKOUT_KEY); } catch {}
}

async function api(path: string, init: RequestInit = {}) {
  const { res, body, error } = await authFetch(path, init);
  if (error) {
    return { res: null, body: { error: "Please log in to continue." }, error };
  }
  return { res, body, error: undefined };
}

const money = (n: number | null | undefined) => `$${(n ?? 0).toFixed(2)}`;

export default function PricingPage() {
  const { user, loading } = useAuth();
  const [pricing, setPricing] = useState<Pricing | null>(null);
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [txs, setTxs] = useState<Tx[]>([]);
  const [annual, setAnnual] = useState(false);
  const [qty, setQty] = useState(10);
  const [quote, setQuote] = useState<Tier | null>(null);
  const [busy, setBusy] = useState<string>("");
  const [error, setError] = useState("");
  const resumed = useRef(false);

  // Clear stale auth errors as soon as the signed-in session is available
  useEffect(() => {
    if (user && !loading) {
      setError("");
    }
  }, [user, loading]);

  // Clear error on mount if user is already available (avoid race condition)
  useEffect(() => {
    if (user) {
      setError("");
    }
  }, []);

  useEffect(() => {
    void (async () => {
      const { res, body } = await api("/api/pricing");
      if (res && res.ok) setPricing(body);
    })();
  }, []);

  useEffect(() => {
    if (!user) { setWallet(null); setTxs([]); return; }
    void (async () => {
      const { res, body } = await api("/api/wallet");
      if (res && res.ok) setWallet(body);
      const { res: res2, body: body2 } = await api("/api/transactions");
      if (res2 && res2.ok) setTxs(Array.isArray(body2.transactions) ? body2.transactions : []);
    })();
  }, [user]);

  // A checkout started while logged out resumes after the user signs in
  useEffect(() => {
    if (loading || !user || resumed.current) return;
    const pending = readPendingCheckout();
    if (!pending) return;
    resumed.current = true;
    clearPendingCheckout();
    void runCheckout(pending);
  }, [loading, user]);

  const tiers = useMemo(() => pricing?.pay_as_you_go?.tiers ?? [], [pricing]);

  const quoteFor = useCallback(async (quantity: number) => {
    const { res, body } = await api("/api/pricing/quote", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan: "pay_as_you_go", quantity }) });
    if (res && res.ok) setQuote(body);
  }, []);

  useEffect(() => {
    if (!pricing) return;
    const t = setTimeout(() => quoteFor(Math.max(5, Math.min(200, Math.floor(qty) || 5))), 150);
    return () => clearTimeout(t);
  }, [qty, pricing, quoteFor]);

  const maxUnit = tiers.length ? Math.max(...tiers.map((t) => t.unit_price)) : 1;

  function startCheckout(action: PendingCheckout) {
    if (loading) return;
    if (!user) {
      savePendingCheckout(action);
      window.location.href = "/login?next=/pricing";
      return;
    }
    void runCheckout(action);
  }

  async function runCheckout(action: PendingCheckout) {
    setBusy(action.kind === "credits" ? "credits" : action.plan);
    setError("");
    savePendingCheckout(action);
    try {
      const { res, body, error } = action.kind === "credits"
        ? await api("/api/checkout/credits", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ quantity: action.quantity }),
          })
        : await api("/api/checkout/subscription", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ plan: action.plan, annual: action.annual }),
          });

      if (error === "no_session" || error === "session_expired" || res?.status === 401) {
        setBusy("");
        if (user && !loading) {
          clearPendingCheckout();
          setError("Your session expired. Sign out and back in, then try checkout again.");
        } else {
          savePendingCheckout(action);
          window.location.href = "/login?next=/pricing";
        }
        return;
      }
      setBusy("");
      if (error || !res || !res.ok) {
        clearPendingCheckout();
        setError(body.error || error || "Checkout is not available yet.");
        return;
      }
      if (body.url) {
        clearPendingCheckout();
        window.location.href = body.url;
        return;
      }
      clearPendingCheckout();
      setError(body.message || body.error || "Checkout is not configured yet.");
    } catch (err: any) {
      setBusy("");
      clearPendingCheckout();
      setError(err?.message || "Could not start checkout.");
    }
  }

  const startCredits = () => startCheckout({ kind: "credits", quantity: qty });
  const startPlan = (plan: "research_pro" | "business") => startCheckout({ kind: "plan", plan, annual });

  const pro = pricing?.research_pro;
  const biz = pricing?.business;
  const proPrice = annual ? (pro?.annual_cost ?? 149.99) : (pro?.monthly_cost ?? 14.99);
  const bizPrice = annual ? (biz?.annual_cost ?? 299.99) : (biz?.monthly_cost ?? 29.99);
  const proCredits = annual ? (pro?.annual_credits_per_month ?? 50) : (pro?.monthly_credits ?? 50);
  const bizCredits = annual ? (biz?.annual_credits_per_month ?? 150) : (biz?.monthly_credits ?? 150);

  const planLabel = user ? (wallet && (wallet.subscription_credits > 0 || wallet.purchased_credits > 0) ? "Active" : "Free") : "Not signed in";

  return (
    <>
      <header className="nav">
        <div className="wrap nav-in">
          <Logo />
          <nav aria-label="Primary" className="links">
            <a href="/#how">How it works</a>
            <a href="/#analyze">What we analyze</a>
            <a href="/pricing">Pricing</a>
            {user && <a href="/dashboard">Dashboard</a>}
          </nav>
          <NavAuth />
        </div>
      </header>

      <main className="wrap pr-main">
        <section className="pr-hero">
          <p className="label mono" style={{ justifyContent: "center" }}><b>PRICING</b><i />Pay for the research you need</p>
          <h1 className="serif">Honest research, <em>honest pricing.</em></h1>
          <p className="lede">Buy a single investigation, or subscribe for credits every month. Purchased credits never expire. Subscription credits refresh each billing month—and don&apos;t roll over.</p>
          <div className="toggle" role="group" aria-label="Billing period">
            <button type="button" className={!annual ? "on" : ""} onClick={() => setAnnual(false)}>Monthly</button>
            <button type="button" className={annual ? "on" : ""} onClick={() => setAnnual(true)}>
              Annual<span className="save">−17%</span>
            </button>
          </div>
        </section>

        {error && <div className="rs-banner err" role="alert">{error}</div>}

        <section className="plans" aria-label="Plans">
          <article className="plan">
            <div className="kicker mono">Free</div>
            <h3>Start here</h3>
            <p className="amount">$0</p>
            <p className="sub">One complimentary Light investigation to see how Verdict works.</p>
            <ul>
              <li>1 free Light investigation</li>
              <li>Basic Verdict score</li>
              <li>Basic research report</li>
              <li>Limited research history</li>
              <li>No recurring credits</li>
            </ul>
            <a className="btn ghost" href={user ? "/dashboard" : "/signup"}>Get started</a>
          </article>

          <article className="plan">
            <div className="kicker mono">Pay as you go <span className="tag">No subscription</span></div>
            <h3>Buy credits</h3>
            <p className="amount">from $5</p>
            <p className="sub">One-time purchase. Credits never expire, and failed investigations are refunded.</p>
            <ul>
              <li>Light research — 1 credit</li>
              <li>Medium research — 2 credits</li>
              <li>Deep research — 3 credits</li>
              <li>Quantity discounts up to 50%</li>
              <li>Buy more any time</li>
            </ul>
            <button className="btn dark" type="button" onClick={() => document.getElementById("calculator")?.scrollIntoView({ behavior: "smooth" })}>
              Choose credits
            </button>
          </article>

          <article className="plan featured">
            <div className="kicker mono">Research Pro <span className="tag">Most popular</span></div>
            <h3>For regular buyers</h3>
            <p className="amount">{money(proPrice)} <small>/{annual ? "year" : "month"}</small></p>
            <p className="sub">{proCredits} credits every billing month. Full Light, Medium and Deep research.</p>
            <ul>
              <li>{proCredits} credits per billing month</li>
              <li>Full evidence reports</li>
              <li>Detailed source citations</li>
              <li>Priority processing</li>
              <li>Buy extra credits any time</li>
            </ul>
            <button className="btn light" type="button" onClick={() => startPlan("research_pro")} disabled={loading || busy === "research_pro"}>
              {busy === "research_pro" ? "Opening…" : "Choose Pro"}
            </button>
          </article>

          <article className="plan">
            <div className="kicker mono">Business</div>
            <h3>For teams</h3>
            <p className="amount">{money(bizPrice)} <small>/{annual ? "year" : "month"}</small></p>
            <p className="sub">{bizCredits} credits every billing month. Everything in Pro, plus bulk tools.</p>
            <ul>
              <li>{bizCredits} credits per billing month</li>
              <li>Bulk investigations</li>
              <li>Product comparisons</li>
              <li>Exportable reports</li>
              <li>Highest priority processing</li>
            </ul>
            <button className="btn ghost" type="button" onClick={() => startPlan("business")} disabled={loading || busy === "business"}>
              {busy === "business" ? "Opening…" : "Choose Business"}
            </button>
          </article>
        </section>

        <p className="plan-note">
          Annual plans grant credits <b>every billing month</b>—not all at once. Subscription credits reset monthly and do not roll over.{" "}
          <a href="#credits">Purchased credits never expire.</a>
        </p>

        <section className="calc" id="calculator">
          <div className="calc-form">
            <h3>Credit calculator</h3>
            <p>Pick how many credits you need. The price below is calculated by our server.</p>
            <div className="qty">
              <button type="button" aria-label="Decrease" onClick={() => setQty((q) => Math.max(5, Math.floor(q) - 5))}>−</button>
              <input
                type="number" min={5} max={200} step={1} value={qty}
                onChange={(e) => setQty(Math.max(0, Math.min(200, Number(e.target.value) || 0)))}
                aria-label="Credit quantity"
              />
              <button type="button" aria-label="Increase" onClick={() => setQty((q) => Math.min(200, Math.floor(q) + 5))}>+</button>
            </div>
            <div className="tiers">
              {tiers.map((t) => (
                <button key={t.quantity} type="button" className={t.quantity === qty ? "on" : ""} onClick={() => setQty(t.quantity)}>
                  {t.quantity}
                </button>
              ))}
            </div>
          </div>
          <div className="calc-out">
            <p className="kicker mono">Your total</p>
            <p className="total">{quote ? money((quote.total_cents ?? 0) / 100) : "—"}</p>
            <p className="per">{quote ? `${money(quote.unit_price)} per credit` : "Enter a quantity"}</p>
            <div className="rows">
              <div><span>Credits</span><b>{quote?.quantity ?? qty}</b></div>
              <div><span>Unit price</span><b>{quote ? money(quote.unit_price) : "—"}</b></div>
              <div>
                <span>You save</span>
                <b className="save">{quote ? `${Math.round((1 - quote.unit_price / maxUnit) * 100)}% vs 5-credit price` : "—"}</b>
              </div>
              <div><span>Expires</span><b>Never</b></div>
            </div>
            <button className="btn light" type="button" onClick={startCredits} disabled={loading || busy === "credits" || qty < 5}>
              {busy === "credits" ? "Opening…" : `Buy ${qty} credits`}
            </button>
          </div>
        </section>

        <section className="credit-strip" id="credits" aria-label="Research costs">
          {[
            ["Light", "light", "Under 5 minutes · 3 targeted searches"],
            ["Medium", "medium", "Under 10 minutes · claims vs reality"],
            ["Deep", "deep", "Under 15 minutes · safety & alternatives"],
          ].map(([name, key, desc]) => (
            <div className="credit-pill" key={key}>
              <span className="dot" /><b>{name}</b>
              <span className="mono">{pricing?.mode_costs?.[key] ?? "—"} cr</span>
              <span className="muted" style={{ fontSize: 12 }}>{desc}</span>
            </div>
          ))}
          <div className="credit-pill"><span className="dot ink" /><b>Your balance</b>
            <span className="mono">{wallet ? `${wallet.subscription_credits} sub · ${wallet.purchased_credits} bought` : planLabel}</span>
          </div>
        </section>

        {user && (
          <section className="hist" aria-label="Purchase history">
            <h2>Your ledger</h2>
            <table>
              <thead>
                <tr><th>Date</th><th>Type</th><th>Mode</th><th>Credits</th><th>Status</th><th>Balance</th></tr>
              </thead>
              <tbody>
                {txs.length === 0 && <tr><td colSpan={6} className="empty">No transactions yet. Your first free Light investigation will appear here.</td></tr>}
                {txs.map((t) => (
                  <tr key={t.id}>
                    <td className="mono">{new Date(t.created_at).toLocaleDateString()}</td>
                    <td>{t.type.replaceAll("_", " ")}</td>
                    <td className="mono">{t.mode ?? "—"}</td>
                    <td className={`mono ${t.amount >= 0 ? "pos" : "neg"}`}>{t.amount > 0 ? `+${t.amount}` : t.amount}</td>
                    <td className="mono">{t.status}</td>
                    <td className="mono">{t.balance_after ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <div className="notice">
          Credits are only deducted after a report is delivered. If an investigation fails, reserved credits are refunded automatically—once, and only once.
        </div>
      </main>

      <footer className="wrap foot">
        <Logo /><span className="muted">Product research, done for you.</span>
        <nav><a href="/#how">How it works</a><a href="/pricing">Pricing</a><span className="mono">© 2026</span></nav>
      </footer>
    </>
  );
}
