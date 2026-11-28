# Verdict

Next.js frontend (repo root) and Flask research/payments API (`backend/`).

## Environment variables

### Vercel (Next.js)

```env
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=your-supabase-anon-key
RESEARCH_API_URL=https://your-render-service.onrender.com
VERDICT_RELAY_SECRET=your-random-relay-secret
CRON_SECRET=your-random-cron-secret
```

### Render (Flask)

```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
VERDICT_RELAY_SECRET=your-random-relay-secret
VERDICT_CRON_SECRET=your-random-cron-secret
STRIPE_SECRET_KEY=sk_test_your-stripe-secret-key
STRIPE_WEBHOOK_SECRET=whsec_your-stripe-webhook-secret
APP_URL=https://your-vercel-app.vercel.app
OXYLABS_API_KEY=your-oxylabs-api-key
NVIDIA_API_KEY=your-nvidia-api-key
GEMINI_API_KEY=your-gemini-api-key
OPENROUTER_API_KEY=your-openrouter-api-key
```

`VERDICT_RELAY_SECRET` must be identical on Vercel and Render. `CRON_SECRET` (Vercel) and `VERDICT_CRON_SECRET` (Render) protect scheduled jobs; Flask accepts either name and prefers `VERDICT_CRON_SECRET`.

If `vercel.json` defines `crons` (or an external scheduler calls the Flask endpoints), set Vercel's `CRON_SECRET` to the same value as Render's `VERDICT_CRON_SECRET`. The scheduled endpoints are `/api/subscriptions/allocate`, `/api/admin/reconcile-payments`, and `/api/admin/sweep-reservations`.
