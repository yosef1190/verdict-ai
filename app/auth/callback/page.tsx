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
    router.replace(user ? "/dashboard" : "/login");
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
