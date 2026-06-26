"""General-purpose utility helpers for the job scraper.

Provides logging setup, async delays, text cleaning, and time formatting.
"""

import asyncio
import logging
import random
import re
from datetime import datetime, timezone


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure the root logger and return a named logger for the project.

    The format is::

        [2026-06-26 12:00:00] INFO | scraper | message text

    Args:
        level: A standard Python logging level name (e.g. ``"DEBUG"``,
               ``"INFO"``, ``"WARNING"``, ``"ERROR"``).

    Returns:
        A ``logging.Logger`` instance named ``"job_scraper"``.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="[%(asctime)s] %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

    logger = logging.getLogger("job_scraper")
    logger.setLevel(numeric_level)
    return logger


async def random_delay(min_sec: float = 2.0, max_sec: float = 6.0) -> None:
    """Asynchronously sleep for a random duration between *min_sec* and *max_sec*.

    Useful as a polite pause between HTTP requests so that scrapers don't
    hammer target servers.

    Args:
        min_sec: Minimum sleep time in seconds.
        max_sec: Maximum sleep time in seconds.
    """
    delay = random.uniform(min_sec, max_sec)
    await asyncio.sleep(delay)


def clean_text(text: str) -> str:
    """Normalise whitespace in *text*.

    * Strips leading / trailing whitespace.
    * Replaces ``\\n``, ``\\t``, and ``\\r`` with a single space.
    * Collapses runs of multiple spaces into one.

    Args:
        text: The raw string to clean.

    Returns:
        A single-line string with normalised spacing.
    """
    if not text:
        return ""

    text = text.replace("\n", " ").replace("\t", " ").replace("\r", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def truncate(text: str, max_length: int = 200) -> str:
    """Truncate *text* to at most *max_length* characters.

    If the text is longer than *max_length*, it is cut and ``'...'`` is
    appended (the total length including the ellipsis is *max_length*).

    Args:
        text: The string to truncate.
        max_length: Maximum allowed length (default 200).

    Returns:
        The original string if short enough, otherwise a truncated copy
        ending with ``'...'``.
    """
    if not text or len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def format_time_ago(dt_string: str) -> str:
    """Convert a datetime string to a human-readable exact duration elapsed.

    Supports:

    * ISO-8601 strings (``2026-06-26T10:00:00``, with or without timezone).
    * Common date formats (``2026-06-26``, ``Jun 26, 2026``,
      ``06/26/2026``).
    * Pass-through for strings that already look relative
      (e.g. ``"3 days ago"``, ``"Just now"``).

    Args:
        dt_string: A date/time string or relative label.

    Returns:
        A human-friendly relative time string such as ``"2 days 3 hrs 5 mins ago"``
        or ``"5 mins ago"``. Returns the original string unchanged when
        parsing fails or when it is already in relative form.
    """
    if not dt_string:
        return "Unknown"

    stripped = dt_string.strip()

    # If the string already looks relative, return as-is.
    relative_keywords = ("ago", "just now", "today", "yesterday", "hour", "minute", "second", "day", "week", "month")
    if any(kw in stripped.lower() for kw in relative_keywords):
        return stripped

    # Attempt to parse into a datetime object.
    dt: datetime | None = None
    formats = [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%b %d, %Y",
        "%B %d, %Y",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(stripped, fmt)
            break
        except ValueError:
            continue

    if dt is None:
        return stripped  # Unparseable — return as-is.

    # Ensure timezone-aware for comparison.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    delta = now - dt

    total_seconds = int(delta.total_seconds())

    if total_seconds < 0:
        return "Just now"
    if total_seconds < 60:
        return "Just now"

    days = total_seconds // 86400
    remaining_seconds = total_seconds % 86400
    hours = remaining_seconds // 3600
    remaining_seconds = remaining_seconds % 3600
    minutes = remaining_seconds // 60

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hr{'s' if hours != 1 else ''}")
    if minutes > 0:
        parts.append(f"{minutes} min{'s' if minutes != 1 else ''}")

    if not parts:
        return "Just now"

    return " ".join(parts) + " ago"


def matches_resume(title: str) -> bool:
    """Check if the job title matches the user's technical skills profile.
    
    Excludes jobs explicitly targeting languages/technologies outside of
    the user's core stack (like Java, PHP, Angular, Vue, .NET, DevOps, QA, etc.).
    
    Args:
        title: The job title string to check.
        
    Returns:
        True if the job is a potential match, False otherwise.
    """
    if not title:
        return False
        
    title_lower = title.lower()
    
    # Negative keywords: technologies NOT in the user's stack
    # Exception: "javascript" contains "java", so we handle that specifically.
    negative_kws = [
        "c#", "c++", "c-sharp", "cplusplus", ".net", "php", "laravel", 
        "wordpress", "angular", "vue", "ruby", "rails", "android", "ios", 
        "flutter", "swift", "kotlin", "cobol", "sap", "salesforce", 
        "devops", "qa engineer", "quality assurance", "test engineer", 
        "manual tester", "selenium", "sysadmin", "system administrator", 
        "database administrator", "dba", "blockchain", "web3", "rust"
    ]
    
    # Handle the Javascript exception
    if "java" in title_lower:
        # Check if the title actually contains "javascript" or "java script"
        # If it does, we strip those out and check if "java" is still present
        stripped_java = title_lower.replace("javascript", "").replace("java script", "")
        if "java" in stripped_java:
            # Contains pure "java" (e.g. Java Developer) -> NOT a match
            return False
            
    # Check all other negative keywords
    for kw in negative_kws:
        if kw in title_lower:
            return False
            
    return True
