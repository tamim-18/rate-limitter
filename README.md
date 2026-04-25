# Rate Limiter

Distributed rate limiter service (FastAPI, Redis + Lua, PostgreSQL, ARQ, RabbitMQ).

Full specification: [`src/requirements.md`](src/requirements.md).

## Quick start

1. Install [uv](https://github.com/astral-sh/uv) and Python 3.12.
2. `uv lock && uv sync`
3. `cp .env.example .env`
4. `docker compose up --build`

API: `http://localhost:8000/health`

## Development

- Application package: `src/rate_limiter/`
- Local install: `uv sync` (includes dev dependency group if configured)
