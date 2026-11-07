import { relay, requireUser, unauthorized } from "@/lib/research";

export const dynamic = "force-dynamic";

/** Poll a research job for progress and the finished report. */
export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!(await requireUser(req))) return unauthorized();
  const { id } = await params;
  const since = new URL(req.url).searchParams.get("since") ?? "0";
  return relay(`/api/jobs/${encodeURIComponent(id)}?since=${encodeURIComponent(since)}`);
}
