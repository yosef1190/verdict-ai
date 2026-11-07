"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "./AuthProvider";
import Logo from "./Logo";
import { supabase } from "@/lib/supabase";

const GoogleG = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"/>
    <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z"/>
    <path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 010-9.4l-7.9-6.1a24 24 0 000 21.6z"/>
    <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.9 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z"/>
  </svg>
);

export default function AuthForm({ mode }: { mode: "signin" }) {
  const { user, loading, signInWithGoogle, signOut } = useAuth();
  const router = useRouter();

  useEffect(() => { 
    if (user && !loading) router.replace("/dashboard"); 
  }, [user, loading, router]);

  if (user) return null;

  return (
    <div className="auth-shell">
      <header className="nav">
        <div className="wrap nav-in">
          <Logo />
          <Link className="btn ghost sm" href="/">← Back to home</Link>
        </div>
      </header>
      <main className="auth-main">
        <div className="auth-card">
          <h1 className="serif">Log in to Verdict</h1>
          <p className="muted sub">Welcome back.</p>
          <button type="button" className="btn light wide" onClick={signInWithGoogle} disabled={loading}><GoogleG /> Continue with Google</button>
        </div>
      </main>
    </div>
  );
}