import { relay, requireUser, unauthorized } from "@/lib/research";

export const dynamic = "force-dynamic";

/** Immutable credit ledger for the signed-in user (newest first). */
export async function GET(req: Request) {
  const user = await requireUser(req);
  if (!user) return unauthorized();
  const query = new URL(req.url).searchParams.toString();
  return relay(`/api/transactions${query ? `?${query}` : ""}`, { user });
}
