"""Probe funalomax: map structure of all 4 parent category pages,
dismiss the age-disclaimer modal, then capture the play link (URL or popup)
from a real game card click."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright, Page

PARENTS = [
    ("perya", "https://funalomax.com/en/perya"),
    ("casino", "https://funalomax.com/en/casino"),
    ("slots", "https://funalomax.com/en/slots"),
    ("e-game", "https://funalomax.com/en/e-game"),
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def dismiss_disclaimer(page: Page) -> bool:
    """Find and click a confirm/accept button in the legal dialog if present."""
    for _ in range(3):
        dialog = await page.query_selector("div[role='dialog']")
        if not dialog:
            return True
        # Try common confirm-button texts
        for selector in [
            "div[role='dialog'] button:has-text('I confirm')",
            "div[role='dialog'] button:has-text('Confirm')",
            "div[role='dialog'] button:has-text('I Agree')",
            "div[role='dialog'] button:has-text('Agree')",
            "div[role='dialog'] button:has-text('Accept')",
            "div[role='dialog'] button:has-text('Continue')",
            "div[role='dialog'] button:has-text('Enter')",
            "div[role='dialog'] button:has-text('Close')",
            "div[role='dialog'] button[type='submit']",
        ]:
            btn = await page.query_selector(selector)
            if btn and await btn.is_visible():
                try:
                    await btn.click(timeout=3000)
                    await asyncio.sleep(1)
                    if not await page.query_selector("div[role='dialog']"):
                        return True
                except Exception:
                    pass
        # List all buttons in the dialog as a fallback
        btns = await page.query_selector_all("div[role='dialog'] button")
        labels = []
        for b in btns:
            try:
                labels.append((await b.inner_text()).strip())
            except Exception:
                labels.append("?")
        print(f"  disclaimer buttons: {labels}")
        # Click the last/primary button heuristically
        if btns:
            try:
                await btns[-1].click(timeout=3000)
                await asyncio.sleep(1)
            except Exception:
                pass
    return False


async def probe_parent(page: Page, parent_id: str, url: str) -> None:
    print(f"\n========== {parent_id} — {url} ==========")
    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_load_state("networkidle", timeout=15000)
    await asyncio.sleep(2)

    await dismiss_disclaimer(page)

    # Layout A: sections with header + game grids
    sections = await page.query_selector_all("section")
    print(f"sections: {len(sections)}")
    for idx, sec in enumerate(sections):
        header = await sec.query_selector("span.text-primary.font-semibold")
        label = (await header.inner_text()).strip() if header else None
        cards = await sec.query_selector_all("div.relative.w-full.rounded-lg")
        if label or cards:
            print(f"  section[{idx}] label={label!r} cards={len(cards)}")

    # Layout B: category pills
    pills = await page.query_selector_all(
        "div.bg-layer-2-base button[data-slot='button'] span.text-primary, "
        "div.bg-layer-2-base button[data-slot='button'] span.text-tertiary"
    )
    pill_labels = []
    for p_ in pills:
        try:
            pill_labels.append((await p_.inner_text()).strip())
        except Exception:
            pass
    if pill_labels:
        print(f"category pills: {pill_labels}")

        # Also count games currently showing in the main grid
        grid_cards = await page.query_selector_all("div.grid.grid-cols-3 > div.relative.w-full.rounded-lg")
        print(f"main grid cards (with 'All' pill active): {len(grid_cards)}")


async def probe_play_link(page: Page) -> None:
    print("\n========== play-link probe ==========")
    await page.goto("https://funalomax.com/en/perya", wait_until="domcontentloaded", timeout=45000)
    await page.wait_for_load_state("networkidle", timeout=15000)
    await asyncio.sleep(2)

    await dismiss_disclaimer(page)

    # Find a real game card (skip the Recommendation banner which is aspect-ratio 351/139)
    card_btn = await page.query_selector(
        "div.grid.grid-cols-3 button.active-scale-98, "
        "section div.grid button.active-scale-98"
    )
    if not card_btn:
        # Fallback
        card_btn = await page.query_selector("button.active-scale-98")

    if not card_btn:
        print("no card button found")
        return

    img = await card_btn.query_selector("img[alt]")
    alt = await img.get_attribute("alt") if img else "?"
    print(f"clicking card for: {alt!r}")

    popup_urls: list[str] = []
    navigation_urls: list[str] = []
    request_urls: list[str] = []

    page.on("popup", lambda p_: popup_urls.append(p_.url))
    page.on("framenavigated", lambda f: navigation_urls.append(f.url))
    page.context.on("request", lambda r: request_urls.append(r.url))

    try:
        await card_btn.click(timeout=10000)
    except Exception as e:
        print(f"click failed: {e}")
        return

    await asyncio.sleep(5)

    print(f"current url: {page.url}")
    print(f"popup urls: {popup_urls}")
    print(f"navigation urls seen: {navigation_urls[:10]}")
    # Filter for likely game/play URLs
    interesting = [u for u in request_urls if any(k in u.lower() for k in ["game", "play", "launch", "session", "token", "evo"]) and "s3.funal" not in u]
    print(f"interesting requests ({len(interesting)}):")
    for u in interesting[:30]:
        print(f"  {u}")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()

        for parent_id, url in PARENTS:
            try:
                await probe_parent(page, parent_id, url)
            except Exception as e:
                print(f"[{parent_id}] error: {e}")

        await probe_play_link(page)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
