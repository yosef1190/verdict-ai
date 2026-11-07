"use server";

export const EMAIL_RE = /^[^\\s@]+@[^\\s@]+\.[^\\s@]+$/;

export async function readJson(req: Request): Promise<Record<string, unknown>> {
  try { return (await req.json()) as Record<string, unknown>; } catch { return {}; }
}

export const str = (v: unknown) => (typeof v === "string" ? v : "");

export function fail(e: unknown) {
  console.error("[auth]", e);
  return Response.json({ error: "Something went wrong. Please try again." }, { status: 500 });
}