# Entity-Relationship Diagram

Source of truth for the control-plane schema. Hot path (Redis) is not modeled here — Postgres is only touched off the request path.

```mermaid
erDiagram
    CLIENTS ||--o{ VIOLATIONS : "incurs"
    RATE_LIMIT_RULES ||--o{ VIOLATIONS : "triggered"

    CLIENTS {
        uuid id PK "gen_random_uuid()"
        varchar(64) api_key UK
        varchar(255) name
        client_tier tier "free | pro | enterprise"
        jsonb extra "default '{}'"
        timestamptz created_at
        timestamptz updated_at
    }

    RATE_LIMIT_RULES {
        uuid id PK "gen_random_uuid()"
        client_tier tier
        varchar(255) endpoint "NULL = tier-wide default"
        algorithm algorithm "token_bucket | fixed_window | sliding_window_log | leaky_bucket"
        integer max_requests "CHECK > 0"
        integer window_seconds "CHECK > 0"
        boolean enabled "default true"
        timestamptz created_at
        timestamptz updated_at
    }

    VIOLATIONS {
        uuid id PK "gen_random_uuid()"
        uuid client_id FK "ON DELETE CASCADE"
        uuid rule_id FK "ON DELETE SET NULL, nullable"
        varchar(255) endpoint "denormalized"
        timestamptz occurred_at "indexed"
        jsonb request_metadata "default '{}'"
    }
```

## Notes

- **`UNIQUE(tier, endpoint)`** on `rate_limit_rules` — `endpoint = NULL` is the tier-wide fallback. Postgres treats NULLs as distinct in UNIQUE, which is what we want (only one default per tier still works because there is at most one row with `endpoint IS NULL` per tier in practice; enforce via app-side check or partial unique index if needed later).
- **Soft delete is intentionally absent** on rules — `enabled=false` is the kill switch. Keeps queries simple and lets the worker re-sync to Redis cleanly.
- **`violations.endpoint` is denormalized** so audit rows survive rule deletion. `rule_id` goes NULL on delete rather than CASCADE for the same reason.
- **Postgres ENUM types** (`client_tier`, `algorithm`) are created once. Adding a value later requires an Alembic migration with `ALTER TYPE ... ADD VALUE` — non-trivial but stable for the lifetime of the project.
- **No `relationship()` calls** in the ORM yet. Added only when something actually traverses them.
