"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/AuthProvider";

/** Google/Supabase OAuth lands here; once the session is set, continue into the app. */
export default function AuthCallback() {
  const { user, loading } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (loading) return;
    let next = new URLSearchParams(window.location.search).get("next");
    try {
      next = next || sessionStorage.getItem("verdict:auth-next");
      sessionStorage.removeItem("verdict:auth-next");
    } catch {}
    const target = next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
    router.replace(user ? target : `/login?next=${encodeURIComponent(target)}`);
  }, [user, loading, router]);
  return (
    <div className="auth-shell">
      <main className="auth-main">
        <div className="auth-card">
          <p className="muted sub">Finishing sign-in…</p>
        </div>
      </main>
    </div>
  );
}
