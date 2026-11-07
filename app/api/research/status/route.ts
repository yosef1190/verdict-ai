import { relay, requireUser, unauthorized } from "@/lib/research";

export const dynamic = "force-dynamic";

/** Engines + whether the scraper / AI keys are configured on the server. */
export async function GET(req: Request) {
  if (!(await requireUser(req))) return unauthorized();
  return relay("/api/status");
}
