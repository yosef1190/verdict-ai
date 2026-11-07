import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
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

    const body = await req.json();
    const { type } = body; // "email" or "google"

    if (type === "email") {
      // Email verification - Supabase handles this differently
      // The email is verified when the user signs up with email+password
      // or clicks the verification link sent to their email
      const { data: { session }, error } = await supabase.auth.getSession();
      
      if (error) {
        return NextResponse.json({ error: error.message }, { status: 400 });
      }

      return NextResponse.json({ 
        ok: true, 
        session: session ? {
          access_token: session.access_token,
          expires_at: session.expires_at,
          user: session.user ? {
            id: session.user.id,
            email: session.user.email,
            email_confirmed_at: session.user.email_confirmed_at,
          } : null
        } : null
      });
    }

    if (type === "google") {
      // Google users - email is typically confirmed via Google
      const { data: { session }, error } = await supabase.auth.getSession();
      
      if (error) {
        return NextResponse.json({ error: error.message }, { status: 400 });
      }

      return NextResponse.json({ 
        ok: true, 
        session: session ? {
          access_token: session.access_token,
          expires_at: session.expires_at,
          user: session.user ? {
            id: session.user.id,
            email: session.user.email,
            // Google users typically have email_confirmed_at set
          } : null
        } : null
      });
    }

    return NextResponse.json({ error: "Invalid verification type" }, { status: 400 });

  } catch (e) {
    console.error("Supabase verify error:", e);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}