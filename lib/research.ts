import "server-only";
import { createClient } from "@supabase/supabase-js";

/** URL of the Python research API (Render in production, localhost in dev). */
export const RESEARCH_API_URL = process.env.RESEARCH_API_URL || "http://localhost:8000";

export type RelayUser = { id: string; email?: string; token: string };

/** Verifies the Supabase access token sent by the browser. Returns the user, or null. */
export async function requireUser(req: Request): Promise<RelayUser | null> {
  const token = req.headers.get("authorization")?.replace(/^Bearer\s+/i, "").trim();
  if (!token) return null;
  const sb = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data, error } = await sb.auth.getUser(token);
  if (error || !data.user) return null;
  return { id: data.user.id, email: data.user.email ?? undefined, token };
}

export const unauthorized = () => Response.json({ error: "Please log in to run research." }, { status: 401 });

/**
 * Calls the research service and relays its JSON + status code.
 *
 * The user's verified id is forwarded as `X-User-Id`, signed with the shared
 * relay secret, and the original bearer token is passed along so the backend
 * can verify it independently. Nothing the browser sent is trusted blindly.
 */
export async function relay(
  path: string,
  init?: RequestInit & { user?: RelayUser | null },
) {
  const { user, ...rest } = init ?? {};
  const headers = new Headers(rest.headers);
  if (user) {
    headers.set("Authorization", `Bearer ${user.token}`);
    headers.set("X-User-Id", user.id);
    if (user.email) headers.set("X-User-Email", user.email);
  }
  const relaySecret = process.env.VERDICT_RELAY_SECRET;
  if (relaySecret) headers.set("X-Relay-Secret", relaySecret);

  try {
    const res = await fetch(`${RESEARCH_API_URL}${path}`, {
      ...rest,
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
    const body = await res.json().catch(() => ({ error: "Unexpected response from the research service." }));
    return Response.json(body, { status: res.status });
  } catch {
    return Response.json(
      { error: "The research service isn't reachable. Start it with `npm run dev:backend` (or ./dev.sh)." },
      { status: 502 },
    );
  }
}
