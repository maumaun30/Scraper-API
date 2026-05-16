# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Docker (preferred)
docker compose up --build

# Local dev
pip install -r requirements.txt
alembic upgrade head
python scripts/create_admin.py --username admin --password <pw>
uvicorn app.main:app --reload

# Migrations
alembic revision --autogenerate -m "message"
alembic upgrade head

# Smoke-test the scraper without touching the DB
python scripts/test_scrape.py
```

No pytest suite. `scripts/test_scrape.py` is a manual probe, not a test.

## Architecture

FastAPI service that pulls the funalomax game catalog on a cron schedule, stores it in Postgres, and serves it via JWT-protected REST endpoints.

**Lifecycle (`app/main.py`):** `lifespan` calls `init_db()` (which `create_all`s registered models — Alembic is also wired up but `create_all` runs on every startup) and then `start_scheduler()`, which registers the `scrape_job` APScheduler cron job inside the same event loop as FastAPI. The scheduler is in-process; there is no separate worker.

**Scrape flow (`app/services/scraper.py` → `scheduler.py`):**
1. `run_full_scrape()` makes one `POST https://funalomax.com/api/gsi/v1/games` with an empty body. No auth, no browser. Returns ~1500 records.
2. `to_item()` normalizes each upstream record into `{title, excerpt, content, source_url, raw_data}`. `title` comes from `descriptions["en"]` (with fallbacks). `excerpt` is a `provider · genre · type` string. `content` is `None` (the upstream payload has no body content). The full normalized record — including all locales, all image variants, and `properties` — goes in `raw_data`.
3. `source_url` is **synthetic**: `https://funalomax.com/games/{provider}/{id}`. The upstream payload has no public per-game URL; this synthetic form is the UNIQUE upsert key in `scraped_items`. Don't change it without rethinking dedup.
4. `job_scrape_and_store()` (in `scheduler.py`) upserts each item by `source_url`: existing rows get `title/content/excerpt/raw_data` overwritten, new rows are inserted.

**Image-key quirk:** the upstream image dict uses suffix `En` for English locales and `Cn` for Chinese locales (not the locale string itself). `_image_suffix()` in `scraper.py` handles this; preserve that mapping if you add more locales.

**Database URL normalization (`app/core/config.py`):** `Settings.normalize_database_url` is a `field_validator` that converts Neon/psycopg2-style URLs to asyncpg form: swaps scheme to `postgresql+asyncpg://`, maps `sslmode=` → `ssl=`, drops `channel_binding`/`connect_timeout`/`application_name` (asyncpg rejects them). Any change to `database_url` parsing must preserve Neon compatibility.

**Auth:** JWT (HS256) via `app/core/security.py`. All routers except `/auth/token`, `/`, `/health` require `Authorization: Bearer <token>`. `scripts/create_admin.py` seeds the first user.

**Rate limiting:** `slowapi` with a single global default (`settings.rate_limit`, e.g. `30/minute`) keyed on remote IP.

## Configuration

Settings are read from `.env` via pydantic-settings. Required: `database_url`, `secret_key`. Optional: `scrape_cron` (default `0 */6 * * *`), `rate_limit`, `access_token_expire_minutes`.

`docker-compose.yml` runs a local Postgres on host port **5433** (container 5432) with creds `postgres/root` and DB `scraper_db`; the API container mounts the repo at `/app`.

## History

Earlier versions used Playwright + headless Chromium to walk funalomax category pages and parse HTML cards (`scraper_schema.json`, stealth context, disclaimer-modal dismissal). That whole path has been replaced by the JSON API call — if you see references to `playwright`, `scraper_schema.json`, or `make_stealth_context` in old branches or docs, they're obsolete.
