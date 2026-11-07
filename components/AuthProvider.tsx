"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";

type Mode = "signin";

type Ctx = {
  user: import("@supabase/supabase-js").User | null;
  loading: boolean;
  error: string | null;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<Ctx | null>(null);

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<import("@supabase/supabase-js").User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Initialize session and listen for changes
  useEffect(() => {
    // Get initial session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null);
      setLoading(false);
    });

    // Listen for session changes
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      setUser(session?.user ?? null);
      setLoading(false);
      
      if (event === "SIGNED_OUT") {
        setError(null);
      }
    });

    return () => {
      subscription.unsubscribe();
    };
  }, []);

  const signInWithGoogle = useCallback(async () => {
    setError(null);
    try {
      await supabase.auth.signInWithOAuth({
        provider: "google",
        options: {
          redirectTo: `${process.env.NEXT_PUBLIC_URL || "http://localhost:3000"}/auth/callback`,
        },
      });
    } catch (e: any) {
      setError(e.message || "Google sign-in failed");
      throw e;
    }
  }, []);

  const signOut = useCallback(async () => {
    setError(null);
    try {
      await supabase.auth.signOut();
    } catch (e: any) {
      setError(e.message || "Sign out failed");
      throw e;
    }
  }, []);

  const value = useMemo<Ctx>(() => ({
    user,
    loading,
    error: error || null,
    signInWithGoogle,
    signOut,
  }), [user, loading, error, signInWithGoogle, signOut]);

  return (
    <AuthContext.Provider value={value}>
      {children}
      {error && <p className="auth-err error">{error}</p>}
    </AuthContext.Provider>
  );
}