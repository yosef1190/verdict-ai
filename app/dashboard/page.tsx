"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";
import Logo from "@/components/Logo";
import Dial from "@/components/Dial";
import Research from "@/components/Research";

export default function Dashboard() {
  const { user, loading, signOut } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [user, loading, router]);

  if (loading || !user) return null;

  const name = user.user_metadata?.full_name ?? user.email?.split("@")[0] ?? "Account";

  return (
    <>
      <header className="nav">
        <div className="wrap nav-in">
          <Logo />
          <div className="auth">
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
      </main>
    </>
  );
}
