-- Migration: Create research_jobs table for Vercel-deployed Verdict backend
-- This table replaces the in-memory Job dictionary used by the Flask implementation

-- Job ID (UUID primary key)
-- User ID (from Supabase auth, for RLS ownership)
-- Job status (queued | running | done | error | timeout)
-- Progress messages (JSONB array of step strings)
-- Research result (JSONB: title, markdown, sources, models)
-- Error message (text, if job failed)
-- Created timestamp (auto)
-- Updated timestamp (auto)

-- Row Level Security (RLS) will be enabled on this table
-- Users can only access their own jobs (user_id = auth.uid())

-- The table structure:
-- id UUID PRIMARY KEY DEFAULT gen_random_uuid()
-- user_id UUID NOT NULL REFERENCES auth.users(id)
-- status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'error', 'timeout'))
-- progress JSONB NOT NULL DEFAULT '[]'
-- result JSONB DEFAULT '{"title": "", "markdown": "", "sources": [], "models": []}'
-- error TEXT
-- created_at TIMESTAMPTZ NOT NULL DEFAULT now()
-- updated_at TIMESTAMPTZ NOT NULL DEFAULT now()

-- Index for fast lookups by user and status
CREATE INDEX idx_research_jobs_user_status ON research_jobs(user_id, status);
-- Index for lookups by job ID
CREATE INDEX idx_research_jobs_id ON research_jobs(id);

-- Comment explaining the table
COMMENT ON TABLE research_jobs IS 'Stores research job records for Vercel-deployed Verdict backend. RLS ensures users can only access their own jobs.';