import { relay, requireUser, unauthorized } from "@/lib/research";

export const dynamic = "force-dynamic";

/** Start a research job. */
export async function POST(req: Request) {
  if (!(await requireUser(req))) return unauthorized();
  const payload = await req.json().catch(() => ({}));
  return relay("/api/research", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
