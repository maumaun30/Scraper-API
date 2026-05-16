"""Smoke test: fetch the funalomax catalog and print a summary."""
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.scraper import run_full_scrape


async def main() -> None:
    items = await run_full_scrape()

    print(f"\n=== {len(items)} items ===")

    providers = Counter(i["raw_data"]["provider"] for i in items)
    genres = Counter(i["raw_data"]["genre"] for i in items)
    types = Counter(i["raw_data"]["type"] for i in items)

    print("\nproviders:", dict(providers.most_common()))
    print("genres:   ", dict(genres.most_common()))
    print("types:    ", dict(types.most_common()))

    if items:
        print("\nFirst item:")
        print(json.dumps(items[0], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
