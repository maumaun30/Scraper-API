"""Funalomax catalog scraper.

The site exposes its full game catalog via a public JSON endpoint
(`POST /api/gsi/v1/games`). One request returns ~1500 games with provider,
genre, type, multi-locale descriptions, and image variants — strictly more
data than the old Playwright walk produced. No auth, no browser, no
selectors to maintain.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

UPSTREAM = "https://funalomax.com/api/gsi/v1/games"
SITE_ROOT = "https://funalomax.com"
DEFAULT_LOCALE = "en"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Origin": SITE_ROOT,
    "Referer": f"{SITE_ROOT}/en",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


def _image_suffix(locale: str) -> str:
    """Image keys use `En` for English locales and `Cn` for Chinese ones."""
    loc = locale.lower()
    if loc.startswith("en"):
        return "En"
    if loc.startswith("zh"):
        return "Cn"
    return locale.capitalize()


def pick_title(g: dict, locale: str = DEFAULT_LOCALE) -> str:
    desc = g.get("descriptions") or {}
    for key in (locale, DEFAULT_LOCALE, "en-soc"):
        if desc.get(key):
            return desc[key]
    if desc:
        return next(iter(desc.values()))
    props = g.get("properties") or {}
    return props.get("gameName") or props.get("baseGameName") or g.get("code") or g.get("id") or "Unknown"


def pick_image(g: dict, locale: str = DEFAULT_LOCALE) -> str | None:
    imgs = g.get("images") or {}
    if not imgs:
        return None
    suffix = _image_suffix(locale)
    for key in (f"imgVert{suffix}", f"imgWide{suffix}", f"imgRect{suffix}",
                "imgVertEn", "imgWideEn", "imgRectEn"):
        if imgs.get(key):
            return imgs[key]
    return next(iter(imgs.values()))


def to_item(g: dict) -> dict[str, Any]:
    """Normalize an upstream game record into the shape `job_scrape_and_store` expects."""
    provider = g.get("providerCode") or ""
    game_id = str(g.get("id") or "")
    genre = g.get("genre")
    gtype = g.get("type")

    title = pick_title(g)
    image = pick_image(g)

    # `source_url` is the UNIQUE upsert key. The upstream record has no public
    # per-game page, so we mint a stable synthetic URL from provider + id.
    source_url = f"{SITE_ROOT}/games/{provider}/{game_id}"

    excerpt_parts = [p for p in (provider, genre, gtype) if p]
    excerpt = " · ".join(excerpt_parts) if excerpt_parts else None

    return {
        "title": title,
        "excerpt": excerpt,
        "content": None,
        "source_url": source_url,
        "raw_data": {
            "id": game_id,
            "provider": provider,
            "genre": genre,
            "type": gtype,
            "title": title,
            "image": image,
            "weight": g.get("weight"),
            "code": g.get("code"),
            "descriptions": g.get("descriptions") or {},
            "images": g.get("images") or {},
            "properties": g.get("properties") or {},
            "categories": [c for c in (provider, genre, gtype) if c],
        },
    }


async def fetch_games_raw() -> list[dict]:
    """One POST returns the full catalog."""
    async with httpx.AsyncClient(timeout=30.0, http2=True, headers=HEADERS) as client:
        r = await client.post(UPSTREAM, json={})
        r.raise_for_status()
        payload = r.json()
    games = payload.get("data") or []
    logger.info(f"Upstream returned {len(games)} games")
    return games


async def run_full_scrape() -> list[dict]:
    """Fetch the full catalog and normalize it for DB upsert."""
    raw = await fetch_games_raw()
    items = [to_item(g) for g in raw if g.get("id")]
    logger.info(f"Normalized {len(items)} items")
    return items
