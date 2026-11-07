import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/cookie";
import { NextResponse } from "next/server";
import type { Request } from "node:http";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  try {
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          get(name: string) {
            return cookies().get(name)?.value;
          },
          set(name: string, value: string, options: any) {
            cookies().set(name, value, options);
          },
          remove(name: string, options: any) {
            cookies().set(name, "", { ...options, maxAge: 0 });
          },
        },
      }
    );

    // Since we're Google-only auth, there are no email codes to resend.
    // If someone triggers resend, just return success or inform them.
    // Supabase doesn't use email OTP codes for Google auth.
    
    const { data: { session } } = await supabase.auth.getSession();
    
    return NextResponse.json({ 
      ok: true, 
      note: "Google sign-in doesn't use email codes - session persists via cookies",
      session: session ? {
        user: session.user ? {
          id: session.user.id,
          email: session.user.email,
        } : null
      } : null
    });
  } catch (e) {
    console.error("Supabase resend error:", e);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}