"use client";
import { useAuth } from "./AuthProvider";
import Link from "next/link";

const GoogleG = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"/>
    <path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z"/>
    <path fill="#FBBC05" d="M10.5 28.7a14.5 14.5 0 010-9.4l-7.9-6.1a24 24 0 000 21.6z"/>
    <path fill="#34A853" d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.9 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.5 42.6 14.6 48 24 48z"/>
  </svg>
);

export function NavAuth() {
  const { user, loading, signInWithGoogle, signOut } = useAuth();
  if (loading) return <div className="auth" aria-hidden="true" style={{ minWidth: 150 }} />;
  if (user) {
    return (
      <div className="auth">
        {user.user_metadata?.avatar_url ? <img className="avatar" src={user.user_metadata.avatar_url} alt="" referrerPolicy="no-referrer" /> : <span className="avatar ph" aria-hidden="true">{(user.user_metadata?.full_name ?? user.email ?? "?")[0]?.toUpperCase()}</span>}
        <span className="uname">{user.user_metadata?.full_name ?? user.email?.split("@")[0] ?? "Account"}</span>
        <button className="btn ghost sm" onClick={signOut}>Sign out</button>
      </div>
    );
  }
  return (
    <div className="auth">
      <button className="btn light" onClick={signInWithGoogle}><GoogleG /> Sign up with Google</button>
    </div>
  );
}

export function CtaAuth() {
  const { user, loading, signOut, signInWithGoogle } = useAuth();
  if (user) {
    return (
      <div className="cta-row left">
        <a className="btn light" href="#top">Analyze a product</a>
        <button className="btn soft" onClick={signOut}>Sign out</button>
      </div>
    );
  }
  return (
    <div className="cta-row left">
      <button className="btn light" onClick={signInWithGoogle}><GoogleG /> Sign up with Google</button>
    </div>
  );
}