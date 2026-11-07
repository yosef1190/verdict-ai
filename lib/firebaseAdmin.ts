// Server-side Supabase client for Next.js server functions and API routes
// Uses the service role key for administrative operations

import { createServerClient, type CookieOptions } from "@supabase/ssr";
import { cookies } from "next/cookie";

/**
 * Create Supabase server client with service role key for server-side operations.
 * This has full admin privileges to manage users, etc.
 */
export function createSupabaseServerClient() {
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!, // Service role key for admin ops
    {
      cookies: {
        get(name: string) {
          const cookie = cookies().get(name);
          return cookie?.value;
        },
        set(name: string, value: string, options: CookieOptions) {
          cookies().set(name, value, options);
        },
        remove(name: string, options: CookieOptions) {
          cookies().set(name, "", { ...options, maxAge: 0 });
        },
      },
    }
  );
}

/**
 * Get the current user from the request session (server side)
 */
export async function getServerSession() {
  const supabase = createSupabaseServerClient();
  const { data: { session} } = await supabase.auth.getSession();
  return session;
}

/**
 * Generate a signed in session for the client
 * Useful for API routes that need to set auth cookies
 */
export async function signInWithGoogleRedirect() {
  const supabase = createSupabaseServerClient();
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: `${process.env.NEXT_PUBLIC_URL || "http://localhost:3000"}/auth/callback`,
    },
  });
  
  if (error) throw error;
  return data;
}