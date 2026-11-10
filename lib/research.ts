import "server-only";
import { createClient } from "@supabase/supabase-js";

/** Where the Vercel-deployed Python research API is listening. */
export const RESEARCH_API_URL = (process.env.RESEARCH_API_URL || "").replace(/\/$/, "");
/*
 * Set NEXT_PUBLIC_RESEARCH_API_URL in Vercel env vars to your
 * Vercel Python Function URL, e.g.
 *   https://your-project.vercel.app/api
 * If left empty, the relay will construct the URL from the current
 * origin, but for production deployments you should set this.
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
