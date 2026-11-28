import { relay, requireUser, unauthorized } from "@/lib/research";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const user = await requireUser(req);
  if (!user) return unauthorized();
  const payload = await req.json().catch(() => ({}));
  return relay("/api/checkout/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    user,
  });
}
