"""End-to-end test: run the scraper on a single parent and print a summary."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.scraper import run_full_scrape


async def main() -> None:
    parent = sys.argv[1] if len(sys.argv) > 1 else "perya"
    items = await run_full_scrape(parent_filter=[parent])

    print(f"\n=== {parent}: {len(items)} items ===")

    # Group by child category
    by_child: dict[str, list[dict]] = {}
    for item in items:
        cats = item["categories"]
        child = cats[1]["label"] if len(cats) > 1 else "?"
        by_child.setdefault(child, []).append(item)

    for child, rows in by_child.items():
        print(f"\n  [{child}] — {len(rows)} games")
        for r in rows[:3]:
            print(f"    • {r['name']:<30} provider={r['provider']:<8} game_id={r['game_id']}")
        if len(rows) > 3:
            print(f"    ... ({len(rows)-3} more)")

    # Show full first item
    if items:
        print("\nFull payload of first item:")
        print(json.dumps(items[0], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
