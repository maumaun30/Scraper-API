import json
import asyncio
import logging
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright, Page, ElementHandle
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://www.solaireonline.com"


def load_schema() -> dict:
    schema_path = Path(settings.scraper_field_schema)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path) as f:
        return json.load(f)


async def extract_field_from_element(element: ElementHandle, field: dict) -> Any:
    """Extract a single field's value from a list item ElementHandle."""
    field_type = field.get("type", "text")
    selector = field.get("selector")

    try:
        if field_type == "exists":
            child = await element.query_selector(selector)
            return child is not None

        if not selector:
            return None

        child = await element.query_selector(selector)
        if not child:
            return None

        if field_type == "text":
            return (await child.inner_text()).strip()

        elif field_type == "html":
            return await child.inner_html()

        elif field_type == "attribute":
            attr = field.get("attribute", "href")
            value = await child.get_attribute(attr)
            # Resolve relative URLs
            if value and value.startswith("/"):
                value = f"{BASE_URL}{value}"
            return value

        elif field_type == "multi_text":
            children = await element.query_selector_all(selector)
            return [(await c.inner_text()).strip() for c in children]

        else:
            return (await child.inner_text()).strip()

    except Exception as e:
        logger.warning(f"Failed to extract field '{field['name']}': {e}")
        return None


async def load_all_items_via_button(page: Page, schema: dict) -> None:
    """
    Click the 'Load More' button repeatedly until it disappears or max_clicks is reached.
    Waits for new items to render after each click.
    """
    pagination = schema.get("pagination", {})
    if pagination.get("type") != "load_more_button":
        return

    button_selector = pagination.get("button_selector")
    max_clicks = pagination.get("max_clicks", 20)
    wait_ms = pagination.get("wait_after_click_ms", 2000)

    for click_num in range(max_clicks):
        try:
            btn = await page.query_selector(button_selector)
            if not btn:
                logger.info(f"Load More button gone after {click_num} clicks — all items loaded")
                break

            is_visible = await btn.is_visible()
            is_enabled = await btn.is_enabled()
            if not is_visible or not is_enabled:
                logger.info(f"Load More button disabled/hidden after {click_num} clicks")
                break

            # Count items before click
            before_count = len(await page.query_selector_all(schema["list_item_selector"]))

            await btn.scroll_into_view_if_needed()
            await btn.click()
            logger.info(f"Clicked Load More ({click_num + 1}/{max_clicks})")

            # Wait for new items to appear
            await asyncio.sleep(wait_ms / 1000)

            # Verify new items actually loaded
            after_count = len(await page.query_selector_all(schema["list_item_selector"]))
            if after_count == before_count:
                logger.info("No new items after click — stopping pagination")
                break

            logger.info(f"Items: {before_count} → {after_count}")

        except Exception as e:
            logger.warning(f"Load More click {click_num + 1} failed: {e}")
            break


async def scrape_list_page(list_url: str, schema: dict) -> list[dict]:
    """
    Scrape a single listing page:
    1. Load the page and wait for hydration
    2. Click Load More until all items are visible
    3. Extract fields from each list item element directly
    """
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        try:
            logger.info(f"Navigating to {list_url}")
            await page.goto(list_url, wait_until="networkidle", timeout=45000)

            # Wait for at least one game card to appear
            await page.wait_for_selector(
                schema["list_item_selector"], timeout=15000
            )

            # Give Next.js hydration a moment
            await asyncio.sleep(2)

            # Determine category from URL slug
            category = list_url.rstrip("/").split("/")[-1]

            # Expand all items via Load More button
            await load_all_items_via_button(page, schema)

            # Extract fields from each item in the DOM
            items = await page.query_selector_all(schema["list_item_selector"])
            logger.info(f"Extracting from {len(items)} items on {list_url}")

            for item_el in items:
                item_data: dict[str, Any] = {"category": category, "source_url": list_url}

                for field in schema.get("fields", []):
                    item_data[field["name"]] = await extract_field_from_element(item_el, field)

                # Build a stable unique key: title + category (no detail page URL available)
                title = item_data.get("title", "")
                if title:
                    slug = title.lower().replace(" ", "-").replace("&", "and")
                    item_data["item_key"] = f"{category}/{slug}"
                    results.append(item_data)

        except Exception as e:
            logger.error(f"Error scraping {list_url}: {e}")
        finally:
            await context.close()
            await browser.close()

    return results


async def run_full_scrape() -> list[dict]:
    """
    Full scrape pipeline across all list_urls defined in the schema.
    Returns deduplicated list of all scraped items.
    """
    schema = load_schema()

    # Support both legacy single "list_url" and new "list_urls" array
    list_urls: list[str] = schema.get("list_urls") or []
    if not list_urls and schema.get("list_url"):
        list_urls = [schema["list_url"]]

    if not list_urls:
        raise ValueError("Schema must define 'list_urls' (array) or 'list_url' (string)")

    all_items: list[dict] = []
    seen_keys: set[str] = set()

    # Scrape categories sequentially to avoid hammering the server
    for url in list_urls:
        logger.info(f"Scraping category: {url}")
        try:
            items = await scrape_list_page(url, schema)
            for item in items:
                key = item.get("item_key") or item.get("title", "")
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    all_items.append(item)
            logger.info(f"Got {len(items)} items from {url} ({len(all_items)} total so far)")
        except Exception as e:
            logger.error(f"Failed to scrape {url}: {e}")
            continue

    logger.info(f"Full scrape complete — {len(all_items)} unique items")
    return all_items
