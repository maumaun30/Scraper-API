"""Look at DOM changes after clicking a game card — login modal? new element? """
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        await page.goto("https://funalomax.com/en/perya", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)

        # Dismiss disclaimer
        proceed = await page.query_selector("div[role='dialog'] button:has-text('Proceed')")
        if proceed:
            await proceed.click()
            await asyncio.sleep(1)

        # Snapshot: all dialogs before click
        before = await page.query_selector_all("div[role='dialog']")
        print(f"dialogs before click: {len(before)}")

        # Click on the first real game card (Game Shows section)
        card = await page.query_selector(
            "section div.grid button.active-scale-98"
        )
        img = await card.query_selector("img[alt]") if card else None
        alt = await img.get_attribute("alt") if img else "?"
        print(f"clicking: {alt!r}")
        await card.click()
        await asyncio.sleep(3)

        after = await page.query_selector_all("div[role='dialog']")
        print(f"dialogs after click: {len(after)}")
        for idx, d in enumerate(after):
            text = (await d.inner_text())[:300]
            print(f"  dialog[{idx}]: {text!r}")

        # Check if an iframe appeared
        iframes = page.frames
        print(f"frames: {[f.url for f in iframes]}")

        # Check for any new link/anchor in the DOM
        print(f"page url: {page.url}")

        # Check for common login modal text
        login_btn = await page.query_selector("button:has-text('Login'), button:has-text('Sign In')")
        if login_btn:
            print(f"login button visible: {(await login_btn.inner_text()).strip()!r}")

        # Capture any href/data-href in game button's DOM at the React-router level
        # by inspecting __NEXT_DATA__ or similar
        next_data = await page.query_selector("script#__NEXT_DATA__")
        if next_data:
            raw = await next_data.inner_text()
            print(f"__NEXT_DATA__ size: {len(raw)} bytes — searching for 'Bingo Funalo'")
            if "Bingo Funalo" in raw:
                idx = raw.find("Bingo Funalo")
                print(f"  context: {raw[max(0,idx-200):idx+500]!r}")
            if "GameID" in raw:
                import re as _re
                matches = _re.findall(r'"[^"]*gameI[Dd][^"]*"\s*:\s*"[^"]+"', raw)[:5]
                for m in matches:
                    print(f"  game-id match: {m}")
                matches2 = _re.findall(r'"(?:play|launch|game)[Uu]rl"\s*:\s*"[^"]+"', raw)[:5]
                for m in matches2:
                    print(f"  url match: {m}")
                # Broader: any key containing 'url' near a game
                name_idx = raw.find('"name":"Perya Super Color Game"')
                if name_idx > 0:
                    print(f"  context around first game: {raw[max(0,name_idx-100):name_idx+600]!r}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
