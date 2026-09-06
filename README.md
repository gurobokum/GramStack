# GramStack

A full-stack starter for Telegram Mini Apps: a Telegram bot paired with a Mini App frontend.

Fork it, remove what you don't need, and get to your product logic - auth, payments, i18n, and background jobs are already wired up. Built for indie developers and agencies who ship Telegram bots and Mini Apps often.

## What's inside

**Bot**

- Telegram-only authentication - users are created from bot updates, no separate login
- Invite system with invite codes (optional, one setting)
- Multi-step conversations - per-user "page" state in redis with regex routing for text replies
- Admin commands and broadcast to all users, with block detection
- i18n for all bot texts (en/ru), with Pydantic models generated from YAML

**Mini App**

- Next.js 16 App Router with language-prefixed routes
- Typed API client generated from the backend's OpenAPI schema
- i18n, forms with validation, Telegram theme integration

**Payments and credits**

- Credits system paid with Telegram Stars: purchase, lock/confirm/refund lifecycle, stale lock cleanup

**Backend platform**

- Background jobs and cron tasks (arq + Redis)
- LLM integration (LangChain + Replicate)
- S3-compatible file storage (MinIO)
- Structured logging (structlog), optional Logfire and PostHog
- pytest suite, strict mypy, ruff, CI with GitHub Actions

## Monorepo structure

| Package            | What it is                                              |
| ------------------ | ------------------------------------------------------- |
| `packages/backend` | FastAPI + python-telegram-bot + arq worker (Python 3.13) |
| `packages/miniapp` | Next.js 16 Mini App frontend                            |
| `packages/sdk`     | TypeScript API client generated from OpenAPI            |

Backend stack: FastAPI, SQLAlchemy 2.0 (async), PostgreSQL, Redis, Alembic, dishka (DI), Pydantic.
Frontend stack: Next.js, Tailwind CSS + daisyUI, TanStack Query, react-hook-form + zod, i18next.

## Quick start

Prerequisites: [Node.js 24](https://github.com/nvm-sh/nvm) (`nvm use 24`), [pnpm](https://pnpm.io/installation), [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker.

1. Install dependencies

   ```bash
   pnpm install
   ```

2. Start local infrastructure (PostgreSQL, Redis, MinIO)

   ```bash
   cd packages/backend
   docker compose up -d
   ```

3. Configure the backend

   ```bash
   cp .env.example .env
   # set TGBOT_TOKEN and the other required values
   ```

4. Run database migrations

   ```bash
   uv run task migrate
   ```

5. Run the apps (each in its own terminal)

   ```bash
   uv run task dev      # backend API, from packages/backend
   uv run task worker   # background worker, from packages/backend
   pnpm miniapp:dev     # Mini App, from the repo root
   ```

## Telegram setup

1. Create a bot with [@BotFather](https://t.me/botfather)
2. Put the token into `packages/backend/.env` as `TGBOT_TOKEN`
3. For the Mini App, set its URL with BotFather and in `MINIAPP_URL`

## Development

After any backend API change, regenerate the SDK:

```bash
pnpm generate_openapi
```

Common checks (backend commands run from `packages/backend`):

```bash
uv run task lint     # ruff
uv run task mypy     # strict mypy
uv run task test     # pytest (needs docker compose up)
pnpm miniapp:lint    # ESLint
pnpm miniapp:ts      # TypeScript check
```

Pre-commit hooks (husky + lint-staged) run the relevant checks automatically for staged files.
