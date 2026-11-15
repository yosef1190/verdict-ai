import { relay, requireUser, unauthorized } from "@/lib/research";

export const dynamic = "force-dynamic";

/** Poll a research job for progress and the finished report. */
export async function GET(req: Request) {
  // Extract job_id from URL path: /api/research/jobs/{job_id}
  const url = new URL(req.url);
  const job_id = url.pathname.split("/").pop() || "";
  
  if (!(await requireUser(req))) return unauthorized();
  return relay(`/api/jobs/${job_id}`);
}