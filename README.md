# Reverse Web Scraper API

A FastAPI-based reverse scraper that crawls Next.js sites (JS-rendered via Playwright), stores structured content in PostgreSQL, and exposes it via a clean JWT-protected REST API.

> **WordPress integration is intentionally excluded.** Consume this API from your own WP plugin via `wp_remote_get()`.

---

## Architecture

```
Target Next.js Site
       │
   Playwright (headless Chromium)
       │
   Scraper Service
       │
   PostgreSQL (scraped_items)
       │
   FastAPI REST API  ←── Your WordPress plugin
```

---

## Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI |
| Browser Engine | Playwright (Chromium, headless) |
| Database | PostgreSQL (async SQLAlchemy 2.0) |
| Migrations | Alembic |
| Auth | JWT (python-jose + bcrypt) |
| Scheduler | APScheduler |
| Rate Limiting | slowapi |

---

## Quick Start

### 1. Configure environment

```bash
cp .env.example .env
# Fill in DATABASE_URL, SECRET_KEY, TARGET_URL
```

### 2. Configure scraper schema

Edit `scraper_schema.json` to match your target Next.js site:

```json
{
  "list_url": "https://target-site.com/articles",
  "list_item_selector": "article.card",
  "detail_url_selector": "a.read-more",
  "fields": [
    { "name": "title",      "selector": "h1.title",  "type": "text" },
    { "name": "content",    "selector": "div.body",   "type": "html" },
    { "name": "excerpt",    "selector": "p.summary",  "type": "text" },
    { "name": "image_url",  "selector": "img.hero",   "type": "attribute", "attribute": "src" },
    { "name": "source_url", "selector": null,          "type": "current_url" }
  ],
  "pagination": {
    "enabled": true,
    "next_selector": "a.next",
    "max_pages": 10
  }
}
```

**Field types:**

| Type | Description |
|---|---|
| `text` | Inner text of element |
| `html` | Raw innerHTML |
| `attribute` | HTML attribute (set `"attribute": "src"` etc.) |
| `multi_text` | Array of inner text for all matched elements |
| `current_url` | The page's URL (no selector needed) |

### 3a. Run with Docker (recommended)

```bash
docker compose up --build
```

### 3b. Run locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

alembic upgrade head
python scripts/create_admin.py --username admin --password yourpassword
uvicorn app.main:app --reload
```

---

## API Reference

Interactive docs: `http://localhost:8000/docs`

### Auth

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/token` | Login, returns JWT |
| `POST` | `/auth/register` | Register a new user |

### Items

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/items/` | List scraped items (paginated + searchable) |
| `GET` | `/items/{id}` | Get single item with full `raw_data` |
| `DELETE` | `/items/{id}` | Delete an item |

**Query params for `GET /items/`:**
- `page`, `page_size` — pagination (default: 1, 20)
- `search=keyword` — searches title and excerpt

**Example response:**
```json
{
  "total": 42,
  "page": 1,
  "page_size": 20,
  "items": [
    {
      "id": 1,
      "title": "Article Title",
      "excerpt": "Short description...",
      "source_url": "https://target-site.com/articles/some-post",
      "raw_data": {
        "title": "Article Title",
        "content": "<p>Full HTML content...</p>",
        "image_url": "https://cdn.target-site.com/hero.jpg",
        "source_url": "https://target-site.com/articles/some-post"
      },
      "scraped_at": "2025-01-01T06:00:00",
      "updated_at": "2025-01-01T06:00:00"
    }
  ]
}
```

### Scraper Control

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/scraper/trigger` | Manually trigger a scrape now |
| `GET` | `/scraper/jobs` | View scheduled job + next run time |

All endpoints except `/auth/token` and `/health` require:
```
Authorization: Bearer <your_jwt_token>
```

---

## Scheduler

| Job | Default | Description |
|---|---|---|
| `scrape_job` | Every 6 hours | Scrape target site → upsert into DB |

Change in `.env`:
```
SCRAPE_CRON=0 */6 * * *
```

Items are **deduplicated by `source_url`** — re-scraping updates in place, never duplicates.

---

## Consuming from WordPress

In your WP plugin:

```php
$token = get_option('scraper_api_token');

$response = wp_remote_get('https://your-scraper-api.com/items/?page=1&page_size=50', [
    'headers' => [
        'Authorization' => 'Bearer ' . $token,
    ],
]);

$data = json_decode(wp_remote_retrieve_body($response), true);

foreach ($data['items'] as $item) {
    $raw = $item['raw_data'];
    // Use $raw['title'], $raw['content'], $raw['source_url'], etc.
}
```

---

## Project Structure

```
scraper-api/
├── app/
│   ├── core/
│   │   ├── config.py        # Settings from .env
│   │   ├── database.py      # Async SQLAlchemy engine
│   │   └── security.py      # JWT utilities
│   ├── models/
│   │   ├── user.py          # User model
│   │   └── scraped_item.py  # ScrapedItem model
│   ├── routers/
│   │   ├── auth.py          # /auth endpoints
│   │   ├── items.py         # /items endpoints
│   │   └── scraper.py       # /scraper endpoints
│   ├── services/
│   │   ├── scraper.py       # Playwright scraping logic
│   │   └── scheduler.py     # APScheduler scrape job
│   └── main.py              # FastAPI app entry
├── alembic/                 # DB migrations
├── scripts/
│   └── create_admin.py      # First-run admin setup
├── scraper_schema.json      # ← Configure your scraper here
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
