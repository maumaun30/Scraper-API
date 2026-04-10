import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.scraped_item import ScrapedItem
from app.services.scraper import run_full_scrape

logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler()


async def job_scrape_and_store():
    """Scrape target site and upsert results into the DB."""
    logger.info("⏰ Scrape job started")
    try:
        items = await run_full_scrape()
        logger.info(f"Scraped {len(items)} items")
    except Exception as e:
        logger.error(f"Scrape job failed: {e}")
        return

    async with AsyncSessionLocal() as db:
        for item_data in items:
            source_url = item_data.get("source_url")
            if not source_url:
                continue

            result = await db.execute(
                select(ScrapedItem).where(ScrapedItem.source_url == source_url)
            )
            existing = result.scalar_one_or_none()

            if existing:
                existing.title = item_data.get("title", existing.title)
                existing.content = item_data.get("content", existing.content)
                existing.excerpt = item_data.get("excerpt", existing.excerpt)
                existing.raw_data = item_data
            else:
                db.add(ScrapedItem(
                    title=item_data.get("title"),
                    content=item_data.get("content"),
                    excerpt=item_data.get("excerpt"),
                    source_url=source_url,
                    raw_data=item_data,
                ))

        await db.commit()
    logger.info("✅ Scrape job complete")


def start_scheduler():
    """Register and start the scrape job."""
    def parse_cron(cron_str: str) -> CronTrigger:
        parts = cron_str.split()
        return CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

    scheduler.add_job(
        job_scrape_and_store,
        trigger=parse_cron(settings.scrape_cron),
        id="scrape_job",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info(f"Scheduler started | scrape: {settings.scrape_cron}")
