"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";

export default function Wallet() {
  const { user: authUser, loading: authLoading } = useAuth();
  const router = useRouter();

  const [wallet, setWallet] = useState<{
    subscription_credits: number;
    purchased_credits: number;
    total: number;
    mode_costs: any;
    free_light_available: boolean;
  } | null>(null);

  const [transactions, setTransactions] = useState<any[]>([]);

  const [session, setSession] = useState<any>(null);
  const [loadingWallets, setLoadingWallets] = useState(true);

  // Get supabase session
  useEffect(() => {
    const getSession = async () => {
      const { data: { session} } = await supabase.auth.getSession();
      setSession(session);
    };
    getSession();
    const interval = setInterval(getSession, 300000);
    return () => clearInterval(interval);
  }, []);

  if (authLoading || !authUser) return null;

  // Fetch wallet data
  useEffect(() => {
    if (!session) return;
    const fetchData = async () => {
      const res = await fetch(`${process.env.NEXT_PUBLIC_URL || "http://localhost:3000"}/api/wallet`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
        cache: "no-store",
      });
      if (res.ok) setWallet(await res.json());
    };
    fetchData();
  }, [session]);

  // Fetch transactions
  useEffect(() => {
    if (!session) return;
    const fetchTransactions = async () => {
      const res = await fetch(`${process.env.NEXT_PUBLIC_URL || "http://localhost:3000"}/api/transactions`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
        cache: "no-store",
      });
      if (res.ok) setTransactions(await res.json());
    };
    fetchTransactions();
  }, [session]);

  // Set loading state when we have data
  useEffect(() => {
    if (session && wallet && transactions.length > 0) {
      setLoadingWallets(false);
    }
  }, [session, wallet, transactions]);

  // Only render when we have session and wallet data
  if (!session || wallet == null) return null;

  return (
    <section className="rs-main">
      <div className="wrap">
        <h1 className="serif">Wallet</h1>

        <div className="rs-card" style={{ padding: "24px" }}>
          <div className="rs-row" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "20px" }}>
            <div>
              <h3>Monthly Credits</h3>
              <p className="mono" style={{ fontSize: 24, margin: "10px 0" }}>
                {wallet.subscription_credits}
              </p>
              <p>Refreshes every month</p>
            </div>
            <div>
              <h3>Purchased Credits</h3>
              <p className="mono" style={{ fontSize: 24, margin: "10px 0" }}>
                {wallet.purchased_credits}
              </p>
              <p>Never expire</p>
            </div>
          </div>

          {wallet.total !== undefined && (
            <div style={{ margin: "20px 0", paddingTop: "20px", borderTop: "1px solid var(--line)" }}>
              <h3>Total Balance</h3>
              <p className="mono" style={{ fontSize: 28, fontWeight: 600, color: "var(--green)" }}>
                {wallet.total}
              </p>
            </div>
          )}

          {wallet.mode_costs && (
            <div style={{ margin: "20px 0" }}>
              <h3>Cost per Mode</h3>
              <p>{JSON.stringify(wallet.mode_costs)}</p>
            </div>
          )}

          <div style={{ marginTop: "20px" }}>
            <h3>Free Light Investigation</h3>
            <p>{wallet.free_light_available ? "Available" : "Used up"}</p>
          </div>
        </div>
      </div>

      {transactions.length > 0 && (
        <div className="rs-card" style={{ padding: "24px", marginTop: "32px" }}>
          <h3>Transaction History</h3>
          <div style={{ maxHeight: "400px", overflow: "auto" }}>
            {transactions.map((t: any, i: number) => (
              <div key={i} style={{ padding: "12px 0", borderBottom: "1px solid var(--line)" }}>
                <div>
                  <strong>{new Date(t.created_at).toLocaleDateString()}</strong>
                  <span style={{ marginLeft: "16px", color: "var(--muted)" }}>• {t.mode}</span>
                </div>
                <div style={{ float: "right" }}>
                  <span style={{ color: t.kind === "subscription" ? "var(--green)" : "var(--muted)" }}>
                    {t.credits} credits
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {transactions.length === 0 && (
        <p style={{ color: "var(--muted)", marginTop: "20px" }}>
          No transactions yet. Your first free Light investigation will appear here.
        </p>
      )}

      <div style={{ marginTop: "32px", clear: "both" }}>
        <a href="/" className="btn" style={{ float: "left" }}>← Back to Dashboard</a>
        <a href="/pricing" className="btn subtle" style={{ float: "right" }}>Manage Subscription</a>
      </div>
    </section>
  );
}