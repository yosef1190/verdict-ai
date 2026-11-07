# Verdict

One project, two services:

| Part | Path | Runs on | Does |
|---|---|---|---|
| Web app (Next.js) | `/` | `:3000` | Landing page, Google login (Supabase), research dashboard |
| Research engine (Python/Flask) | `/backend` | `:5000` (localhost only) | Scrapes the product page, searches for reviews/complaints, scores + writes the report |

**Flow:** landing page → "Sign up with Google" → `/dashboard` (the research tool).
The browser never talks to Flask directly. It calls `/api/research/*` on Next, which checks the
Supabase login token and then forwards to the research engine — so only signed-in users can spend your Oxylabs/LLM credits.

## Setup

```bash
# 1. web app
npm install

# 2. research engine
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ..

# 3. run both
./dev.sh            # or: npm run dev:backend  +  npm run dev  in two terminals
```

Environment files (unchanged from your originals):
- `.env.local` — Supabase / app settings for Next.js
- `backend/.env` — Oxylabs + NVIDIA / Gemini / OpenRouter keys for the research engine

Optional: set `RESEARCH_API_URL` (default `http://127.0.0.1:5000`) if the research engine runs elsewhere.

## Layout

```
app/                 landing (/), /login, /dashboard, /auth/callback, /api/research/*
components/Research.tsx   the research UI shown after login
lib/research.ts      login check + proxy to the Python service
backend/             the former verdict-research project (CLI: app.py, API: web.py, tests/)
```

The original landing README is kept as `README.landing.old.md`; the research engine's own docs are in `backend/README.md`.
# verdict-ai
