import "server-only";
import { createClient } from "@supabase/supabase-js";

/** URL of the Vercel-deployed Python research API.
 * In Vercel services mode, this is automatically set via the RESEARCH_API_URL binding
 * from the backend service. No manual configuration needed.
 */
export const RESEARCH_API_URL = process.env.RESEARCH_API_URL || "http://localhost:8000";

/**
 * Fallback: if RESEARCH_API_URL is not set (e.g. local dev without the binding),
 * the relay function will use the default above. In production, the Vercel
 * binding ensures this is always set.
 */

/** Verifies the Supabase access token sent by the browser. Returns the user, or null. */
export async function requireUser(req: Request) {
  const token = req.headers.get("authorization")?.replace(/^Bearer\s+/i, "").trim();
  if (!token) return null;
  const sb = createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data, error } = await sb.auth.getUser(token);
  return error ? null : data.user;
}

export const unauthorized = () => Response.json({ error: "Please log in to run research." }, { status: 401 });

/** Calls the research service and relays its JSON + status code. */
export async function relay(path: string, init?: RequestInit) {
  try {
    const res = await fetch(`${RESEARCH_API_URL}${path}`, { ...init, cache: "no-store", signal: AbortSignal.timeout(30_000) });
    const body = await res.json().catch(() => ({ error: "Unexpected response from the research service." }));
    return Response.json(body, { status: res.status });
  } catch {
    return Response.json(
      { error: "The research service isn't reachable. Start it with `npm run dev:backend` (or ./dev.sh)." },
      { status: 502 },
    );
  }
}
