import { relay } from "@/lib/research";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const secret = process.env.CRON_SECRET;
  const supplied = req.headers.get("authorization")?.replace(/^Bearer\s+/i, "").trim();
  if (!secret || !supplied || supplied !== secret) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }
  return relay("/api/subscriptions/allocate", {
    method: "POST",
    headers: { "X-Cron-Secret": secret },
  });
}
