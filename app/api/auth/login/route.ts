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
    const { type, credentials } = body; // type: "google" | "email", credentials: { idToken | email, password }

    if (type === "google") {
      // Google OAuth - we'll handle this via the frontend OAuth flow
      // This endpoint can be used to verify/continue a Google session
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
          } : null
        } : null
      });
    }

    if (type === "email") {
      const { email, password } = credentials;
      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });

      if (error) {
        return NextResponse.json({ error: error.message }, { status: 400 });
      }

      return NextResponse.json({ 
        ok: true, 
        user: data.user ? {
          id: data.user.id,
          email: data.user.email,
        } : null,
        session: data.session ? {
          access_token: data.session.access_token,
          expires_at: data.session.expires_at,
        } : null
      });
    }

    return NextResponse.json({ error: "Invalid login type" }, { status: 400 });

  } catch (e) {
    console.error("Supabase login error:", e);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}