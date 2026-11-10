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

    const body = await req.json();
    const { type, credentials } = body;

    if (type === "google") {
      const {
        data: { session },
        error,
      } = await supabase.auth.getSession();

      if (error) {
        return NextResponse.json({ error: error.message }, { status: 400 });
      }

      return NextResponse.json({
        ok: true,
        session: session
          ? {
              access_token: session.access_token,
              expires_at: session.expires_at,
              user: session.user
                ? {
                    id: session.user.id,
                    email: session.user.email,
                  }
                : null,
            }
          : null,
      });
    }

    if (type === "email") {
      const { email, password } = credentials ?? {};

      if (!email || !password) {
        return NextResponse.json(
          { error: "Email and password are required." },
          { status: 400 }
        );
      }

      const { data, error } = await supabase.auth.signInWithPassword({
        email,
        password,
      });

      if (error) {
        return NextResponse.json({ error: error.message }, { status: 400 });
      }

      return NextResponse.json({
        ok: true,
        user: data.user
          ? {
              id: data.user.id,
              email: data.user.email,
            }
          : null,
        session: data.session
          ? {
              access_token: data.session.access_token,
              expires_at: data.session.expires_at,
            }
          : null,
      });
    }

    return NextResponse.json(
      { error: "Invalid login type" },
      { status: 400 }
    );
  } catch (error) {
    console.error("Supabase login error:", error);

    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}