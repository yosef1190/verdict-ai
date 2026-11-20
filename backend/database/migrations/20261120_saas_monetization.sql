-- Migration: SaaS monetization tables
-- Adds subscriptions, credit wallets, reservations, transactions, payments,
-- investigation metadata, and refunds. All tables are user-scoped with RLS so
-- users can only read their own rows.
--
-- Security model:
--   * Clients may SELECT their own rows.
--   * Clients may NOT change balances, insert transactions, or mark payments.
--   * All wallet mutations go through the service-role key on the server.

-- ============================================================================
-- user_profiles: one row per user, tracks the FREE plan's complimentary grant
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'pay_as_you_go', 'research_pro', 'business')),
    free_light_used BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE user_profiles IS 'Per-user profile: current plan + whether the complimentary Light investigation has been claimed. The backend enforces the single-free-claim rule.';

-- ============================================================================
-- credit_wallets: two independent balances per user
-- ============================================================================
CREATE TABLE IF NOT EXISTS credit_wallets (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    subscription_credits INTEGER NOT NULL DEFAULT 0 CHECK (subscription_credits >= 0),
    purchased_credits INTEGER NOT NULL DEFAULT 0 CHECK (purchased_credits >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE credit_wallets IS 'Two independent balances per user. Subscription credits reset each billing cycle; purchased credits never expire.';

-- ============================================================================
-- subscriptions: active subscription records, monthly credit allowance
-- ============================================================================
CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL CHECK (plan IN ('research_pro', 'business')),
    billing_interval TEXT NOT NULL CHECK (billing_interval IN ('monthly', 'annual')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'canceled', 'past_due', 'trialing')),
    credits_per_period INTEGER NOT NULL,
    current_period_start TIMESTAMPTZ NOT NULL DEFAULT now(),
    current_period_end TIMESTAMPTZ NOT NULL,
    stripe_subscription_id TEXT UNIQUE,
    last_invoice_id TEXT,
    canceled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe ON subscriptions(stripe_subscription_id);

COMMENT ON TABLE subscriptions IS 'Active and historical subscriptions. Annual subscriptions still receive credits monthly (never all upfront), enforced by the backend when a period rolls over.';

-- ============================================================================
-- credit_reservations: prevents double-spend while an investigation runs
-- ============================================================================
CREATE TABLE IF NOT EXISTS credit_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    investigation_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('light', 'medium', 'deep')),
    cost INTEGER NOT NULL CHECK (cost > 0),
    status TEXT NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'finalized', 'released')),
    subscription_used INTEGER NOT NULL DEFAULT 0,
    purchased_used INTEGER NOT NULL DEFAULT 0,
    balance_before INTEGER NOT NULL DEFAULT 0,
    balance_after INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    UNIQUE (investigation_id)
);

CREATE INDEX IF NOT EXISTS idx_reservations_user ON credit_reservations(user_id, status);

COMMENT ON TABLE credit_reservations IS 'Reservation ledger. A row is inserted (status=held) when an investigation starts, finalized on success, released on failure. UNIQUE(investigation_id) makes reservation/finalize/refund idempotent.';

-- ============================================================================
-- credit_transactions: immutable transaction ledger
-- ============================================================================
CREATE TABLE IF NOT EXISTS credit_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN (
        'free_grant', 'subscription_grant', 'purchase', 'reservation',
        'consumption', 'refund', 'adjustment'
    )),
    amount INTEGER NOT NULL,
    mode TEXT CHECK (mode IN ('light', 'medium', 'deep')),
    investigation_id TEXT,
    payment_reference TEXT,
    status TEXT NOT NULL DEFAULT 'completed' CHECK (status IN ('pending', 'completed', 'failed', 'reversed')),
    balance_before INTEGER NOT NULL DEFAULT 0,
    balance_after INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_transactions_user ON credit_transactions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_investigation ON credit_transactions(investigation_id);

COMMENT ON TABLE credit_transactions IS 'Immutable ledger of every credit movement. Application code should only INSERT rows; balances live in credit_wallets.';

-- ============================================================================
-- investigations: per-research metadata (mode, cost, status)
-- ============================================================================
CREATE TABLE IF NOT EXISTS investigations (
    id TEXT PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK (mode IN ('light', 'medium', 'deep')),
    cost INTEGER NOT NULL CHECK (cost > 0),
    status TEXT NOT NULL DEFAULT 'starting' CHECK (status IN ('starting', 'running', 'completed', 'failed', 'refunded')),
    refunded BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    report_title TEXT,
    report_markdown TEXT,
    report_html TEXT,
    sources JSONB DEFAULT '[]',
    stage_timings JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_investigations_user ON investigations(user_id, started_at DESC);

COMMENT ON TABLE investigations IS 'Metadata about each research run. report_markdown/html store the delivered result so it survives Render sleeping.';

-- ============================================================================
-- payments: verified one-time and subscription payments
-- ============================================================================
CREATE TABLE IF NOT EXISTS payments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('credits', 'subscription')),
    plan TEXT,
    credit_amount INTEGER,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL DEFAULT 'usd',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded')),
    provider TEXT NOT NULL DEFAULT 'stripe',
    provider_session_id TEXT UNIQUE,
    provider_payment_intent TEXT,
    provider_subscription_id TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_payments_session ON payments(provider_session_id);

COMMENT ON TABLE payments IS 'Verified payments. provider_session_id is UNIQUE so webhook replays cannot grant credits twice.';

-- ============================================================================
-- refunds: record of refunded investigations
-- ============================================================================
CREATE TABLE IF NOT EXISTS investigation_refunds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    investigation_id TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    credits_refunded INTEGER NOT NULL CHECK (credits_refunded >= 0),
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (investigation_id)
);

COMMENT ON TABLE investigation_refunds IS 'Records credit refunds for failed investigations. UNIQUE(investigation_id) ensures a refund cannot be issued twice.';

-- ============================================================================
-- Row Level Security
-- ============================================================================
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_reservations ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE investigations ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE investigation_refunds ENABLE ROW LEVEL SECURITY;

-- Users may read only their own rows. No INSERT/UPDATE/DELETE policies are
-- granted to clients; only the service role mutates these tables.
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'user_profiles', 'credit_wallets', 'subscriptions',
        'credit_reservations', 'credit_transactions', 'investigations',
        'payments', 'investigation_refunds'
    ]
    LOOP
        EXECUTE format(
            'DROP POLICY IF EXISTS "%s_select_own" ON %I', t, t
        );
        EXECUTE format(
            'CREATE POLICY "%s_select_own" ON %I FOR SELECT USING (auth.uid() = user_id)',
            t, t
        );
    END LOOP;
END $$;

-- ============================================================================
-- Investigation mode columns on the existing research_jobs table
-- ============================================================================
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS mode TEXT DEFAULT 'light';
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS cost INTEGER DEFAULT 1;
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS stage_timings JSONB DEFAULT '{}';
ALTER TABLE research_jobs ADD COLUMN IF NOT EXISTS metrics JSONB DEFAULT '{}';

COMMENT ON COLUMN research_jobs.mode IS 'Research depth: light | medium | deep';
COMMENT ON COLUMN research_jobs.cost IS 'Credit cost of this investigation';
COMMENT ON COLUMN research_jobs.stage_timings IS 'Measured stage durations (seconds) for the performance report';
COMMENT ON COLUMN research_jobs.metrics IS 'Counts: search queries, sources found/accepted/rejected, retries, API failures';
-- ============================================================================
-- Atomic credit operations
-- ----------------------------------------------------------------------------
-- Credit math must never be a read-modify-write from application code: two
-- concurrent investigations could pass the balance check and overdraw the
-- wallet. These functions do the whole operation inside one transaction, with
-- FOR UPDATE on the wallet row, and are idempotent on investigation_id.
-- Only the service role may execute them.
-- ============================================================================

CREATE OR REPLACE FUNCTION verdict_reserve_credits(
    p_user_id UUID,
    p_investigation_id TEXT,
    p_mode TEXT,
    p_cost INTEGER
) RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_sub INTEGER;
    v_pur INTEGER;
    v_before INTEGER;
    v_sub_used INTEGER;
    v_pur_used INTEGER;
    v_row credit_reservations;
BEGIN
    IF p_cost IS NULL OR p_cost <= 0 THEN
        RAISE EXCEPTION 'invalid cost %', p_cost;
    END IF;

    -- Make sure the row exists, then take the lock that serialises this user.
    INSERT INTO credit_wallets (user_id) VALUES (p_user_id)
    ON CONFLICT (user_id) DO NOTHING;

    SELECT subscription_credits, purchased_credits
      INTO v_sub, v_pur
      FROM credit_wallets
     WHERE user_id = p_user_id
       FOR UPDATE;

    -- Replaying the same investigation id must not charge twice.
    SELECT * INTO v_row
      FROM credit_reservations
     WHERE investigation_id = p_investigation_id;
    IF FOUND THEN
        RETURN jsonb_build_object(
            'status', v_row.status, 'cost', v_row.cost, 'mode', v_row.mode,
            'subscription_used', v_row.subscription_used,
            'purchased_used', v_row.purchased_used,
            'balance_before', v_row.balance_before,
            'balance_after', v_row.balance_after,
            'already', TRUE
        );
    END IF;

    v_before := v_sub + v_pur;
    IF v_before < p_cost THEN
        RETURN jsonb_build_object(
            'status', 'insufficient', 'available', v_before, 'required', p_cost
        );
    END IF;

    -- Subscription credits are spent first.
    v_sub_used := LEAST(v_sub, p_cost);
    v_pur_used := p_cost - v_sub_used;

    UPDATE credit_wallets
       SET subscription_credits = subscription_credits - v_sub_used,
           purchased_credits = purchased_credits - v_pur_used,
           updated_at = now()
     WHERE user_id = p_user_id;

    INSERT INTO credit_reservations (
        user_id, investigation_id, mode, cost, status,
        subscription_used, purchased_used, balance_before, balance_after
    ) VALUES (
        p_user_id, p_investigation_id, p_mode, p_cost, 'held',
        v_sub_used, v_pur_used, v_before, v_before - p_cost
    );

    INSERT INTO credit_transactions (
        user_id, type, amount, mode, investigation_id, status,
        balance_before, balance_after
    ) VALUES (
        p_user_id, 'reservation', -p_cost, p_mode, p_investigation_id, 'completed',
        v_before, v_before - p_cost
    );

    RETURN jsonb_build_object(
        'status', 'held', 'cost', p_cost, 'mode', p_mode,
        'subscription_used', v_sub_used, 'purchased_used', v_pur_used,
        'balance_before', v_before, 'balance_after', v_before - p_cost,
        'already', FALSE
    );
END;
$$;

CREATE OR REPLACE FUNCTION verdict_finalize_credits(p_investigation_id TEXT)
RETURNS BOOLEAN
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE credit_reservations
       SET status = 'finalized', resolved_at = now()
     WHERE investigation_id = p_investigation_id
       AND status = 'held';
    RETURN FOUND;
END;
$$;

CREATE OR REPLACE FUNCTION verdict_refund_credits(
    p_investigation_id TEXT,
    p_reason TEXT DEFAULT ''
) RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_row credit_reservations;
    v_credits INTEGER;
    v_after INTEGER;
BEGIN
    SELECT * INTO v_row
      FROM credit_reservations
     WHERE investigation_id = p_investigation_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('refunded', FALSE, 'reason', 'missing');
    END IF;
    -- Finalized or already-released reservations are never refunded again.
    IF v_row.status <> 'held' THEN
        RETURN jsonb_build_object('refunded', FALSE, 'reason', v_row.status);
    END IF;

    v_credits := v_row.subscription_used + v_row.purchased_used;
    IF v_credits = 0 THEN
        -- Reservation recorded before the per-bucket columns existed: restore
        -- everything as purchased credits, which never expire.
        v_credits := v_row.cost;
    END IF;

    UPDATE credit_wallets
       SET subscription_credits = subscription_credits + v_row.subscription_used,
           purchased_credits = purchased_credits + (v_credits - v_row.subscription_used),
           updated_at = now()
     WHERE user_id = v_row.user_id
    RETURNING subscription_credits + purchased_credits INTO v_after;

    UPDATE credit_reservations
       SET status = 'released', resolved_at = now()
     WHERE id = v_row.id;

    INSERT INTO investigation_refunds (investigation_id, user_id, credits_refunded, reason)
    VALUES (p_investigation_id, v_row.user_id, v_credits, p_reason)
    ON CONFLICT (investigation_id) DO NOTHING;

    INSERT INTO credit_transactions (
        user_id, type, amount, mode, investigation_id, status,
        balance_before, balance_after
    ) VALUES (
        v_row.user_id, 'refund', v_credits, v_row.mode, p_investigation_id, 'completed',
        v_after - v_credits, v_after
    );

    RETURN jsonb_build_object(
        'refunded', TRUE, 'credits', v_credits, 'balance_after', v_after,
        'subscription_restored', v_row.subscription_used,
        'purchased_restored', v_credits - v_row.subscription_used
    );
END;
$$;

REVOKE ALL ON FUNCTION verdict_reserve_credits(UUID, TEXT, TEXT, INTEGER) FROM PUBLIC;
REVOKE ALL ON FUNCTION verdict_finalize_credits(TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION verdict_refund_credits(TEXT, TEXT) FROM PUBLIC;
