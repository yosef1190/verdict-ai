import { relay, requireUser, unauthorized } from "@/lib/research";

export const dynamic = "force-dynamic";

/** The signed-in user's credit balances and free-trial eligibility. */
export async function GET(req: Request) {
  const user = await requireUser(req);
  if (!user) return unauthorized();
  return relay("/api/wallet", { user });
}
