import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  try {
    // Create Supabase client with cookie session
    const cookieStore = await cookies();
    const supabase = createServerClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
      {
        cookies: {
          get(name: string) {
            return cookieStore.get(name)?.value;
          },
          set(name: string, value: string, options: any) {
            cookieStore.set(name, value, options);
          },
          remove(name: string, options: any) {
            cookieStore.set(name, "", { ...options, maxAge: 0 });
          },
        },
      }
    );

    // Get the session - sign up with Google usually means we have a Google user
    // but we need to handle the onboarding
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      return NextResponse.json(
        { error: "No session found. Please sign in first." },
        { status: 401 }
      );
    }

    // For Google signup, we might just return the user info
    // or create/onboard the user
    const { data: { user } } = await supabase.auth.getUser();

    return NextResponse.json({ 
      ok: true, 
      user: user ? {
        id: user.id,
        email: user.email,
        // Add any custom fields here
      } : null 
    });
  } catch (e) {
    console.error("Supabase signup error:", e);
    return NextResponse.json(
      { error: "Internal server error" },
      { status: 500 }
    );
  }
}