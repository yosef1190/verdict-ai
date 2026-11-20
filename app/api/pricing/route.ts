import { relay } from "@/lib/research";

export const dynamic = "force-dynamic";

/** Public pricing table, sourced from the backend config so prices never drift. */
export async function GET() {
  return relay("/api/pricing");
}
