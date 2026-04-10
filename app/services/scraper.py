import json
import asyncio
import logging
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright, Page, ElementHandle, BrowserContext
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

BASE_URL = "https://www.solaireonline.com"

# Realistic browser fingerprint to avoid bot detection
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


def load_schema() -> dict:
    schema_path = Path(settings.scraper_field_schema)
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path) as f:
        return json.load(f)


async def make_stealth_context(browser) -> BrowserContext:
    """Create a browser context that looks like a real user."""
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 900},
        locale="en-US",
        timezone_id="Asia/Manila",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    )
    # Hide webdriver flag — key for bot detection bypass
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    """)
    return context


async def wait_for_cards(page: Page, selector: str, timeout: int = 45000) -> bool:
    """
    Wait for game cards with multiple fallback strategies.
    Returns True if cards found, False if timed out.
    """
    try:
        # Strategy 1: wait for selector directly
        await page.wait_for_selector(selector, timeout=timeout)
        return True
    except Exception:
        pass

    # Strategy 2: wait for networkidle + check manually
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(3)
        el = await page.query_selector(selector)
        if el:
            return True
    except Exception:
        pass

    # Strategy 3: poll every 2s for up to 30s
    for _ in range(15):
        await asyncio.sleep(2)
        el = await page.query_selector(selector)
        if el:
            logger.info("Cards found via polling fallback")
            return True

    return False


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
    """Click Load More button repeatedly until gone or max_clicks reached."""
    pagination = schema.get("pagination", {})
    if pagination.get("type") != "load_more_button":
        return

    button_selector = pagination.get("button_selector")
    max_clicks = pagination.get("max_clicks", 20)
    wait_ms = pagination.get("wait_after_click_ms", 2500)

    for click_num in range(max_clicks):
        try:
            btn = await page.query_selector(button_selector)
            if not btn:
                logger.info(f"Load More gone after {click_num} clicks")
                break

            if not await btn.is_visible() or not await btn.is_enabled():
                logger.info(f"Load More disabled after {click_num} clicks")
                break

            before_count = len(await page.query_selector_all(schema["list_item_selector"]))
            await btn.scroll_into_view_if_needed()
            await btn.click()
            logger.info(f"Clicked Load More ({click_num + 1}/{max_clicks})")

            await asyncio.sleep(wait_ms / 1000)

            after_count = len(await page.query_selector_all(schema["list_item_selector"]))
            if after_count == before_count:
                logger.info("No new items after click — stopping")
                break

            logger.info(f"Items: {before_count} → {after_count}")

        except Exception as e:
            logger.warning(f"Load More click {click_num + 1} failed: {e}")
            break


async def scrape_list_page(list_url: str, schema: dict) -> list[dict]:
    """Scrape a single listing page — load, expand, extract."""
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=BROWSER_ARGS,
        )
        context = await make_stealth_context(browser)
        page = await context.new_page()

        try:
            logger.info(f"Navigating to {list_url}")

            # Go to page, don't wait for networkidle (can hang on SPAs)
            await page.goto(list_url, wait_until="domcontentloaded", timeout=60000)

            # Small pause for JS to start executing
            await asyncio.sleep(3)

            # Wait for game cards with generous timeout + fallbacks
            found = await wait_for_cards(page, schema["list_item_selector"], timeout=45000)

            if not found:
                # Log page source snippet for debugging
                content = await page.content()
                snippet = content[:500] if content else "(empty)"
                logger.error(
                    f"Cards never appeared on {list_url}. "
                    f"Page title: {await page.title()}. "
                    f"HTML snippet: {snippet}"
                )
                return []

            # Extra settle time after cards appear
            await asyncio.sleep(2)

            category = list_url.rstrip("/").split("/")[-1]

            # Expand via Load More
            await load_all_items_via_button(page, schema)

            items = await page.query_selector_all(schema["list_item_selector"])
            logger.info(f"Extracting from {len(items)} items on {list_url}")

            for item_el in items:
                item_data: dict[str, Any] = {"category": category, "source_url": list_url}

                for field in schema.get("fields", []):
                    item_data[field["name"]] = await extract_field_from_element(item_el, field)

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
    """Full scrape across all list_urls in schema."""
    schema = load_schema()

    list_urls: list[str] = schema.get("list_urls") or []
    if not list_urls and schema.get("list_url"):
        list_urls = [schema["list_url"]]

    if not list_urls:
        raise ValueError("Schema must define 'list_urls' or 'list_url'")

    all_items: list[dict] = []
    seen_keys: set[str] = set()

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
