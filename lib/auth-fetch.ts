"use client";

import { supabase } from "./supabase";

/**
 * Authenticated fetch helper that:
 * 1. Gets the current session from Supabase
 * 2. Attaches Authorization: Bearer <access_token> to every request
 * 3. On 401, tries one session refresh and retry
 * 4. Only redirects to login if the refresh also fails
 * 5. Returns { res, body } for consistent handling across the app
 */
export async function authFetch(
  path: string,
  init: RequestInit = {}
): Promise<{ res: Response | null; body: any; error?: string }> {
  // Step 1: Get the current session
  const { data: sessionData, error: sessionError } = await supabase.auth.getSession();

  if (sessionError || !sessionData?.session?.access_token) {
    // No valid session - redirect to login with return URL
    // We use a gentle approach: set a flag that the redirect handler will pick up
    // Instead of hard window.location.href, we throw an error that the
    // calling code can handle to redirect
    return { res: null, body: { error: "Please log in to continue." }, error: "no_session" };
  }

  const token = sessionData.session.access_token;

  // Step 2: Make the request with the Bearer token
  const res = await fetch(path, {
    ...init,
    headers: {
      ...(init.headers || {}),
      ...(init.headers?.Authorization ? { Authorization: init.headers.Authorization } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    // Include credentials if needed for cookie-based auth
    credentials: "include",
  });

  const body = await res.json().catch(() => ({}));

  // Step 3: If 401, try to refresh the session and retry once
  if (res.status === 401) {
    // Try to refresh the session
    const { data: refreshed, error: refreshError } = await supabase.auth.refreshSession();

    if (!refreshError && refreshed?.session?.access_token) {
      // Refresh succeeded, retry the request with new token
      const newToken = refreshed.session.access_token;
      const res2 = await fetch(path, {
        ...init,
        headers: {
          ...(init.headers || {}),
          ...(init.headers?.Authorization ? { Authorization: init.headers.Authorization } : {}),
          ...(newToken ? { Authorization: `Bearer ${newToken}` } : {}),
        },
        credentials: "include",
      });
      const body2 = await res2.json().catch(() => ({}));
      return { res: res2, body: body2 };
    }

    // Refresh failed - return 401 error so caller can redirect to login
    return { res: null, body: { error: "Session expired. Please log in again." }, error: "session_expired" };
  }

  // Step 4: Successful response
  return { res, body };
}