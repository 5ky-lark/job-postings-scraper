"""Discord Bot for Job Posting Scraper.

A Discord bot with commands to trigger job scraping on demand, check stats,
and manage the automated scheduler.

Usage:
    python bot.py

Commands:
    !fetch           — Instantly scrape all 4 job sites and post results
    !fetch kalibrr   — Scrape only Kalibrr
    !fetch indeed    — Scrape only Indeed
    !fetch jobstreet — Scrape only JobStreet
    !fetch linkedin  — Scrape only LinkedIn
    !stats           — Show job database statistics
    !sources         — Show all configured sources and their status
    !keywords        — Show the search keywords being used
    !clear           — Clear the job database (admin only)
    !help_jobs       — Show all available commands

Environment variables (set in .env):
    DISCORD_BOT_TOKEN   — Your Discord bot token
    DISCORD_WEBHOOK_URL — Webhook URL for scheduled notifications
"""

import asyncio
import logging
from collections import Counter
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands, tasks

import config
from db import init_db, save_jobs, get_job_count, get_recent_jobs
from discord_sender import DiscordSender
from scrapers import (
    KalibrrScraper,
    IndeedScraper,
    JobStreetScraper,
    LinkedInScraper,
    Job,
)
from utils import setup_logging

logger = setup_logging(config.LOG_LEVEL)

# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None,  # We define our own
    activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="for dev jobs 👀",
    ),
)

# Track whether a scrape is currently running (prevent double-runs)
_scrape_lock = asyncio.Lock()

# Source emoji mapping
SOURCE_EMOJI = {
    "kalibrr": "🟣",
    "indeed": "🟢",
    "jobstreet": "🟠",
    "linkedin": "🔵",
}

SCRAPER_MAP = {
    "kalibrr": KalibrrScraper,
    "indeed": IndeedScraper,
    "jobstreet": JobStreetScraper,
    "linkedin": LinkedInScraper,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_job_embed(job: dict) -> discord.Embed:
    """Build a rich Discord embed for a single job listing."""
    source = job.get("source", "unknown").lower()
    color_map = {
        "kalibrr": 0x7C3AED,
        "indeed": 0x2557A7,
        "jobstreet": 0xE44D26,
        "linkedin": 0x0077B5,
    }
    color = color_map.get(source, 0x95A5A6)
    emoji = SOURCE_EMOJI.get(source, "📋")

    title = job.get("title", "Untitled Position")
    url = job.get("url", "")

    company = job.get("company", "N/A") or "N/A"
    location = job.get("location", "N/A") or "N/A"
    salary = job.get("salary", "") or "Not specified"
    date_posted = job.get("date_posted", "") or "Recently"

    description = (
        f"🏢 **Company:** {company}\n"
        f"📍 **Location:** {location}\n"
        f"💰 **Salary:** {salary}\n"
        f"📅 **Posted:** {date_posted}\n"
        f"{emoji} **Source:** {source.capitalize()}\n\n"
        f"🔗 **[Apply / View Listing]({url})**"
    )

    embed = discord.Embed(
        title=title,
        url=url if url else None,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Job Scraper • {source.capitalize()}")

    return embed


def _build_summary_embed(
    new_count: int,
    source_counts: dict[str, int],
    elapsed: float,
    total_scraped: int,
) -> discord.Embed:
    """Build a summary embed with scrape results."""
    if new_count > 0:
        embed = discord.Embed(
            title=f"🔍 Found {new_count} new job{'s' if new_count != 1 else ''}!",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc),
        )
    else:
        embed = discord.Embed(
            title="🔍 Scrape Complete — No New Jobs",
            description="All jobs found were already in the database.",
            color=0xF39C12,
            timestamp=datetime.now(timezone.utc),
        )

    # Source breakdown
    if source_counts:
        lines = []
        for src, count in sorted(
            source_counts.items(), key=lambda kv: kv[1], reverse=True
        ):
            emoji = SOURCE_EMOJI.get(src, "📋")
            lines.append(f"{emoji} **{src.capitalize()}**: {count}")
        embed.add_field(
            name="📊 Breakdown",
            value="\n".join(lines),
            inline=True,
        )

    embed.add_field(
        name="📈 Stats",
        value=(
            f"Total scraped: {total_scraped}\n"
            f"New (unique): {new_count}\n"
            f"Time: {elapsed:.1f}s"
        ),
        inline=True,
    )

    embed.add_field(
        name="🗄️ Database",
        value=f"{get_job_count()} total jobs stored",
        inline=True,
    )

    embed.set_footer(text="Job Scraper")
    return embed


async def _run_scrapers(
    sources: list[str] | None = None,
) -> tuple[list[dict], list[dict], float]:
    """Run scrapers and return (all_jobs, new_jobs, elapsed_seconds).

    Args:
        sources: Optional list of source names to scrape. If None, scrape all.

    Returns:
        Tuple of (all scraped jobs, new jobs after dedup, elapsed seconds).
    """
    start = asyncio.get_event_loop().time()

    if sources is None:
        sources = ["kalibrr", "indeed", "jobstreet", "linkedin"]

    all_jobs: list[dict] = []

    for source_name in sources:
        scraper_cls = SCRAPER_MAP.get(source_name)
        if not scraper_cls:
            logger.warning(f"Unknown source: {source_name}")
            continue

        logger.info(f"--- Scraping {source_name.upper()} ---")
        try:
            scraper = scraper_cls(proxy=config.PROXY_URL)
            jobs = await scraper.scrape()
            job_dicts = [j.to_dict() for j in jobs]
            all_jobs.extend(job_dicts)
            logger.info(f"{source_name.upper()} returned {len(jobs)} jobs")
        except Exception:
            logger.exception(f"Scraper {source_name.upper()} failed")

    # Dedup against database
    new_jobs = save_jobs(all_jobs) if all_jobs else []

    elapsed = asyncio.get_event_loop().time() - start
    return all_jobs, new_jobs, elapsed


# ---------------------------------------------------------------------------
# Bot events
# ---------------------------------------------------------------------------


@bot.event
async def on_ready() -> None:
    """Called when the bot connects to Discord."""
    logger.info(f"Bot connected as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Guilds: {[g.name for g in bot.guilds]}")
    init_db()
    logger.info("Database initialized.")

    if config.SCRAPE_MODE == "realtime":
        logger.info("Realtime scraping mode active. Starting staggered loops...")
        if not scrape_kalibrr_task.is_running():
            scrape_kalibrr_task.start()
        if not scrape_indeed_task.is_running():
            scrape_indeed_task.start()
        if not scrape_jobstreet_task.is_running():
            scrape_jobstreet_task.start()
        if not scrape_linkedin_task.is_running():
            scrape_linkedin_task.start()
    else:
        # Start the scheduled scrape loop
        if not scheduled_scrape.is_running():
            scheduled_scrape.start()
            logger.info(
                f"Scheduled scraping started (every {config.CHECK_INTERVAL_HOURS}h)"
            )


# ---------------------------------------------------------------------------
# Scheduled task (runs every CHECK_INTERVAL_HOURS or at staggered intervals)
# ---------------------------------------------------------------------------


@tasks.loop(hours=config.CHECK_INTERVAL_HOURS)
async def scheduled_scrape() -> None:
    """Automatically scrape all sources on a schedule."""
    if _scrape_lock.locked():
        logger.info("Scheduled scrape skipped — another scrape is running.")
        return

    async with _scrape_lock:
        logger.info("Scheduled scrape starting...")
        all_jobs, new_jobs, elapsed = await _run_scrapers()

        # Send to webhook if there are new jobs
        if new_jobs and config.DISCORD_WEBHOOK_URL:
            sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
            try:
                await sender.send_jobs(new_jobs)
                logger.info(f"Sent {len(new_jobs)} jobs to webhook")
            except Exception:
                logger.exception("Failed to send to webhook")


@scheduled_scrape.before_loop
async def _before_scheduled() -> None:
    """Wait until the bot is ready before starting the loop."""
    await bot.wait_until_ready()


# Real-time individual scraping loops per source
@tasks.loop(minutes=config.KALIBRR_INTERVAL_MIN)
async def scrape_kalibrr_task() -> None:
    from db import get_last_run, set_last_run
    last_run = get_last_run("kalibrr")
    if last_run:
        elapsed = datetime.now(timezone.utc) - last_run
        # 10s buffer to prevent slight timing mismatches
        if elapsed < timedelta(minutes=config.KALIBRR_INTERVAL_MIN) - timedelta(seconds=10):
            next_run_in = timedelta(minutes=config.KALIBRR_INTERVAL_MIN) - elapsed
            logger.info(
                f"Kalibrr: Ran recently ({elapsed.total_seconds() / 60:.1f}m ago). "
                f"Next run in {next_run_in.total_seconds() / 60:.1f}m. Skipping startup run."
            )
            return

    async with _scrape_lock:
        logger.info("Realtime: Kalibrr scrape starting...")
        try:
            all_jobs, new_jobs, elapsed = await _run_scrapers(["kalibrr"])
            logger.info(f"Realtime: Kalibrr scrape finished in {elapsed:.1f}s. New jobs: {len(new_jobs)}")
            set_last_run("kalibrr", datetime.now(timezone.utc))
            if new_jobs and config.DISCORD_WEBHOOK_URL:
                sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
                await sender.send_jobs(new_jobs)
        except Exception:
            logger.exception("Realtime: Kalibrr scrape failed")


@scrape_kalibrr_task.before_loop
async def before_kalibrr() -> None:
    await bot.wait_until_ready()


@tasks.loop(minutes=config.INDEED_INTERVAL_MIN)
async def scrape_indeed_task() -> None:
    from db import get_last_run, set_last_run
    last_run = get_last_run("indeed")
    if last_run:
        elapsed = datetime.now(timezone.utc) - last_run
        if elapsed < timedelta(minutes=config.INDEED_INTERVAL_MIN) - timedelta(seconds=10):
            next_run_in = timedelta(minutes=config.INDEED_INTERVAL_MIN) - elapsed
            logger.info(
                f"Indeed: Ran recently ({elapsed.total_seconds() / 60:.1f}m ago). "
                f"Next run in {next_run_in.total_seconds() / 60:.1f}m. Skipping startup run."
            )
            return

    async with _scrape_lock:
        logger.info("Realtime: Indeed scrape starting...")
        try:
            all_jobs, new_jobs, elapsed = await _run_scrapers(["indeed"])
            logger.info(f"Realtime: Indeed scrape finished in {elapsed:.1f}s. New jobs: {len(new_jobs)}")
            set_last_run("indeed", datetime.now(timezone.utc))
            if new_jobs and config.DISCORD_WEBHOOK_URL:
                sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
                await sender.send_jobs(new_jobs)
        except Exception:
            logger.exception("Realtime: Indeed scrape failed")


@scrape_indeed_task.before_loop
async def before_indeed() -> None:
    await bot.wait_until_ready()
    # Stagger by 30 seconds
    await asyncio.sleep(30)


@tasks.loop(minutes=config.JOBSTREET_INTERVAL_MIN)
async def scrape_jobstreet_task() -> None:
    from db import get_last_run, set_last_run
    last_run = get_last_run("jobstreet")
    if last_run:
        elapsed = datetime.now(timezone.utc) - last_run
        if elapsed < timedelta(minutes=config.JOBSTREET_INTERVAL_MIN) - timedelta(seconds=10):
            next_run_in = timedelta(minutes=config.JOBSTREET_INTERVAL_MIN) - elapsed
            logger.info(
                f"Jobstreet: Ran recently ({elapsed.total_seconds() / 60:.1f}m ago). "
                f"Next run in {next_run_in.total_seconds() / 60:.1f}m. Skipping startup run."
            )
            return

    async with _scrape_lock:
        logger.info("Realtime: Jobstreet scrape starting...")
        try:
            all_jobs, new_jobs, elapsed = await _run_scrapers(["jobstreet"])
            logger.info(f"Realtime: Jobstreet scrape finished in {elapsed:.1f}s. New jobs: {len(new_jobs)}")
            set_last_run("jobstreet", datetime.now(timezone.utc))
            if new_jobs and config.DISCORD_WEBHOOK_URL:
                sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
                await sender.send_jobs(new_jobs)
        except Exception:
            logger.exception("Realtime: Jobstreet scrape failed")


@scrape_jobstreet_task.before_loop
async def before_jobstreet() -> None:
    await bot.wait_until_ready()
    # Stagger by 60 seconds
    await asyncio.sleep(60)


@tasks.loop(minutes=config.LINKEDIN_INTERVAL_MIN)
async def scrape_linkedin_task() -> None:
    from db import get_last_run, set_last_run
    last_run = get_last_run("linkedin")
    if last_run:
        elapsed = datetime.now(timezone.utc) - last_run
        if elapsed < timedelta(minutes=config.LINKEDIN_INTERVAL_MIN) - timedelta(seconds=10):
            next_run_in = timedelta(minutes=config.LINKEDIN_INTERVAL_MIN) - elapsed
            logger.info(
                f"LinkedIn: Ran recently ({elapsed.total_seconds() / 60:.1f}m ago). "
                f"Next run in {next_run_in.total_seconds() / 60:.1f}m. Skipping startup run."
            )
            return

    async with _scrape_lock:
        logger.info("Realtime: LinkedIn scrape starting...")
        try:
            all_jobs, new_jobs, elapsed = await _run_scrapers(["linkedin"])
            logger.info(f"Realtime: LinkedIn scrape finished in {elapsed:.1f}s. New jobs: {len(new_jobs)}")
            set_last_run("linkedin", datetime.now(timezone.utc))
            if new_jobs and config.DISCORD_WEBHOOK_URL:
                sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
                await sender.send_jobs(new_jobs)
        except Exception:
            logger.exception("Realtime: LinkedIn scrape failed")


@scrape_linkedin_task.before_loop
async def before_linkedin() -> None:
    await bot.wait_until_ready()
    # Stagger by 90 seconds
    await asyncio.sleep(90)


# ---------------------------------------------------------------------------
# Bot commands
# ---------------------------------------------------------------------------


@bot.command(name="fetch")
async def cmd_fetch(ctx: commands.Context, source: str | None = None) -> None:
    """Instantly scrape job sites and post results.

    Usage:
        !fetch           — Scrape all 4 sites
        !fetch kalibrr   — Scrape only Kalibrr
        !fetch indeed    — Scrape only Indeed
        !fetch jobstreet — Scrape only JobStreet
        !fetch linkedin  — Scrape only LinkedIn
    """
    # Validate source
    if source and source.lower() not in SCRAPER_MAP:
        valid = ", ".join(f"`{s}`" for s in SCRAPER_MAP)
        await ctx.send(
            f"❌ Unknown source `{source}`. Valid options: {valid}"
        )
        return

    # Prevent concurrent scrapes
    if _scrape_lock.locked():
        await ctx.send(
            "⏳ A scrape is already running! Please wait for it to finish."
        )
        return

    async with _scrape_lock:
        sources = [source.lower()] if source else None
        source_label = source.upper() if source else "ALL SITES"

        # Send "working" message
        loading_embed = discord.Embed(
            title=f"⏳ Scraping {source_label}...",
            description=(
                "This may take a few minutes. Browsers are firing up, "
                "bypassing anti-bot protections, and collecting jobs.\n\n"
                "☕ Grab a coffee while you wait!"
            ),
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc),
        )
        loading_msg = await ctx.send(embed=loading_embed)

        # Run the scrape
        try:
            all_jobs, new_jobs, elapsed = await _run_scrapers(sources)
        except Exception as e:
            error_embed = discord.Embed(
                title="❌ Scrape Failed",
                description=f"```{str(e)[:500]}```",
                color=0xE74C3C,
            )
            await loading_msg.edit(embed=error_embed)
            return

        # Build source counts from new jobs
        source_counts = Counter(j.get("source", "unknown") for j in new_jobs)

        # Edit the loading message with the summary
        summary_embed = _build_summary_embed(
            new_count=len(new_jobs),
            source_counts=dict(source_counts),
            elapsed=elapsed,
            total_scraped=len(all_jobs),
        )
        await loading_msg.edit(embed=summary_embed)

        # Send individual job embeds (max 20 to avoid spam)
        if new_jobs:
            jobs_to_show = new_jobs[:20]
            for i in range(0, len(jobs_to_show), 5):
                batch = jobs_to_show[i : i + 5]
                embeds = [_build_job_embed(job) for job in batch]
                await ctx.send(embeds=embeds)
                if i + 5 < len(jobs_to_show):
                    await asyncio.sleep(1)  # Avoid rate limits

            if len(new_jobs) > 20:
                await ctx.send(
                    f"📋 *...and {len(new_jobs) - 20} more jobs. "
                    f"Check the database for the full list.*"
                )

        # Also send to webhook if configured
        if new_jobs and config.DISCORD_WEBHOOK_URL:
            sender = DiscordSender(config.DISCORD_WEBHOOK_URL)
            try:
                await sender.send_jobs(new_jobs)
            except Exception:
                logger.exception("Failed to send to webhook")


@bot.command(name="stats")
async def cmd_stats(ctx: commands.Context) -> None:
    """Show job database statistics.

    Usage: !stats
    """
    total = get_job_count()
    recent_24h = get_recent_jobs(hours=24)
    recent_6h = get_recent_jobs(hours=6)

    # Count by source (last 24h)
    source_counts_24h = Counter(j.get("source", "unknown") for j in recent_24h)
    source_counts_6h = Counter(j.get("source", "unknown") for j in recent_6h)

    embed = discord.Embed(
        title="📊 Job Scraper Statistics",
        color=0x9B59B6,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(
        name="🗄️ Total Jobs in Database",
        value=f"**{total:,}**",
        inline=False,
    )

    # Last 6h breakdown
    if source_counts_6h:
        lines_6h = []
        for src, count in sorted(
            source_counts_6h.items(), key=lambda kv: kv[1], reverse=True
        ):
            emoji = SOURCE_EMOJI.get(src, "📋")
            lines_6h.append(f"{emoji} {src.capitalize()}: **{count}**")
        embed.add_field(
            name=f"🕐 Last 6 Hours ({len(recent_6h)} total)",
            value="\n".join(lines_6h) or "None",
            inline=True,
        )
    else:
        embed.add_field(
            name="🕐 Last 6 Hours",
            value="No new jobs",
            inline=True,
        )

    # Last 24h breakdown
    if source_counts_24h:
        lines_24h = []
        for src, count in sorted(
            source_counts_24h.items(), key=lambda kv: kv[1], reverse=True
        ):
            emoji = SOURCE_EMOJI.get(src, "📋")
            lines_24h.append(f"{emoji} {src.capitalize()}: **{count}**")
        embed.add_field(
            name=f"📅 Last 24 Hours ({len(recent_24h)} total)",
            value="\n".join(lines_24h) or "None",
            inline=True,
        )
    else:
        embed.add_field(
            name="📅 Last 24 Hours",
            value="No new jobs",
            inline=True,
        )

    # Scheduler status
    if config.SCRAPE_MODE == "realtime":
        status_lines = []
        tasks_list = [
            ("Kalibrr", scrape_kalibrr_task),
            ("Indeed", scrape_indeed_task),
            ("JobStreet", scrape_jobstreet_task),
            ("LinkedIn", scrape_linkedin_task),
        ]
        for name, task in tasks_list:
            if task.is_running():
                next_run = task.next_iteration
                if next_run:
                    timestamp = int(next_run.timestamp())
                    status_lines.append(f"✅ {name}: next <t:{timestamp}:R>")
                else:
                    status_lines.append(f"✅ {name}: running")
            else:
                status_lines.append(f"❌ {name}: stopped")
        scheduler_status = "\n".join(status_lines)
    else:
        if scheduled_scrape.is_running():
            next_run = scheduled_scrape.next_iteration
            if next_run:
                timestamp = int(next_run.timestamp())
                scheduler_status = (
                    f"✅ Scheduled (every {config.CHECK_INTERVAL_HOURS}h)\n"
                    f"Next: <t:{timestamp}:R>"
                )
            else:
                scheduler_status = f"✅ Scheduled (every {config.CHECK_INTERVAL_HOURS}h)"
        else:
            scheduler_status = "❌ Stopped"

    embed.add_field(
        name="⏰ Scheduler Mode",
        value=f"Mode: **{config.SCRAPE_MODE.upper()}**\n{scheduler_status}",
        inline=False,
    )

    embed.set_footer(text="Job Scraper")
    await ctx.send(embed=embed)


@bot.command(name="sources")
async def cmd_sources(ctx: commands.Context) -> None:
    """Show all configured job sources.

    Usage: !sources
    """
    embed = discord.Embed(
        title="🌐 Configured Job Sources",
        color=0x3498DB,
        timestamp=datetime.now(timezone.utc),
    )

    sources_info = [
        (
            "🟣 Kalibrr",
            "DynamicFetcher (JS rendering)",
            "https://www.kalibrr.com",
            "8 keywords, 3-8s delay",
        ),
        (
            "🟢 Indeed PH",
            "StealthyFetcher (Cloudflare bypass)",
            "https://ph.indeed.com",
            "8 keywords, 5-10s delay",
        ),
        (
            "🟠 JobStreet PH",
            "StealthyFetcher (SPA handling)",
            "https://www.jobstreet.com.ph",
            "8 keywords, 5-10s delay",
        ),
        (
            "🔵 LinkedIn",
            "StealthyFetcher + real_chrome",
            "https://www.linkedin.com/jobs",
            "4 keywords, 10-20s delay",
        ),
    ]

    for name, method, url, config_info in sources_info:
        embed.add_field(
            name=name,
            value=f"🔗 [{url}]({url})\n⚙️ {method}\n📋 {config_info}",
            inline=False,
        )

    embed.set_footer(text="Use !fetch <source> to scrape a specific site")
    await ctx.send(embed=embed)


@bot.command(name="keywords")
async def cmd_keywords(ctx: commands.Context) -> None:
    """Show the search keywords being used.

    Usage: !keywords
    """
    kws = config.SEARCH_KEYWORDS

    # Split into chunks of 20 for display
    chunks = [kws[i : i + 20] for i in range(0, len(kws), 20)]

    embed = discord.Embed(
        title=f"🔑 Search Keywords ({len(kws)} total)",
        color=0x1ABC9C,
        timestamp=datetime.now(timezone.utc),
    )

    for i, chunk in enumerate(chunks):
        formatted = ", ".join(f"`{kw}`" for kw in chunk)
        embed.add_field(
            name=f"Set {i + 1}",
            value=formatted[:1024],  # Discord field limit
            inline=False,
        )

    embed.add_field(
        name="📍 Locations",
        value=", ".join(f"`{loc}`" for loc in config.LOCATIONS),
        inline=False,
    )

    embed.set_footer(text="Keywords are defined in config.py")
    await ctx.send(embed=embed)


@bot.command(name="recent")
async def cmd_recent(ctx: commands.Context, hours: int = 6) -> None:
    """Show recently found jobs.

    Usage:
        !recent      — Jobs from last 6 hours
        !recent 24   — Jobs from last 24 hours
    """
    if hours < 1:
        hours = 1
    if hours > 168:  # Max 1 week
        hours = 168

    recent = get_recent_jobs(hours=hours)

    if not recent:
        embed = discord.Embed(
            title=f"📭 No jobs found in the last {hours}h",
            color=0xF39C12,
            timestamp=datetime.now(timezone.utc),
        )
        await ctx.send(embed=embed)
        return

    # Summary
    source_counts = Counter(j.get("source", "unknown") for j in recent)
    embed = discord.Embed(
        title=f"📬 {len(recent)} job{'s' if len(recent) != 1 else ''} found in the last {hours}h",
        color=0x2ECC71,
        timestamp=datetime.now(timezone.utc),
    )

    lines = []
    for src, count in sorted(
        source_counts.items(), key=lambda kv: kv[1], reverse=True
    ):
        emoji = SOURCE_EMOJI.get(src, "📋")
        lines.append(f"{emoji} **{src.capitalize()}**: {count}")
    embed.add_field(name="📊 Breakdown", value="\n".join(lines), inline=False)

    await ctx.send(embed=embed)

    # Show first 10 jobs
    jobs_to_show = recent[:10]
    embeds = [_build_job_embed(job) for job in jobs_to_show]

    for i in range(0, len(embeds), 5):
        batch = embeds[i : i + 5]
        await ctx.send(embeds=batch)
        if i + 5 < len(embeds):
            await asyncio.sleep(1)

    if len(recent) > 10:
        await ctx.send(
            f"📋 *Showing 10 of {len(recent)}. "
            f"Use `!recent {hours}` to see this timeframe again.*"
        )


@bot.command(name="clear")
@commands.has_permissions(administrator=True)
async def cmd_clear(ctx: commands.Context) -> None:
    """Clear all jobs from the database (admin only).

    Usage: !clear
    """
    import sqlite3
    from config import DB_PATH

    count = get_job_count()

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM jobs")
        conn.commit()

    embed = discord.Embed(
        title="🗑️ Database Cleared",
        description=f"Removed **{count:,}** job records.",
        color=0xE74C3C,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"Cleared by {ctx.author}")
    await ctx.send(embed=embed)


@cmd_clear.error
async def cmd_clear_error(ctx: commands.Context, error: Exception) -> None:
    """Handle permission errors for the clear command."""
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You need **Administrator** permissions to clear the database.")


@bot.command(name="help_jobs")
async def cmd_help_jobs(ctx: commands.Context) -> None:
    """Show all available bot commands.

    Usage: !help_jobs
    """
    embed = discord.Embed(
        title="🤖 Job Scraper Bot — Commands",
        description="Scrape software developer jobs from PH job boards and send them right here.",
        color=0x7C3AED,
        timestamp=datetime.now(timezone.utc),
    )

    commands_list = [
        (
            "!fetch",
            "Instantly scrape **all 4** job sites and post new jobs here.\n"
            "Use `!fetch kalibrr`, `!fetch indeed`, `!fetch jobstreet`, "
            "or `!fetch linkedin` to scrape a specific site.",
        ),
        ("!stats", "Show database statistics and scheduler status."),
        ("!sources", "Show all configured job sources and their methods."),
        ("!keywords", "Show the 59 search keywords being used."),
        (
            "!recent [hours]",
            "Show recently found jobs. Default: last 6 hours.\n"
            "Example: `!recent 24` for last 24 hours.",
        ),
        ("!clear", "🔒 Clear the job database (admin only)."),
        ("!help_jobs", "Show this help message."),
    ]

    for name, desc in commands_list:
        embed.add_field(name=f"`{name}`", value=desc, inline=False)

    if config.SCRAPE_MODE == "realtime":
        scheduler_desc = (
            "The bot automatically scrapes each site continuously at staggered intervals:\n"
            f"- **Kalibrr**: every {config.KALIBRR_INTERVAL_MIN}m\n"
            f"- **Indeed**: every {config.INDEED_INTERVAL_MIN}m\n"
            f"- **JobStreet**: every {config.JOBSTREET_INTERVAL_MIN}m\n"
            f"- **LinkedIn**: every {config.LINKEDIN_INTERVAL_MIN}m"
        )
    else:
        scheduler_desc = (
            f"The bot automatically scrapes every **{config.CHECK_INTERVAL_HOURS} hours** "
            "and sends new jobs to the configured webhook."
        )

    embed.add_field(
        name="⏰ Automatic Scheduling",
        value=scheduler_desc,
        inline=False,
    )

    embed.set_footer(text="Job Scraper Bot")
    await ctx.send(embed=embed)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the Discord bot."""
    token = config.DISCORD_BOT_TOKEN

    if not token:
        logger.error(
            "DISCORD_BOT_TOKEN is not configured!\n"
            "Please set it in your .env file.\n"
            "Get a token from: https://discord.com/developers/applications"
        )
        return

    logger.info("Starting Discord bot...")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
