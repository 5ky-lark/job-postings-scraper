"""Job Posting Scraper — Entry Point.

Scrapes software developer jobs from 4 Philippine job boards (Kalibrr,
Indeed, JobStreet, LinkedIn) and sends new listings to Discord via webhook.

Usage:
    python main.py              # Start the scheduler (runs every N hours)
    python main.py --once       # Run a single scrape cycle and exit
    python main.py --test       # Send a test message to Discord and exit

Environment variables are loaded from a ``.env`` file in the project root.
See ``.env.example`` for available options.
"""

import argparse
import asyncio
import signal
import sys
from collections import Counter

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
from db import init_db, save_jobs, get_job_count
from discord_sender import DiscordSender
from scrapers import (
    KalibrrScraper,
    IndeedScraper,
    JobStreetScraper,
    LinkedInScraper,
)
from utils import setup_logging


logger = setup_logging(config.LOG_LEVEL)


# -----------------------------------------------------------------------
# Core scrape cycle
# -----------------------------------------------------------------------


async def run_scrape_cycle() -> None:
    """Execute one full scraping cycle across all sources.

    1. Scrape all 4 job sites concurrently.
    2. Deduplicate via the SQLite database.
    3. Send new jobs to Discord.
    """
    logger.info("=" * 60)
    logger.info("Starting scrape cycle...")
    logger.info("=" * 60)

    # Validate webhook URL
    if not config.DISCORD_WEBHOOK_URL or config.DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/YOUR"):
        logger.error(
            "DISCORD_WEBHOOK_URL is not configured! "
            "Please set it in your .env file."
        )
        return

    # Initialize scrapers
    scrapers = [
        KalibrrScraper(proxy=config.PROXY_URL),
        IndeedScraper(proxy=config.PROXY_URL),
        JobStreetScraper(proxy=config.PROXY_URL),
        LinkedInScraper(proxy=config.PROXY_URL),
    ]

    # Run all scrapers — we run them sequentially to avoid overwhelming
    # the system with 4 concurrent browser instances, but each scraper
    # handles its own keyword iteration internally.
    all_jobs: list[dict] = []

    for scraper in scrapers:
        logger.info(f"--- Scraping {scraper.name.upper()} ---")
        try:
            jobs = await scraper.scrape()
            job_dicts = [j.to_dict() for j in jobs]
            all_jobs.extend(job_dicts)
            logger.info(
                f"{scraper.name.upper()} returned {len(jobs)} jobs"
            )
        except Exception:
            logger.exception(
                f"Scraper {scraper.name.upper()} failed — skipping"
            )

    logger.info(f"Total raw jobs collected: {len(all_jobs)}")

    if not all_jobs:
        logger.info("No jobs found this cycle. Nothing to send.")
        return

    # Deduplicate against SQLite — only returns truly new jobs
    new_jobs = save_jobs(all_jobs)
    logger.info(
        f"New jobs after dedup: {len(new_jobs)} "
        f"(DB total: {get_job_count()})"
    )

    if not new_jobs:
        logger.info("All jobs were already seen. Nothing new to send.")
        return

    # Log breakdown by source
    source_counts = Counter(j.get("source", "unknown") for j in new_jobs)
    for source, count in source_counts.most_common():
        logger.info(f"  {source}: {count} new")

    # Send to Discord
    sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
    try:
        await sender.send_jobs(new_jobs)
        logger.info(
            f"Successfully sent {len(new_jobs)} new jobs to Discord!"
        )
    except Exception:
        logger.exception("Failed to send jobs to Discord")

    logger.info("Scrape cycle complete.")
    logger.info("=" * 60)


# -----------------------------------------------------------------------
# CLI entry points
# -----------------------------------------------------------------------


async def run_once() -> None:
    """Run a single scrape cycle and exit."""
    init_db()
    await run_scrape_cycle()


async def send_test() -> None:
    """Send a test message to verify the Discord webhook."""
    if not config.DISCORD_WEBHOOK_URL or config.DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/YOUR"):
        logger.error(
            "DISCORD_WEBHOOK_URL is not configured! "
            "Please set it in your .env file."
        )
        return

    sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
    await sender.send_test_message()
    logger.info("Test message sent — check your Discord channel!")


_scrape_lock = asyncio.Lock()


async def run_single_source_scrape(source_name: str) -> None:
    """Execute a scrape cycle for a single source with lock protection."""
    async with _scrape_lock:
        logger.info(f"Realtime: Starting scrape for {source_name.upper()}...")
        # Validate webhook URL
        if not config.DISCORD_WEBHOOK_URL or config.DISCORD_WEBHOOK_URL.startswith("https://discord.com/api/webhooks/YOUR"):
            logger.error(
                "DISCORD_WEBHOOK_URL is not configured! "
                "Please set it in your .env file."
            )
            return

        # Initialize specific scraper
        scraper_cls = None
        if source_name == "kalibrr":
            from scrapers.kalibrr import KalibrrScraper
            scraper_cls = KalibrrScraper
        elif source_name == "indeed":
            from scrapers.indeed import IndeedScraper
            scraper_cls = IndeedScraper
        elif source_name == "jobstreet":
            from scrapers.jobstreet import JobStreetScraper
            scraper_cls = JobStreetScraper
        elif source_name == "linkedin":
            from scrapers.linkedin import LinkedInScraper
            scraper_cls = LinkedInScraper

        if not scraper_cls:
            logger.error(f"Unknown source name: {source_name}")
            return

        try:
            scraper = scraper_cls(proxy=config.PROXY_URL)
            jobs = await scraper.scrape()
            job_dicts = [j.to_dict() for j in jobs]
            if job_dicts:
                new_jobs = save_jobs(job_dicts)
                logger.info(
                    f"Realtime: {source_name.upper()} returned {len(jobs)} jobs. "
                    f"New after dedup: {len(new_jobs)} "
                    f"(DB total: {get_job_count()})"
                )
                if new_jobs:
                    # Log breakdown
                    logger.info(f"  {source_name}: {len(new_jobs)} new")
                    # Send to Discord
                    sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
                    await sender.send_jobs(new_jobs)
                    logger.info(f"Successfully sent {len(new_jobs)} new jobs to Discord!")
            else:
                logger.info(f"Realtime: {source_name.upper()} returned 0 jobs.")
        except Exception:
            logger.exception(f"Realtime: Scraper {source_name.upper()} failed")


async def run_scheduler() -> None:
    """Start the APScheduler loop that runs scrape cycles on an interval."""
    init_db()
    logger.info(f"Job Scraper started in mode: {config.SCRAPE_MODE}")
    logger.info(
        f"Keywords: {len(config.SEARCH_KEYWORDS)} | "
        f"Locations: {config.LOCATIONS}"
    )
    logger.info(f"Database: {config.DB_PATH} ({get_job_count()} jobs stored)")

    scheduler = AsyncIOScheduler()

    if config.SCRAPE_MODE == "realtime":
        logger.info("Scheduling individual scrapers with staggered realtime loops:")
        from datetime import datetime, timedelta

        for source, interval in config.SOURCE_INTERVALS.items():
            logger.info(f"  - {source}: every {interval} minutes")
            
            # Stagger startup
            offset_seconds = 0
            if source == "indeed":
                offset_seconds = 30
            elif source == "jobstreet":
                offset_seconds = 60
            elif source == "linkedin":
                offset_seconds = 90
                
            start_date = datetime.now() + timedelta(seconds=offset_seconds)

            scheduler.add_job(
                run_single_source_scrape,
                trigger=IntervalTrigger(minutes=interval, start_date=start_date),
                args=[source],
                id=f"scrape_{source}",
                name=f"Job Scrape {source.capitalize()}",
                max_instances=1,
                replace_existing=True,
            )
    else:
        # Run once immediately on startup
        await run_scrape_cycle()

        # Then schedule recurring runs
        scheduler.add_job(
            run_scrape_cycle,
            trigger=IntervalTrigger(hours=config.CHECK_INTERVAL_HOURS),
            id="scrape_cycle",
            name="Job Scrape Cycle",
            max_instances=1,
            replace_existing=True,
        )

    scheduler.start()
    logger.info("Scheduler running. Press Ctrl+C to stop.")

    # Keep the event loop alive
    stop_event = asyncio.Event()

    def _signal_handler(*_: object) -> None:
        logger.info("Shutdown signal received — stopping scheduler...")
        scheduler.shutdown(wait=False)
        stop_event.set()

    # Register signal handlers for graceful shutdown
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)
    else:
        # On Windows, signal handlers work differently
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — shutting down.")
        scheduler.shutdown(wait=False)

    logger.info("Job Scraper stopped. Goodbye!")


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and dispatch to the appropriate coroutine."""
    parser = argparse.ArgumentParser(
        description="Job Posting Scraper — fetch software developer jobs "
                    "and send to Discord.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scrape cycle and exit.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Send a test message to Discord and exit.",
    )
    args = parser.parse_args()

    if args.test:
        asyncio.run(send_test())
    elif args.once:
        asyncio.run(run_once())
    else:
        asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
