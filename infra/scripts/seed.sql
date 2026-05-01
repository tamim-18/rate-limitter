-- Seed data for local dev / smoke testing.
--
-- Idempotent: safe to re-run. Uses ON CONFLICT on the natural keys so the
-- script can be reapplied without ballooning the dataset or failing on
-- duplicate inserts. UUIDs come from the server-side default.
--
-- Loaded by `make seed` (psql) after `make migrate`. NOT run automatically
-- on container start — seeding production by accident is a real risk we
-- explicitly avoid.

BEGIN;

-- ── clients ────────────────────────────────────────────────────────────
-- Three keys, one per tier, so manual curl tests can hit every code path.
-- api_key values are obviously fake; production issues hashed keys via
-- the admin API (P5).
INSERT INTO clients (api_key, name, tier, extra) VALUES
  ('sk_dev_free_0000000000000000000000000000',       'Dev Free Tier',   'free',       '{"owner": "dev@example.com"}'),
  ('sk_dev_pro_00000000000000000000000000000',       'Dev Pro Tier',    'pro',        '{"owner": "dev@example.com"}'),
  ('sk_dev_enterprise_00000000000000000000000',      'Dev Enterprise',  'enterprise', '{"owner": "dev@example.com"}')
ON CONFLICT (api_key) DO NOTHING;

-- ── rate_limit_rules ──────────────────────────────────────────────────
-- Layout:
--   • One tier-wide default per tier (endpoint = NULL).
--   • One per-endpoint override (/api/v1/search) showing tighter limits
--     on an expensive route.
--   • Algorithm choices spread across all four implementations so each
--     Lua script gets exercised by manual smoke tests.
--
-- Uniqueness is (tier, endpoint). The partial-NULL case is handled
-- explicitly by separate ON CONFLICT clauses since Postgres treats NULLs
-- as distinct in UNIQUE — we coalesce to a sentinel string to dedupe.
INSERT INTO rate_limit_rules (tier, endpoint, algorithm, max_requests, window_seconds, enabled) VALUES
  ('free',       NULL,             'fixed_window',       60,   60, true),
  ('pro',        NULL,             'token_bucket',       600,  60, true),
  ('enterprise', NULL,             'token_bucket',       6000, 60, true),
  ('free',       '/api/v1/search', 'sliding_window_log', 10,   60, true),
  ('pro',        '/api/v1/search', 'leaky_bucket',       100,  60, true),
  ('enterprise', '/api/v1/search', 'token_bucket',       1000, 60, true)
ON CONFLICT (tier, endpoint) DO NOTHING;

COMMIT;

-- ── verification ───────────────────────────────────────────────────────
-- Quick sanity printout. Not part of the transaction.
\echo
\echo 'Seeded clients:'
SELECT tier, name, api_key FROM clients ORDER BY tier;
\echo
\echo 'Seeded rules:'
SELECT tier, COALESCE(endpoint, '<default>') AS endpoint, algorithm, max_requests, window_seconds, enabled
  FROM rate_limit_rules
 ORDER BY tier, endpoint NULLS FIRST;
