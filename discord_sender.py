"""Discord webhook sender with rich embeds for job notifications.

Sends batches of job listings as colour-coded embeds with a leading summary
embed that shows the per-source breakdown.  Respects Discord's 10-embed-per-
message limit and handles 429 rate-limit responses gracefully.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from config import SOURCE_COLORS, SOURCE_ICONS
from utils import truncate

logger = logging.getLogger("job_scraper.discord")

_MAX_EMBEDS_PER_MESSAGE: int = 10
"""Discord allows at most 10 embeds in a single webhook POST."""


class DiscordSender:
    """Sends job notifications to a Discord channel via webhook.

    Args:
        webhook_url: The full Discord webhook URL.
    """

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url: str = webhook_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send_jobs(self, jobs: list[dict[str, Any]]) -> None:
        """Send a collection of job listings as Discord embeds.

        A summary embed is sent first, followed by the individual job
        embeds batched in groups of up to 10.

        Args:
            jobs: A list of job dicts.  Each dict should contain at least
                  ``title``, ``url``, ``source``, and ideally ``company``,
                  ``location``, ``salary``, ``date_posted``, and
                  ``first_seen``.
        """
        if not jobs:
            logger.info("No jobs to send — skipping Discord notification.")
            return

        # Tally per-source counts for the summary embed.
        sources: dict[str, int] = {}
        for job in jobs:
            src = job.get("source", "unknown").lower()
            sources[src] = sources.get(src, 0) + 1

        # 1. Send summary embed.
        summary_embed = self._build_summary_embed(len(jobs), sources)
        await self._post_embeds([summary_embed])

        # 2. Send job embeds in batches of 10.
        embeds = [self._build_embed(job) for job in jobs]
        for i in range(0, len(embeds), _MAX_EMBEDS_PER_MESSAGE):
            batch = embeds[i : i + _MAX_EMBEDS_PER_MESSAGE]
            await self._post_embeds(batch)

    async def send_test_message(self) -> None:
        """Send a test embed to verify the webhook URL is valid.

        The embed is bright green with a simple confirmation message.
        """
        embed: dict[str, Any] = {
            "title": "✅ Job Scraper Connected!",
            "description": (
                "The Discord webhook is working correctly.\n"
                "Job notifications will appear here."
            ),
            "color": 0x00FF00,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Job Scraper • Test Message"},
        }
        await self._post_embeds([embed])
        logger.info("Test message sent successfully.")

    # ------------------------------------------------------------------
    # Embed builders
    # ------------------------------------------------------------------

    def _build_embed(self, job: dict[str, Any]) -> dict[str, Any]:
        """Build a single Discord embed dict for a job listing.

        Args:
            job: A job dict with standard keys.

        Returns:
            A dict representing a Discord embed object.
        """
        source: str = job.get("source", "unknown").lower()
        icon: str = SOURCE_ICONS.get(source, "📋")
        color: int = SOURCE_COLORS.get(source, 0x95A5A6)

        title_text = job.get("title", "Untitled Position")
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
            f"{icon} **Source:** {source.capitalize()}\n\n"
            f"🔗 **[Apply / View Listing]({url})**"
        )

        embed: dict[str, Any] = {
            "title": truncate(title_text, 256),
            "url": url,
            "description": description,
            "color": color,
            "footer": {"text": f"Job Scraper • {source.capitalize()}"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return embed

    def _build_summary_embed(
        self, new_count: int, sources: dict[str, int]
    ) -> dict[str, Any]:
        """Build a summary embed showing the per-source breakdown.

        Args:
            new_count: Total number of new jobs found.
            sources: A mapping of source name → count.

        Returns:
            A dict representing a Discord embed object.
        """
        lines: list[str] = []
        for src, count in sorted(sources.items(), key=lambda kv: kv[1], reverse=True):
            icon = SOURCE_ICONS.get(src, "📋")
            lines.append(f"{icon} **{src.capitalize()}**: {count} job{'s' if count != 1 else ''}")

        description = "\n".join(lines) if lines else "No breakdown available."

        embed: dict[str, Any] = {
            "title": f"🔍 Found {new_count} new job{'s' if new_count != 1 else ''}!",
            "description": description,
            "color": 0x2ECC71,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Job Scraper • Summary"},
        }
        return embed

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _post_embeds(self, embeds: list[dict[str, Any]]) -> None:
        """POST a list of embeds to the Discord webhook.

        Handles HTTP-429 (rate-limited) responses by reading the
        ``Retry-After`` header and sleeping before retrying once.

        Args:
            embeds: A list of Discord embed dicts (max 10).
        """
        payload: dict[str, Any] = {"embeds": embeds}

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(3):
                try:
                    response = await client.post(
                        self.webhook_url, json=payload
                    )

                    if response.status_code in (200, 204):
                        logger.debug(
                            "Webhook POST succeeded (status %s, %d embed(s)).",
                            response.status_code,
                            len(embeds),
                        )
                        return

                    if response.status_code == 429:
                        retry_after = float(
                            response.headers.get("Retry-After", "5")
                        )
                        logger.warning(
                            "Rate-limited by Discord. Retrying after %.1f s (attempt %d/3).",
                            retry_after,
                            attempt + 1,
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    # Non-retryable HTTP error.
                    logger.error(
                        "Discord webhook returned HTTP %s: %s",
                        response.status_code,
                        response.text[:300],
                    )
                    return

                except httpx.HTTPError as exc:
                    logger.error(
                        "HTTP error posting to Discord (attempt %d/3): %s",
                        attempt + 1,
                        exc,
                    )
                    if attempt < 2:
                        await asyncio.sleep(2.0)

        logger.error("Failed to post embeds after 3 attempts.")
