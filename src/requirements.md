# Rate Limiter — Project Reference Document

## 1. Project Goal

Build a **production-style distributed rate limiter** from scratch, implementing the core concepts from Chapter 4 of Alex Xu's _System Design Interview_ book. This is a hands-on learning project designed to go on GitHub as a portfolio piece.

The rate limiter sits as middleware in front of API endpoints, tracks request counts per client using Redis, enforces configurable limits using pluggable algorithms, and handles the distributed systems edge cases — race conditions, synchronization, and async event processing.

By the end, anyone can clone the repo, run `docker compose up`, and have a fully working multi-service rate limiter stack running locally. The project also deploys to AWS via CI/CD on every merge to `main`.

## 2. What We're Building

A standalone rate limiter service with these capabilities:

- **Four pluggable rate limiting algorithms** — Token Bucket, Fixed Window Counter, Sliding Window Log, Leaky Bucket — each implemented as an atomic Redis Lua script, switchable via configuration without code changes.
- **FastAPI middleware** — intercepts every HTTP request, extracts the client identifier (API key, IP address, or JWT subject), checks Redis for the current count, and either forwards the request or returns HTTP 429 with `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `Retry-After` headers.
- **Admin API** — REST endpoints to CRUD rate limit rules (tier, limit, window, algorithm) and manage API clients.
- **Postgres-backed rule storage** — rate limit rules, client metadata, and violation audit logs persist in PostgreSQL.
- **Redis as the hot data store** — holds live counters (one key per client per window) and a cached copy of rate limit rules so the middleware never touches Postgres on the request path.
- **ARQ background worker** — syncs rules from Postgres to Redis when rules change, logs violations asynchronously, and runs cron jobs for cleanup.
- **RabbitMQ event bus** — when a request gets rate-limited, the middleware publishes an event. Consumers can send alerts, update dashboards, or enqueue requests for deferred processing.
- **Docker Compose orchestration** — 5 services on a single bridge network, all bootable with one command.
- **CI/CD pipeline** — GitHub Actions for lint + test on PR, build + deploy to AWS ECS on merge to main.
- **AWS deployment** — ECS Fargate for containers, ElastiCache for Redis, RDS for Postgres, Amazon MQ for RabbitMQ.

## 3. Architecture Overview

### Request Flow (Happy Path)

```
Client
  │
  │  HTTP request
  ▼
┌─────────────────────────────────────────┐
│           FastAPI Middleware             │
│  1. Extract client ID (API key/IP/JWT)  │
│  2. Load rule from Redis cache          │
│  3. Execute Lua script (atomic check)   │
│  4. Lua returns: ALLOW or DENY          │
└───────────┬──────────────┬──────────────┘
            │              │
      ┌─────▼─────┐  ┌────▼──────────────────────┐
      │  ALLOW    │  │  DENY                      │
      │  Pass to  │  │  Option 1: Enqueue to      │
      │  API      │  │  RabbitMQ (deferred)        │
      │  routes   │  │  Option 2: Return HTTP 429  │
      └───────────┘  │  with Retry-After header    │
                     └────────────────────────────┘
```

### Data Flow (Configuration Plane)

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│  PostgreSQL  │────────▶│  ARQ Worker  │────────▶│    Redis     │
│              │  read   │              │  push   │              │
│  Rules       │  rules  │  Sync task   │  rules  │  Rules cache │
│  Clients     │         │  Audit task  │         │  Counters    │
│  Violations  │◀────────│  Cleanup     │         │  ARQ broker  │
│              │  write  │              │         │              │
└──────────────┘  logs   └──────┬───────┘         └──────────────┘
                                │
                                │ consume
                                ▼
                        ┌──────────────┐
                        │  RabbitMQ    │
                        │  Event bus   │
                        └──────────────┘
```

### Key Design Decisions

- **Lua scripts for atomicity**: Each algorithm runs as a single Lua script inside Redis. Since Redis is single-threaded and Lua scripts execute atomically, there are no race conditions — no distributed locks needed, no Redlock, no deadlock risk.
- **Control plane / data plane separation**: Postgres holds the source of truth (rules, audit); Redis holds the hot data (counters, cached rules). The ARQ worker bridges them. The middleware only ever touches Redis on the request path.
- **RabbitMQ off the hot path**: The message broker handles async side-effects (alerts, deferred processing, audit logging) — never the core rate limiting decision.

## 4. Tech Stack

| Layer            | Technology                                          | Why                                                                |
| ---------------- | --------------------------------------------------- | ------------------------------------------------------------------ |
| Language         | Python 3.12                                         | Async-native, good ecosystem for web + data                        |
| Package Manager  | **uv**                                              | 10x faster than pip, deterministic lockfile, modern Python tooling |
| Web Framework    | FastAPI + Uvicorn                                   | Async, middleware support, dependency injection, auto OpenAPI docs |
| Database         | PostgreSQL 16 + SQLAlchemy 2.0                      | Async ORM, proven relational store for config + audit              |
| Migrations       | Alembic                                             | SQLAlchemy-native, async support, autogenerate                     |
| Cache / Broker   | Redis 7                                             | Atomic Lua scripts, sub-ms latency, also serves as ARQ task broker |
| Message Queue    | RabbitMQ 3                                          | Robust AMQP broker, management UI, dead letter queues              |
| Background Jobs  | ARQ                                                 | Redis-backed, async-native, cron support, lightweight              |
| Config           | pydantic-settings                                   | Env var parsing + validation in one place                          |
| Logging          | structlog                                           | JSON in production, pretty console in dev                          |
| Linting          | Ruff                                                | Replaces flake8 + isort + black, extremely fast                    |
| Type Checking    | MyPy (strict)                                       | Catches bugs before runtime                                        |
| Testing          | pytest + pytest-asyncio                             | Async test support, fixtures, coverage                             |
| Load Testing     | Locust                                              | Python-based, real-time web UI, scriptable                         |
| Containerization | Docker + Docker Compose                             | Multi-service orchestration, reproducible environments             |
| CI/CD            | GitHub Actions                                      | Native to GitHub, service containers for Redis + Postgres          |
| Cloud            | AWS (ECS Fargate, ElastiCache, RDS, Amazon MQ, ALB) | Managed services, no EC2 to maintain                               |
| IaC              | Terraform                                           | Declarative, version-controlled infrastructure                     |

## 5. Coding Standards & Design Patterns

This project is built following industry best practices and established software design principles throughout. The codebase should serve as a reference for how to structure a production Python service — not just "it works," but "it's built right."

### SOLID Principles

- **Single Responsibility (SRP)**: Every module owns exactly one concern. `config.py` handles configuration. `connection.py` handles connection lifecycle. Each algorithm file implements one algorithm. The middleware only decides allow/deny — it doesn't log violations or publish events directly.
- **Open/Closed (OCP)**: The algorithm system is open for extension, closed for modification. Adding a fifth algorithm means creating one new Python file + one new Lua script and registering it in the factory — zero changes to the middleware, config, or any existing algorithm.
- **Liskov Substitution (LSP)**: All algorithm implementations inherit from `BaseAlgorithm` and are fully interchangeable. The middleware calls `algorithm.check_rate_limit(key, rule)` and gets back a `Decision` — it never knows or cares which algorithm is running.
- **Interface Segregation (ISP)**: Dependencies are injected as narrow interfaces. Route handlers receive `redis.Redis` or `AsyncSession`, not a god-object that wraps everything. The health endpoint doesn't depend on the algorithm layer. The worker doesn't depend on the middleware.
- **Dependency Inversion (DIP)**: High-level modules (middleware, services) depend on abstractions (base algorithm class, session factory), not on concrete implementations. FastAPI's `Depends()` system wires everything together at runtime, not at import time.

### DRY (Don't Repeat Yourself)

- Common model fields (id, created_at, updated_at) are defined once in a `TimestampMixin` and reused across all models.
- Connection initialization/teardown follows the same pattern for Redis and RabbitMQ — `init_*()` / `close_*()` / `get_*()` — defined once per service.
- The Dockerfile is shared between `api` and `worker` — same image, different entrypoint command. No duplicated build logic.
- Environment variable handling is centralized in `config.py` with pydantic-settings — no `os.getenv()` scattered across the codebase.

### Additional Design Patterns

- **Factory Pattern**: `algorithms/__init__.py` provides a factory function that takes an `AlgorithmType` enum and returns the correct algorithm instance. The middleware never instantiates algorithms directly.
- **Strategy Pattern**: The four algorithms are interchangeable strategies behind a common interface. Which strategy runs is determined by the rule configuration stored in Postgres, not hardcoded in the middleware.
- **Repository Pattern**: The service layer (`services/`) encapsulates all database access. Route handlers call service methods, never execute raw queries. This makes the data access layer testable and swappable.
- **Pub/Sub Pattern**: The middleware publishes rate-limit events to RabbitMQ without knowing who consumes them. Consumers (violation logger, alerter) subscribe independently — adding a new consumer doesn't touch the publisher.
- **Dependency Injection**: FastAPI's `Depends()` system injects Redis connections, database sessions, and RabbitMQ connections into route handlers and middleware. No global imports, no hidden state, fully testable with mock injection.
- **App Factory Pattern**: `create_app()` in `main.py` builds and configures the FastAPI instance. This makes it easy to create differently-configured instances for testing vs production.

### Code Quality Standards

- **Type hints everywhere**: All function signatures, return types, and variables are typed. MyPy runs in `strict` mode — no `Any` escapes, no untyped definitions.
- **Async-first**: All I/O operations (Redis, Postgres, RabbitMQ) use async/await. No blocking calls on the event loop.
- **Structured logging**: Every log entry is a structured event with key-value context (not string interpolation). JSON in production for machine parsing, pretty console in dev for readability.
- **Error handling**: Database sessions auto-rollback on exception. Connection managers fail loudly on startup (not silently mid-request). Health checks catch and report errors per-service without crashing.
- **Security**: Containers run as non-root. Secrets live in `.env` (gitignored). No credentials in code or Docker images. Production disables docs endpoints.
- **Idempotent migrations**: Alembic migrations are forward-only, autogenerated from model changes, and tested in CI before reaching production.
- **Consistent naming**: snake_case for Python, kebab-case for Docker services, UPPER_SNAKE for env vars. Modules named by what they do, not what pattern they implement.
- **Separation of concerns across layers**: Routes (API) → Services (business logic) → Models (data) → DB (persistence). Each layer only talks to the one directly below it.

## 6. Docker Setup

### Services (docker-compose.yml)

| Service    | Image                        | Role                                | Ports       | Volume      |
| ---------- | ---------------------------- | ----------------------------------- | ----------- | ----------- |
| `api`      | Custom (Dockerfile)          | FastAPI app + middleware            | 8000        | bind: ./src |
| `worker`   | Custom (same Dockerfile)     | ARQ background worker               | —           | bind: ./src |
| `redis`    | redis:7-alpine               | Counters + rules cache + ARQ broker | 6379        | redis-data  |
| `postgres` | postgres:16-alpine           | Rules + clients + audit log         | 5432        | pg-data     |
| `rabbitmq` | rabbitmq:3-management-alpine | Event bus + management UI           | 5672, 15672 | rabbit-data |

All services run on a shared bridge network (`rate-limiter-net`) and resolve each other by service name.

### Dockerfile Strategy

Multi-stage build using the official uv image:

- **Stage 1 (builder)**: `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` — installs deps from lockfile via `uv sync --frozen`, copies source, installs project.
- **Stage 2 (runtime)**: `python:3.12-slim-bookworm` — copies only the `.venv` from builder, adds `curl` and `libpq5` for health checks and asyncpg. Runs as non-root user `app`.

The `api` and `worker` services share the same image but use different `command` entries in docker-compose.

### Dev Overrides (docker-compose.override.yml)

Loaded automatically by `docker compose`. Adds:

- `--reload` for hot code reloading on file changes
- Bind mounts (`./src:/app/src`) so edits are reflected instantly
- Debug-level logging
- Uses the `builder` stage target so `uv` is available in the container

### Health Checks and Startup Order

Both `api` and `worker` use `depends_on` with `condition: service_healthy`:

| Service  | Health Check Command                           | Why                                    |
| -------- | ---------------------------------------------- | -------------------------------------- |
| redis    | `redis-cli ping`                               | Verify Redis accepts connections       |
| postgres | `pg_isready -U postgres`                       | Verify Postgres accepts connections    |
| rabbitmq | `rabbitmq-diagnostics check_port_connectivity` | Verify AMQP port is ready (takes ~30s) |
| api      | `curl -f http://localhost:8000/health`         | App-level check, verifies all backends |

### Environment Variables

All env vars are defined in `.env` (copied from `.env.example`). The compose file references them via `${VARIABLE}` syntax. Key variables:

- `POSTGRES_DB`, `POSTGRES_PASSWORD` — database name and password
- `RABBITMQ_PASSWORD` — RabbitMQ password
- `DATABASE_URL` — full async connection string (constructed in compose from above vars)
- `REDIS_URL` — Redis connection string
- `RABBITMQ_URL` — AMQP connection string
- `DEFAULT_ALGORITHM` — which algorithm to use by default (token_bucket, fixed_window, etc.)
- `DEFAULT_RATE_LIMIT` — default requests per window
- `DEFAULT_WINDOW_SECONDS` — default window size

## 7. uv (Package Manager)

We use **uv** instead of pip/poetry/pipenv. Key files:

- `pyproject.toml` — all dependencies (runtime + dev), tool configs (ruff, pytest, mypy), build system (hatchling)
- `uv.lock` — deterministic lockfile, **committed to git**
- `.python-version` — tells uv which Python to use (3.12)

### Common Commands

```bash
uv sync                    # Install all deps (runtime + dev) from lockfile
uv sync --frozen           # Install exactly from lockfile (CI/Docker)
uv add <package>           # Add a runtime dependency
uv add --dev <package>     # Add a dev dependency
uv run <command>           # Run a command in the venv (e.g., uv run pytest)
uv lock                    # Regenerate lockfile after pyproject.toml changes
```

### In Docker

The builder stage uses `uv sync --frozen --no-dev` to install only production deps. The `--frozen` flag ensures the lockfile is used exactly — no resolution happens at build time, making builds fast and deterministic.

## 8. Project Structure

```
rate-limiter/
│
├── pyproject.toml                      # uv project config, all deps, tool settings
├── uv.lock                             # Lockfile (committed)
├── .python-version                     # 3.12
│
├── Dockerfile                          # Multi-stage: builder (uv) → runtime (slim)
├── docker-compose.yml                  # 5 services: api, worker, redis, postgres, rabbitmq
├── docker-compose.override.yml         # Dev overrides: hot reload, bind mounts
├── .env.example                        # Template for env vars
├── .dockerignore                       # Keep images lean
├── .gitignore                          # Standard Python + Terraform + Docker ignores
├── Makefile                            # Shortcuts: make up, make test, make migrate
├── README.md                           # Quick start + architecture summary
│
├── src/
│   └── rate_limiter/
│       ├── __init__.py
│       ├── main.py                     # FastAPI app factory, lifespan, middleware registration
│       ├── config.py                   # pydantic-settings: env parsing + validation
│       ├── dependencies.py             # DI providers: get_redis, get_db, get_rabbit
│       ├── logging.py                  # structlog setup: JSON (prod) / console (dev)
│       │
│       ├── middleware/
│       │   ├── rate_limit.py           # Core middleware: extract key → check → pass/reject
│       │   └── identifier.py           # Client ID extraction: API key, IP, JWT
│       │
│       ├── algorithms/
│       │   ├── __init__.py             # AlgorithmType enum + factory function
│       │   ├── base.py                 # Abstract base: check_rate_limit(key, rule) → Decision
│       │   ├── token_bucket.py         # Redis hash + Lua refill logic
│       │   ├── fixed_window.py         # INCR + EXPIRE
│       │   ├── sliding_window_log.py   # Sorted set + ZREMRANGEBYSCORE
│       │   └── leaky_bucket.py         # Queue-based constant drain
│       │
│       ├── lua/                        # Raw .lua scripts loaded at startup
│       │   ├── token_bucket.lua
│       │   ├── fixed_window.lua
│       │   ├── sliding_window_log.lua
│       │   └── leaky_bucket.lua
│       │
│       ├── models/                     # SQLAlchemy ORM models
│       │   ├── base.py                 # DeclarativeBase + common mixins (timestamps, ID)
│       │   ├── rule.py                 # RateLimitRule: tier, limit, window, algorithm
│       │   ├── client.py              # Client: api_key, tier, metadata
│       │   └── violation.py           # ViolationLog: timestamp, client, endpoint, rule
│       │
│       ├── schemas/                    # Pydantic request/response models
│       │   ├── __init__.py            # HealthResponse, ServiceHealth
│       │   ├── rule.py
│       │   └── client.py
│       │
│       ├── api/                        # FastAPI routers
│       │   ├── health.py              # GET /health — pings redis, postgres, rabbitmq
│       │   ├── rules.py               # CRUD for rate limit rules (admin)
│       │   ├── clients.py             # CRUD for API clients (admin)
│       │   └── demo.py                # Dummy endpoints to test rate limiting
│       │
│       ├── services/                   # Business logic layer
│       │   ├── rule_service.py        # CRUD + trigger rule sync to Redis
│       │   ├── client_service.py
│       │   └── violation_service.py   # Log violations async
│       │
│       ├── worker/                     # ARQ background jobs
│       │   ├── settings.py            # ARQ WorkerSettings: redis, cron, functions
│       │   ├── tasks.py               # sync_rules_to_redis, log_violation, cleanup
│       │   └── consumers.py           # RabbitMQ event consumers
│       │
│       ├── events/                     # RabbitMQ pub/sub
│       │   ├── publisher.py           # Publish rate_limit_exceeded events
│       │   └── schemas.py             # Event payload models
│       │
│       └── db/
│           ├── __init__.py            # Async engine + session factory
│           └── connection.py          # Redis + RabbitMQ connection managers
│
├── migrations/                         # Alembic
│   ├── env.py                         # Reads DATABASE_URL from app config
│   └── versions/
│       └── 001_initial_schema.py      # Tables: rules, clients, violations
│
├── alembic.ini                         # Alembic config
│
├── tests/
│   ├── conftest.py                    # Fixtures: test Redis, test DB, test client
│   ├── docker-compose.test.yml        # Isolated Redis + Postgres for CI
│   ├── unit/
│   │   ├── test_token_bucket.py
│   │   ├── test_fixed_window.py
│   │   ├── test_sliding_window.py
│   │   └── test_leaky_bucket.py
│   ├── integration/
│   │   ├── test_middleware.py         # Full request → 200/429 flow
│   │   ├── test_rule_sync.py          # Postgres → Redis propagation
│   │   └── test_events.py            # RabbitMQ publish/consume
│   └── load/
│       └── locustfile.py              # Hammer the limiter under load
│
├── .github/
│   └── workflows/
│       ├── ci.yml                     # PR: lint (ruff + mypy) → test (pytest + services)
│       └── deploy.yml                 # Main: build → push ECR → deploy ECS
│
└── infra/
    ├── terraform/
    │   ├── main.tf                    # VPC, subnets, security groups
    │   ├── ecs.tf                     # ECS cluster, task defs, services (api + worker)
    │   ├── ecr.tf                     # Container registry
    │   ├── elasticache.tf             # Redis (ElastiCache)
    │   ├── rds.tf                     # PostgreSQL (RDS)
    │   ├── mq.tf                      # RabbitMQ (Amazon MQ)
    │   ├── alb.tf                     # Application Load Balancer
    │   ├── variables.tf
    │   ├── outputs.tf
    │   └── terraform.tfvars.example
    └── scripts/
        ├── bootstrap.sh               # First-time AWS setup
        └── seed.sql                   # Initial rules + demo client data
```

## 9. Rate Limiting Algorithms

### Token Bucket

Each client has a "bucket" with a maximum number of tokens. Each request consumes one token. Tokens refill at a steady rate. If the bucket is empty, the request is denied.

**Redis implementation**: A hash key per client with `tokens` (current count) and `last_refill` (timestamp). The Lua script calculates how many tokens to add since last refill, adds them (capped at max), then tries to consume one.

**Behavior**: Allows bursts up to bucket size, then throttles to the refill rate.

### Fixed Window Counter

Divide time into fixed windows (e.g., 1-minute intervals). Each window has a counter. If the counter exceeds the limit, deny.

**Redis implementation**: Key = `counter:{client}:{window_start_timestamp}`. Use `INCR` to increment, `EXPIRE` to auto-delete after window ends.

**Behavior**: Simple and fast, but has an edge case — a burst at the boundary of two windows can allow 2x the intended rate.

### Sliding Window Log

Track the exact timestamp of every request in a sorted set. On each new request, remove all entries older than the window, count remaining entries, and decide.

**Redis implementation**: Sorted set where each member is a unique request ID scored by timestamp. `ZREMRANGEBYSCORE` removes expired entries, `ZCARD` counts remaining.

**Behavior**: Most accurate, but uses more memory (one entry per request).

### Leaky Bucket

Requests enter a queue (the bucket) and are processed at a fixed rate (the leak). If the queue is full, new requests are denied.

**Redis implementation**: A list with `RPUSH` to add and a counter to track queue depth. A separate drain process (or Lua-based virtual drain) removes entries at the configured rate.

**Behavior**: Smooths traffic to a constant output rate. Good for APIs that need predictable throughput.

## 10. Build Phases

The project is built in 9 sequential phases. Each phase is independently verifiable before moving to the next.

| Phase | Name                   | What's Built                                                                  | Verification                                              |
| ----- | ---------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------- |
| P0    | Project scaffolding    | pyproject.toml, Dockerfile, docker-compose, .env, CI/CD, Makefile, gitignore  | Files exist, `uv sync` works                              |
| P1    | Core foundations       | App factory, config, db session, Redis/RabbitMQ connections, /health endpoint | `docker compose up` boots, `curl /health` returns 200     |
| P2    | Database layer         | SQLAlchemy models (Rule, Client, Violation), Alembic setup, initial migration | `alembic upgrade head` creates tables, seed data works    |
| P3    | Algorithms             | Abstract base, 4 algorithm implementations, Lua scripts, factory              | Unit tests pass against live Redis                        |
| P4    | Middleware (hot path)  | Rate limit middleware, client ID extractor, demo endpoints                    | Requests return 200 until limit, then 429 with headers    |
| P5    | Admin API              | CRUD for rules + clients, service layer                                       | Create/update rules via API, rate limits change           |
| P6    | Worker + events        | ARQ worker, RabbitMQ publisher/consumer, rule sync, violation logging         | Rule change in Postgres propagates to Redis automatically |
| P7    | Tests                  | Unit (algorithms), integration (middleware), load (Locust)                    | `make test` passes, CI pipeline goes green                |
| P8    | AWS infra + deployment | Terraform (VPC, ECS, ElastiCache, RDS, MQ, ALB), deploy workflow              | Push to main → live on AWS via ALB URL                    |

## 11. CI/CD Pipeline

### CI (ci.yml) — Runs on every PR and push to main

1. **Lint job**: Install uv → `uv sync --frozen` → `ruff check` → `ruff format --check` → `mypy`
2. **Test job** (depends on lint): Spin up Redis + Postgres as GitHub Actions service containers → `alembic upgrade head` → `pytest` with coverage → upload to Codecov

### Deploy (deploy.yml) — Runs on merge to main

1. Configure AWS credentials (OIDC role assumption)
2. Login to Amazon ECR
3. Build Docker image, tag with commit SHA + `latest`
4. Push to ECR
5. Render ECS task definitions for `api` and `worker` with new image
6. Deploy both services to ECS, wait for stability

## 12. AWS Infrastructure

| AWS Service | Maps To         | Purpose                                      |
| ----------- | --------------- | -------------------------------------------- |
| ECS Fargate | api + worker    | Containers without managing EC2              |
| ECR         | Docker registry | Store built images                           |
| ElastiCache | Redis           | Managed Redis, no ops overhead               |
| RDS         | PostgreSQL      | Managed Postgres with backups                |
| Amazon MQ   | RabbitMQ        | Managed AMQP broker                          |
| ALB         | Load balancer   | HTTPS termination, health check routing      |
| VPC         | Network         | Isolated network with public/private subnets |

All defined in Terraform under `infra/terraform/`. State stored in S3 with DynamoDB locking.

## 13. Makefile Commands

| Command            | What It Does                                             |
| ------------------ | -------------------------------------------------------- |
| `make up`          | `docker compose up --build -d` — start everything        |
| `make down`        | Stop all services                                        |
| `make down-v`      | Stop + remove volumes (full reset)                       |
| `make logs`        | Tail logs from all services                              |
| `make logs-api`    | Tail API logs only                                       |
| `make install`     | `uv sync` — install deps locally                         |
| `make lint`        | `ruff check` + `ruff format --check`                     |
| `make fmt`         | Auto-format + auto-fix                                   |
| `make typecheck`   | `mypy src/`                                              |
| `make test`        | Spin up test services → pytest → teardown                |
| `make test-unit`   | Unit tests only (no services needed)                     |
| `make test-load`   | Locust load test against localhost:8000                  |
| `make migrate`     | Run Alembic migrations inside the api container          |
| `make migrate-new` | Generate a new migration (`make migrate-new MSG="desc"`) |
| `make seed`        | Seed demo data into Postgres                             |
| `make clean`       | Remove **pycache**, .pytest_cache, etc.                  |

## 14. Expected Outcome

When complete, this project demonstrates:

1. **Distributed systems fundamentals** — atomic operations via Lua, control/data plane separation, async event-driven architecture
2. **Four rate limiting algorithms** — implemented, tested, and benchmarked side-by-side with pluggable switching via Strategy + Factory patterns
3. **Software engineering principles** — SOLID, DRY, separation of concerns, dependency injection, repository pattern — applied consistently across every module, not just mentioned in a README
4. **Production patterns** — health checks, structured logging, graceful shutdown, non-root containers, deterministic builds, strict typing with MyPy
5. **Full-stack ops** — Docker Compose for local dev, CI/CD for automation, Terraform for cloud infra, managed AWS services
6. **Clean, reviewable code** — typed Python, linted with Ruff, formatted consistently, tested with coverage, layered architecture (API → Service → Model → DB) that any team member can navigate

The repo should be clonable and runnable in under 2 minutes with `cp .env.example .env && docker compose up --build`.
