import { relay, requireUser, unauthorized } from "@/lib/research";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  const user = await requireUser(req);
  if (!user) return unauthorized();
  return relay("/api/subscription/portal", { method: "POST", user });
}
