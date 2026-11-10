import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  try {
    const cookieStore = await cookies();

    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          getAll() {
            return cookieStore.getAll();
          },
          setAll(cookiesToSet) {
            try {
              cookiesToSet.forEach(({ name, value, options }) => {
                cookieStore.set(name, value, options);
              });
            } catch {
              // Cookie updates may be unavailable in certain server contexts.
            }
          },
        },
      }
    );

    const {
      data: { session },
    } = await supabase.auth.getSession();

    return NextResponse.json({
      ok: true,
      note: "Google sign-in doesn't use email codes.",
      session: session
        ? {
            user: {
              id: session.user.id,
              email: session.user.email,
            },
          }
        : null,
    });
  } catch (error) {
    console.error("Supabase resend error:", error);

    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}