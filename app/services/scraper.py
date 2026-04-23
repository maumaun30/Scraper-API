import json
import asyncio
import logging
import re
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright, Page, BrowserContext
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://funalomax.com"

BROWSER_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# image URL example:
#   https://s3.funalomax.com/games/evo/rect/evo_200x200_GameIDSupercolorgame02_en-US_1776073926.png
# provider is the first path segment after /games/, game id follows "GameID"
IMAGE_URL_RE = re.compile(
    r"s3\.funalomax\.com/games/(?P<provider>[^/]+)/[^/]+/[^_]+_[^_]+_GameID(?P<game_id>[^_]+)_"
)


def load_schema() -> dict:
    schema_path = Path(settings.scraper_field_schema)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path) as f:
        return json.load(f)


async def make_stealth_context(browser) -> BrowserContext:
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        timezone_id="Asia/Manila",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        },
    )
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)
    return context


async def dismiss_disclaimer(page: Page, selector: str) -> None:
    """Age/legal disclaimer modal blocks clicks until dismissed."""
    try:
        btn = await page.wait_for_selector(selector, timeout=5000)
        if btn:
            await btn.click()
            await asyncio.sleep(1)
            logger.info("Dismissed disclaimer modal")
    except Exception:
        # No modal present — fine, keep going
        pass


def parse_image_metadata(image_url: str | None) -> dict[str, str | None]:
    """Extract provider and game id from a funalomax S3 image URL."""
    if not image_url:
        return {"provider": None, "game_id": None}
    m = IMAGE_URL_RE.search(image_url)
    if not m:
        return {"provider": None, "game_id": None}
    return {"provider": m.group("provider"), "game_id": m.group("game_id")}


def slugify(value: str) -> str:
    s = value.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_-]+", "-", s)
    return s.strip("-")


async def scrape_parent_page(page: Page, parent: dict, selectors: dict, skip_labels: list[str]) -> list[dict]:
    """Scrape one parent category page. Returns a flat list of items, each
    tagged with its hierarchical category path."""
    parent_id = parent["id"]
    parent_label = parent["label"]
    url = parent["url"]

    logger.info(f"[{parent_id}] GET {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)

    try:
        await page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass
    await asyncio.sleep(2)

    await dismiss_disclaimer(page, selectors["disclaimer_proceed_button"])

    # Wait for at least one child-category section to render
    try:
        await page.wait_for_selector(selectors["child_category_section"], timeout=30000)
    except Exception:
        logger.error(f"[{parent_id}] no child category sections rendered at {url}")
        return []

    sections = await page.query_selector_all(selectors["child_category_section"])
    logger.info(f"[{parent_id}] {len(sections)} child category sections")

    items: list[dict] = []

    for sec in sections:
        label_el = await sec.query_selector(selectors["child_category_label"])
        if not label_el:
            continue
        child_label = (await label_el.inner_text()).strip()
        if child_label in skip_labels:
            logger.info(f"[{parent_id}] skipping section: {child_label}")
            continue

        cards = await sec.query_selector_all(selectors["game_card"])
        logger.info(f"[{parent_id}] section={child_label!r} cards={len(cards)}")

        for card in cards:
            img = await card.query_selector(selectors["game_image"])
            if not img:
                continue
            name = (await img.get_attribute("alt") or "").strip()
            image_url = await img.get_attribute("src")
            if not name:
                continue

            meta = parse_image_metadata(image_url)
            child_slug = slugify(child_label)
            item_key = f"{parent_id}/{child_slug}/{slugify(name)}"

            items.append({
                "name": name,
                "featured_image": image_url,
                "play_link": url,
                "categories": [
                    {"level": 1, "id": parent_id, "label": parent_label},
                    {"level": 2, "id": child_slug, "label": child_label},
                ],
                "provider": meta["provider"],
                "game_id": meta["game_id"],
                "item_key": item_key,
                # Synthetic unique URL so the DB upsert keyed on source_url
                # treats every game as its own row.
                "source_url": f"{url}#{item_key}",
            })

    return items


async def run_full_scrape(parent_filter: list[str] | None = None) -> list[dict]:
    """Scrape all parent pages (or only those whose id is in parent_filter)
    and return a deduplicated list of items."""
    schema = load_schema()
    parents = schema["sections"]
    selectors = schema["selectors"]
    skip_labels = schema.get("skip_child_categories", [])

    if parent_filter:
        parents = [p for p in parents if p["id"] in parent_filter]

    all_items: list[dict] = []
    seen_keys: set[str] = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=BROWSER_ARGS)
        context = await make_stealth_context(browser)
        page = await context.new_page()

        try:
            for parent in parents:
                try:
                    items = await scrape_parent_page(page, parent, selectors, skip_labels)
                    new_count = 0
                    for item in items:
                        key = item["item_key"]
                        if key in seen_keys:
                            continue
                        seen_keys.add(key)
                        all_items.append(item)
                        new_count += 1
                    logger.info(
                        f"[{parent['id']}] +{new_count} new items (total so far: {len(all_items)})"
                    )
                except Exception as e:
                    logger.error(f"[{parent['id']}] failed: {e}")
                    continue
        finally:
            await context.close()
            await browser.close()

    logger.info(f"Full scrape done — {len(all_items)} unique items across {len(parents)} parents")
    return all_items
