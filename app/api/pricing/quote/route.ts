import { relay } from "@/lib/research";

export const dynamic = "force-dynamic";

/** Server-side price quote. The browser never computes the amount it will pay. */
export async function POST(req: Request) {
  const payload = await req.json().catch(() => ({}));
  return relay("/api/pricing/quote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
