"use client";

import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import Logo from "@/components/Logo";
import Dial from "@/components/Dial";
import Research from "@/components/Research";

export default function Dashboard() {
  const { user, loading, signOut } = useAuth();
  const router = useRouter();
  const [wallet, setWallet] = useState<{ subscription_credits: number; purchased_credits: number } | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  if (loading || !user) return null;

  const name = user.user_metadata?.full_name ?? user.email?.split("@")[0] ?? "Account";

  // Fetch wallet data
  useEffect(() => {
    const fetchWallet = async () => {
      const { data: { session} } = await supabase.auth.getSession();
      if (session) {
        const res = await fetch(`${process.env.NEXT_PUBLIC_URL || "http://localhost:3000"}/api/wallet`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
          cache: "no-store",
        });
        if (res.ok) setWallet(await res.json());
      }
    };
    fetchWallet();
  }, []);

  return (
    <>
      <header className="nav">
        <div className="wrap nav-in">
          <Logo />
          <div className="auth">
            <a className="btn ghost sm" href="/pricing">Plan &amp; credits</a>
            {user.user_metadata?.avatar_url
              ? <img className="avatar" src={user.user_metadata.avatar_url} alt="" referrerPolicy="no-referrer" />
              : <span className="avatar ph" aria-hidden="true">{name[0]?.toUpperCase()}</span>}
            <span className="uname">{name}</span>
            <button className="btn ghost sm" onClick={signOut}>Sign out</button>
          </div>
        </div>
      </header>
      <main className="wrap rs-main">
        <section className="rs-hero">
          <Dial size={132} value={0} label={false} />
          <h1 className="serif">Research a product. <em>Get your Verdict.</em></h1>
          <p className="lede">Paste a product link. Verdict reads the page, finds independent reviews and complaints, and scores it from 0 to 100.</p>
        </section>
        <Research />
        <section className="dashboard-billing">
          <h2>Billing</h2>
          <div className="billing-status">
            {wallet && wallet.subscription_credits > 0 && (
              <div>
                <span>Subscription active</span>
                <small>· {wallet.subscription_credits} monthly credits</small>
              </div>
            )}
            {wallet && wallet.purchased_credits > 0 && (
              <div>
                <span>Purchased credits</span>
                <small>· {wallet.purchased_credits} never-expire credits</small>
              </div>
            )}
            {(!wallet || wallet.subscription_credits === 0) && wallet?.purchased_credits === 0 && (
              <div>
                <span>No active subscription</span>
                <small>Subscribe to research credits monthly</small>
              </div>
            )}
          </div>
          <div className="billing-actions">
            <button className="btn light" onClick={() => router.push("/pricing")}>Manage subscription</button>
          </div>
        </section>
      </main>
    </>
  );
}
