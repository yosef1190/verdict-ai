// Supabase auth helpers - no OTP codes, no Firestore storage needed
// Supabase handles session management natively via cookies

/**
 * No-op since Supabase handles auth natively.
 * Google users are authenticated via Supabase OAuth session.
 * No custom token creation or OTP verification needed.
 */
export const googleSignIn = async () => {
  // Supabase signInWithOAuth is called from the UI component
  // This function exists for API consistency but Supabase handles the flow
  return null;
};

/**
 * No-op - Supabase manages sessions automatically
 */
export const getUserUid = async () => {
  const { supabase } = await import("@/lib/supabase");
  const { data: { user } } = await supabase.auth.getUser();
  return user?.id ?? null;
};

/**
 * Get current user from Supabase session
 */
export async function getCurrentUser() {
  const { supabase } = await import("@/lib/supabase");
  const { data: { user} } = await supabase.auth.getUser();
  return user ?? null;
}