// Type definitions for Supabase PostgreSQL database
// These correspond to tables in your Supabase project

import { createClient } from "@supabase/supabase-js";

type SupabaseClient = ReturnType<typeof createClient>;

export type Database = {
  public: {
    Tables: {
      // Users table - extends supabase auth.users with custom fields
      users: {
        Row: {
          id: string; // matches auth.users.id
          email: string | null;
          full_name: string | null;
          avatar_url: string | null;
          created_at: string;
          updated_at: string;
          // Custom fields for your app
          // e.g., onboarding_completed: boolean;
        };
        Insert: {
          id: string;
          email: string | null;
          full_name: string | null;
          avatar_url: string | null;
          created_at: string;
          updated_at: string;
        };
        Update: {
          full_name?: string;
          avatar_url?: string;
          // e.g., onboarding_completed?: boolean;
        };
      };
      
      // Additional tables you might need for a SaaS app
      profiles: {
        Row: {
          id: string;
          user_id: string;
          // ... other fields
        };
        Insert: {
          id: string;
          user_id: string;
        };
        Update: {
          // fields to update
        };
      };
      
      // Add more tables as needed for your app
    };
    Views: {
      // Add views if any
    };
    Functions: {
      // Add server-side functions if any
    };
    Types: {
      // Add custom types if any
    };
  };
};