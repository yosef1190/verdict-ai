import { RESEARCH_API_URL } from "@/lib/research";

export const dynamic = "force-dynamic";

/**
 * Forward Stripe webhooks to the Flask backend.
 *
 * The raw request body is passed through untouched so the backend can verify
 * the `Stripe-Signature` header against the exact bytes Stripe signed. Nothing
 * is trusted or granted on this side.
 */
export async function POST(req: Request) {
  const payload = await req.text();
  const signature = req.headers.get("stripe-signature") ?? "";

  try {
    const res = await fetch(`${RESEARCH_API_URL}/api/webhooks/stripe`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Stripe-Signature": signature },
      body: payload,
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    });
    return new Response(await res.text(), { status: res.status });
  } catch {
    return Response.json({ error: "Webhook relay unavailable." }, { status: 502 });
  }
}
